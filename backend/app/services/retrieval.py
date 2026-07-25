"""RAG OKUMA yolu (C4.3). Yazma yolu (chunk/olay/entity uretimi) generation.py'de.

Akis — CLAUDE.md "Embedding & Retrieval Kurallari"ndaki 7 adim:
  1. Sorgu = kullanicinin hamlesi + SON BOLUMUN KUYRUGU (~200 token). Sadece hamle yetmez:
     "iceri giriyorum" gibi kisa bir hamlenin vektoru hicbir seye benzemez, arama bos doner.
  2. chunk'larda vektor aramasi -> en iyi 5, SON N BOLUM HARIC (onlar zaten tam metin gidiyor).
  3. Her isabetin AYNI BOLUMDEKI chunk±1'i eklenir (sahnenin basi/sonu kesilmesin).
  4. Cakisan/bitisik chunk'lar TEK BLOGA birlesir (ayni metin iki kez gitmesin).
  5. Kronolojik siralanir (bolum, sonra chunk sirasi).
  6. RAG blogu toplam ~2000 token tavani; tavana vurunca EN DUSUK SKORLU bloktan kesilir.
  7. Olaylar da aranir ama prompta YALNIZCA chunk isabeti OLMAYAN bolumlerden, ayri blok
     olarak girer (ayni sey iki kez soylenmesin). Prompta GIREN olayin importance'i yukselir.

Bolum bazli n±1 penceresi ve content[:1200] (bolum BASINDAN alinti) mantigi KALKTI: sahne
bolumun sonundaysa bas alintida hic gorunmuyordu.
"""

import logging
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import embeddings
from ..ai.chunking import count_tokens, tail_by_tokens, truncate_by_tokens
from ..ai.prompts import entity_card_tokens
from ..models import Character, Chunk, Event, Item, Location, Story

logger = logging.getLogger(__name__)

CHUNK_RETRIEVAL_LIMIT = 5   # sorguya en yakin kac chunk cekilsin (adim 2)
EVENT_RETRIEVAL_LIMIT = 4   # sorguya en yakin kac olay cekilsin (adim 7)
QUERY_TAIL_TOKENS = 200     # sorguya eklenen son bolum kuyrugu (adim 1)
RAG_TOKEN_BUDGET = 2000     # RAG blogunun TOPLAM token tavani (adim 6; olaylar dahil)

# Son N bolum prompta ZATEN tam metin giriyor -> aramadan haric (adim 2). D3'te hikaye bazli
# ayar olacak (default 2, aralik 1-5); simdilik tek yerde sabit.
LAST_CHAPTERS_FULL_TEXT = 2

# Dinamik onem: prompta GIREN olayin importance'i AZALAN artisla yukselir, CEIL'i asmaz.
# new = old + (CEIL - old) * GROWTH -> her cekilis daha az ekler, hicbir sey 1.0'a kosmaz.
IMPORTANCE_CEIL = 0.95
IMPORTANCE_GROWTH = 0.2

# Pinned cekirdek (D3.1): SORGUDAN BAGIMSIZ olarak her uretimde giden olaylar. "1. bolumun
# baskarakteri 90. bolumde hala baglamda" garantisi budur — RAG bos donse bile giderler.
PINNED_MAX_EVENTS = 10
PINNED_TOKEN_BUDGET = 500
PINNED_CORE_ENTITIES = 3   # kac karakter "cekirdek" (protagonist/cok gecen) sayilsin
PINNED_CANDIDATE_POOL = 60  # importance'a gore cekilen aday olay sayisi (bellekte elenir)


# Entity karti secimi (D3.2): TUM kartlari her bolumde gondermek baglamin en buyuk israfi.
# Her zaman yalnizca ISIM listesi gider (model "bu isim zaten var" bilsin); TAM kartlar
# sahneye alakali olanlar icin.
SCENE_CARD_TOKEN_BUDGET = 800
SCENE_CARD_MAX = 12
SCENE_SEMANTIC_TOP = 4     # embed'le (anlamca) secilecek ek entity sayisi
NAME_PART_MIN = 3          # ismin ilk parcasi bu uzunluktaysa tek basina da aranir


@dataclass
class RetrievalResult:
    """RAG cikti paketi. Sadece metin degil, prompta NELERIN girdigi de doner:
    - event_ids: pinned cekirdek ayni olayi ikinci kez gondermesin diye
    - scene_chapter_ids / texts: D3.2 entity secimi "sahnede kim var" diye bakabilsin"""

    block: str | None = None
    event_ids: set[int] = field(default_factory=set)
    scene_chapter_ids: set[int] = field(default_factory=set)
    texts: list[str] = field(default_factory=list)
    # Sorgu vektoru: entity karti seciminde ANLAMSAL yakinlik icin yeniden kullanilir
    # (ikinci kez embed etmek ayni metin icin bir cagri + bir kota birimi daha harcardi).
    query_vec: list[float] | None = None


def build_retrieval_query(story: Story, user_action: str) -> str:
    """Adim 1 — sorgu zenginlestirme: hamle + son bolumun kuyrugu."""
    parts = [(user_action or "").strip()]
    if story.chapters:
        tail = tail_by_tokens(story.chapters[-1].content, QUERY_TAIL_TOKENS)
        if tail:
            parts.append(tail)
    return "\n\n".join(p for p in parts if p)


async def story_has_embedded_chunks(db: AsyncSession, story_id: int) -> bool:
    """Hikayede embed'lenmis en az bir chunk var mi? (Sorguyu bosuna embedlememek /
    kotayi harcamamak icin aramadan once ucuz kontrol. Chunk katmanindan onceki
    hikayelerde False doner -> olay yoluna dusulur, C4.4 backfill'i doldurana kadar.)"""
    stmt = select(Chunk.id).where(Chunk.story_id == story_id, Chunk.embedding.isnot(None)).limit(1)
    return (await db.execute(stmt)).first() is not None


async def story_has_embedded_events(db: AsyncSession, story_id: int) -> bool:
    """Hikayede embed'lenmis en az bir olay var mi?"""
    stmt = select(Event.id).where(Event.story_id == story_id, Event.embedding.isnot(None)).limit(1)
    return (await db.execute(stmt)).first() is not None


def _excluded_chapter_ids(story: Story) -> set[int]:
    """Son N bolumun id'leri: prompta zaten tam metin girdikleri icin aramadan cikarilir."""
    return {c.id for c in story.chapters[-LAST_CHAPTERS_FULL_TEXT:]} if story.chapters else set()


async def embed_query(db: AsyncSession, story: Story, query: str) -> list[float]:
    """Sorguyu TEK kez embedler; vektor chunk ve olay aramalarinda PAYLASILIR (ayri ayri
    embedlemek ayni metin icin iki API cagrisi + iki kota birimi harcardi)."""
    return (await embeddings.embed_for_user(db, story.user_id, [query]))[0]


async def find_relevant_chunks(
    db: AsyncSession,
    story: Story,
    query_vec: list[float],
    limit: int = CHUNK_RETRIEVAL_LIMIT,
    *,
    exclude_chapter_ids: set[int] | None = None,
) -> list[tuple[int, int, float]]:
    """Adim 2 — sorguya anlamca en yakin chunk'lar: (chapter_id, chunk_index, distance).
    Yalnizca embedding'i dolu chunk'lar aranir; sonuclar DUZ DEGER doner (ORM nesnesi degil:
    deferred embedding kolonu async'te lazy-load tetikleyip MissingGreenlet atar)."""
    stmt = (
        select(
            Chunk.chapter_id,
            Chunk.chunk_index,
            Chunk.embedding.cosine_distance(query_vec).label("dist"),
        )
        .where(Chunk.story_id == story.id, Chunk.embedding.isnot(None))
        .order_by("dist")
        .limit(limit)
    )
    if exclude_chapter_ids:
        stmt = stmt.where(Chunk.chapter_id.not_in(exclude_chapter_ids))
    rows = (await db.execute(stmt)).all()
    return [(chap_id, idx, float(dist)) for chap_id, idx, dist in rows]


async def expand_and_merge_chunks(
    db: AsyncSession, story: Story, hits: list[tuple[int, int, float]]
) -> list[dict]:
    """Adim 3-4-5 — her isabetin chunk±1'ini ekler, bitisik/cakisan chunk'lari TEK bloga
    birlestirir, kronolojik siralar. Dondurulen blok: {chapter_index, start, text, score}.
    score = blogu olusturan ISABETLERIN en iyi (en kucuk) mesafesi; token tavaninda bu
    kullanilir (komsu chunk'larin kendi mesafesi yoktur)."""
    if not hits:
        return []

    hit_chapter_ids = {chap_id for chap_id, _, _ in hits}
    # Isabet eden bolumlerin TUM chunk'larini tek sorguda cek (bolum basina birkac tane;
    # ±1 komsulari Python'da secmek ayri sorgulardan ucuz ve basit).
    rows = (
        await db.execute(
            select(Chunk.chapter_id, Chunk.chunk_index, Chunk.text).where(
                Chunk.chapter_id.in_(hit_chapter_ids)
            )
        )
    ).all()
    texts = {(chap_id, idx): text for chap_id, idx, text in rows}

    # Adim 3: istenen indeksler = her isabet ve komsulari (var olmayanlar dusulur)
    wanted: dict[int, set[int]] = {}
    best_dist: dict[tuple[int, int], float] = {}
    for chap_id, idx, dist in hits:
        best_dist[(chap_id, idx)] = min(dist, best_dist.get((chap_id, idx), dist))
        for neighbor in (idx - 1, idx, idx + 1):
            if (chap_id, neighbor) in texts:
                wanted.setdefault(chap_id, set()).add(neighbor)

    id_to_index = {c.id: c.index for c in story.chapters}
    blocks: list[dict] = []
    for chap_id, indices in wanted.items():
        # Adim 4: ardisik indeksleri tek bloga birlestir (ayni metin iki kez gitmesin)
        run: list[int] = []
        for idx in sorted(indices):
            if run and idx != run[-1] + 1:
                blocks.append(_make_block(chap_id, run, texts, best_dist, id_to_index))
                run = []
            run.append(idx)
        if run:
            blocks.append(_make_block(chap_id, run, texts, best_dist, id_to_index))

    # Adim 5: kronolojik (bolum, sonra chunk sirasi)
    blocks.sort(key=lambda b: (b["chapter_index"], b["start"]))
    return blocks


def _make_block(
    chap_id: int,
    run: list[int],
    texts: dict[tuple[int, int], str],
    best_dist: dict[tuple[int, int], float],
    id_to_index: dict[int, int],
) -> dict:
    dists = {i: best_dist[(chap_id, i)] for i in run if (chap_id, i) in best_dist}
    return {
        "chapter_id": chap_id,
        "chapter_index": id_to_index.get(chap_id, 0),
        "start": run[0],
        # parts: (chunk_index, metin) — daraltmada kenardan chunk atabilmek icin sinirlar korunur
        "parts": [(i, texts[(chap_id, i)]) for i in run],
        # Komsu-only blok olusamaz (her blokta en az bir isabet var), yine de savunmaci varsayilan
        "score": min(dists.values()) if dists else 1.0,
        # En iyi isabetin chunk indeksi: daraltirken bu chunk KORUNUR (alinti eslesmenin
        # etrafindan gelsin, blogun basindan degil)
        "best_index": min(dists, key=dists.get) if dists else run[0],
    }


def block_text(block: dict) -> str:
    """Blogun govdesi (basliksiz) — arama ucu pencereyi bununla doldurur."""
    return "\n\n".join(text for _, text in block["parts"])


def render_block(block: dict) -> str:
    """Blogun prompta girecek HALI (basligi dahil). Token tavani bunun uzerinden olculur —
    yalnizca govde sayilirsa basliklar tavani sessizce asirir."""
    return f"--- Chapter {block['chapter_index']} (scene) ---\n{block_text(block)}"


def _shrink_block(block: dict, budget: int) -> None:
    """Tek basina tavani asan blogu daraltir: EN IYI ISABETTEN uzak olan KENARDAN chunk atar
    (chunk sinirlari korunur). Boylece kirpma alintiyi eslesmenin etrafinda tutar — basindan
    kesip eslesmeyi dusurmez. Tek chunk bile sigmazsa son care olarak metin kirpilir."""
    while len(block["parts"]) > 1 and count_tokens(render_block(block)) > budget:
        first_idx = block["parts"][0][0]
        last_idx = block["parts"][-1][0]
        best = block["best_index"]
        # En iyi isabete UZAK olan ucu at
        if (best - first_idx) >= (last_idx - best):
            block["parts"].pop(0)
        else:
            block["parts"].pop()
        block["start"] = block["parts"][0][0]
    if count_tokens(render_block(block)) > budget:
        header_cost = count_tokens(f"--- Chapter {block['chapter_index']} (scene) ---\n")
        only_idx, only_text = block["parts"][0]
        block["parts"] = [(only_idx, truncate_by_tokens(only_text, max(budget - header_cost, 0)))]


def _apply_budget(blocks: list[dict], budget: int) -> tuple[list[dict], int]:
    """Adim 6 — token tavani: bloklar EN IYI SKORDAN baslayarak siraya alinir, sigan kabul
    edilir; sigmayan (en dusuk skorlu/en uzak) DUSER. Tek blok bile tavani asiyorsa
    _shrink_block ile daraltilir. Maliyet BASLIK DAHIL olculur (blok arasi "\\n\\n" ayirac
    dahil). Kabul edilenler yeniden KRONOLOJIK siralanir (adim 5 korunur)."""
    kept: list[dict] = []
    used = 0
    separator = count_tokens("\n\n")
    for block in sorted(blocks, key=lambda b: b["score"]):
        cost = count_tokens(render_block(block)) + (separator if kept else 0)
        if used + cost <= budget:
            kept.append(block)
            used += cost
        elif not kept:
            # En iyi blok tek basina tavani asiyor: daralt (bos RAG donmekten iyi). Daraltma
            # tam chunk atarak yapildigi icin tavanin altinda yer kalabilir — DEVAM et, kalan
            # yeri sonraki (daha kucuk) bloklar doldurabilsin.
            _shrink_block(block, budget)
            kept.append(block)
            used = count_tokens(render_block(block))
    kept.sort(key=lambda b: (b["chapter_index"], b["start"]))
    return kept, used


async def bump_event_importance(events: list[Event]) -> None:
    """Dinamik onem: prompta GERCEKTEN giren olaylarin importance'i (azalan artis, CEIL
    sinirli) ve retrieved_count'u yukselir. Yalnizca aramada eslesenler degil, baglama
    cekilenler yukselir — puan "ise yaradi" sinyali olsun diye."""
    for event in events:
        event.importance = min(
            IMPORTANCE_CEIL, event.importance + (IMPORTANCE_CEIL - event.importance) * IMPORTANCE_GROWTH
        )
        event.retrieved_count += 1


async def find_relevant_events(
    db: AsyncSession,
    story: Story,
    query_vec: list[float],
    limit: int = EVENT_RETRIEVAL_LIMIT,
    *,
    bump: bool = False,
    exclude_chapter_ids: set[int] | None = None,
) -> list[tuple[Event, float]]:
    """Sorguya anlamca en yakin olaylari (Event, distance) dondurur — OpenAI uzayinda cosine.
    bump=True ise eslesenlerin importance'i hemen yukselir (arama ucu bump YAPMAZ; uretim
    yolunda bump prompta GIRENLERE uygulanir, bkz. bump_event_importance).

    exclude_chapter_ids: bu bolumlerin olaylari SORGUDA elenir. Uretim yolunda chunk isabeti
    olan bolumler burada verilir — aksi halde limit'lik yer zaten sahne olarak giden bolumlere
    harcanir ve olay katmani hic katki yapamaz (filtre sorgudan SONRA uygulanirsa liste bosalir)."""
    stmt = (
        select(Event, Event.embedding.cosine_distance(query_vec).label("dist"))
        .where(Event.story_id == story.id, Event.embedding.isnot(None))
        .order_by("dist")
        .limit(limit)
    )
    if exclude_chapter_ids:
        stmt = stmt.where(Event.chapter_id.not_in(exclude_chapter_ids))
    rows = (await db.execute(stmt)).all()
    hits = [(event, float(dist)) for event, dist in rows]
    if bump:
        await bump_event_importance([e for e, _ in hits])
    return hits


def _format_scenes(blocks: list[dict]) -> str:
    return "\n\n".join(render_block(b) for b in blocks)


def core_entity_names(story: Story, events: list[Event], limit: int = PINNED_CORE_ENTITIES) -> list[str]:
    """Hikayenin "cekirdek" karakterleri: adi verilen olaylarda EN COK gecenler. Olay metinleri
    kendi basina anlasilir olacak sekilde (acik isimlerle, zamir YOK) uretildigi icin bu sayim
    protagonist/cok gecen karakteri ucuza ve LLM'siz yakalar."""
    texts = [(e.text or "").casefold() for e in events]
    counts: list[tuple[int, str]] = []
    for character in story.characters:
        name = (character.name or "").strip()
        if not name:
            continue
        folded = name.casefold()
        hits = sum(1 for t in texts if folded in t)
        if hits:
            counts.append((hits, name))
    counts.sort(key=lambda x: (-x[0], x[1]))
    return [name for _, name in counts[:limit]]


async def build_pinned_block(
    db: AsyncSession,
    story: Story,
    exclude_event_ids: set[int] | None = None,
    core_names: list[str] | None = None,
) -> str | None:
    """Pinned cekirdek: SORGUDAN BAGIMSIZ, her uretimde giden olaylar. Iki kaynak birlesir:
      1. En yuksek importance'li olaylar (hikayenin donum noktalari),
      2. Cekirdek karakterlere (protagonist/cok gecen) DOKUNAN olaylar — puani biraz dusuk
         olsa da surekliligin bel kemigi.
    RAG'le zaten gonderilen olaylar (exclude_event_ids) elenir: ayni sey iki kez gitmesin.
    Son N bolum de elenir (zaten tam metin gidiyorlar). Tavan: PINNED_MAX_EVENTS olay ve
    PINNED_TOKEN_BUDGET token — hangisi once dolarsa.

    Not: importance dinamiktir (RAG'le cekildikce yukselir), yani pinned kume zamanla
    hikayenin gercekten ise yarayan omurgasina dogru kayar."""
    excluded_chapters = _excluded_chapter_ids(story)
    exclude_event_ids = exclude_event_ids or set()

    rows = (
        await db.execute(
            select(Event)
            .where(Event.story_id == story.id)
            .order_by(Event.importance.desc(), Event.id)
            .limit(PINNED_CANDIDATE_POOL)
        )
    ).scalars().all()

    candidates = [
        e for e in rows if e.id not in exclude_event_ids and e.chapter_id not in excluded_chapters
    ]
    if not candidates:
        return None

    core = [n.casefold() for n in (core_names if core_names is not None else core_entity_names(story, rows))]
    # Cekirdek karaktere dokunan olaylar one alinir; esitlikte importance belirler.
    def rank(event: Event) -> tuple[int, float]:
        touches_core = any(n in (event.text or "").casefold() for n in core)
        return (0 if touches_core else 1, -event.importance)

    candidates.sort(key=rank)

    id_to_index = {c.id: c.index for c in story.chapters}
    lines: list[str] = []
    used = 0
    for event in candidates[:PINNED_MAX_EVENTS]:
        line = f"- Chapter {id_to_index.get(event.chapter_id, '?')}: {event.text}"
        cost = count_tokens(line)
        if used + cost > PINNED_TOKEN_BUDGET:
            break
        lines.append(line)
        used += cost

    if not lines:
        return None
    # Kronolojik okunsun (prompt icinde zaman akisi bozulmasin)
    lines.sort(key=lambda l: int(l.split()[2].rstrip(":")) if l.split()[2].rstrip(":").isdigit() else 0)
    return "\n".join(lines)


def name_regex(name: str) -> re.Pattern | None:
    """Bir entity ismini KELIME SINIRINA saygili arayan desen. Duz substring aramasi yanlis
    eslesir: "Ryu" -> "Ryuk" icinde bulunurdu. Tam isim VEYA ismin ILK parcasi (>=3 harf)
    aranir — soyad/lakap parcalari tek basina aranmaz (ortak soyadlar tum aileyi cekerdi)."""
    name = (name or "").strip()
    if not name:
        return None
    variants = {name}
    first = name.split()[0]
    if len(first) >= NAME_PART_MIN:
        variants.add(first)
    pattern = "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{pattern})(?!\w)", re.IGNORECASE | re.UNICODE)


def _mentioned_in(entities: list, haystacks: list[str]) -> set[int]:
    """Verilen metinlerde adi GECEN entity'lerin id kumesi."""
    blob = "\n".join(h for h in haystacks if h)
    if not blob:
        return set()
    found: set[int] = set()
    for entity in entities:
        pattern = name_regex(entity.name)
        if pattern and pattern.search(blob):
            found.add(entity.id)
    return found


async def _semantically_close_entities(
    db: AsyncSession, story_id: int, query_vec: list[float], limit: int
) -> list[tuple[object, float]]:
    """C4.2'de doldurulan entity embed'leriyle sorguya anlamca en yakin kartlar. Adi hic
    gecmese de sahneyle ilgili olani yakalar ("kilic" hamlesi -> 'Sunfire Sword' karti)."""
    hits: list[tuple[object, float]] = []
    for model in (Character, Location, Item):
        rows = (
            await db.execute(
                select(model, model.embedding.cosine_distance(query_vec).label("dist"))
                .where(model.story_id == story_id, model.embedding.isnot(None))
                .order_by("dist")
                .limit(limit)
            )
        ).all()
        hits.extend((entity, float(dist)) for entity, dist in rows)
    hits.sort(key=lambda pair: pair[1])
    return hits[:limit]


async def load_core_names(db: AsyncSession, story: Story) -> list[str]:
    """Cekirdek karakter isimleri — pinned cekirdek ve entity karti secimi AYNI listeyi
    kullanir (tek kaynak, tek sorgu)."""
    rows = (
        await db.execute(
            select(Event)
            .where(Event.story_id == story.id)
            .order_by(Event.importance.desc(), Event.id)
            .limit(PINNED_CANDIDATE_POOL)
        )
    ).scalars().all()
    return core_entity_names(story, rows)


def _by_kind(entities: list) -> dict[str, list]:
    grouped: dict[str, list] = {"characters": [], "locations": [], "items": []}
    for entity in entities:
        if isinstance(entity, Character):
            grouped["characters"].append(entity)
        elif isinstance(entity, Location):
            grouped["locations"].append(entity)
        elif isinstance(entity, Item):
            grouped["items"].append(entity)
    return grouped


async def select_entity_cards(
    db: AsyncSession,
    story: Story,
    user_action: str | None,
    result: RetrievalResult,
    core_names: list[str],
) -> tuple[dict[str, list], dict[str, list]]:
    """(sabit_cekirdek, sahneye_ozel) tam kartlarini secer. Geri kalan entity'ler prompta
    yalnizca ISIM olarak girer.

    SABIT CEKIRDEK: protagonist/cok gecen karakterler — bolumden bolume nadiren degisir,
    bu yuzden ERKEN (cache-dostu) konumda gider.
    SAHNEYE OZEL: hamlede adi gecenler + son N bolumde gecenler + RAG metinlerinde gecenler
    + sorguya anlamca yakin olanlar — her bolumde degisir, bu yuzden GEC konumda (RAG yaninda).
    Tavan: SCENE_CARD_MAX adet / SCENE_CARD_TOKEN_BUDGET token; asanlar isim listesinde kalir."""
    all_entities = [*story.characters, *story.locations, *story.items]
    core_folded = {n.casefold() for n in core_names}
    core = [e for e in story.characters if (e.name or "").casefold() in core_folded]
    core_ids = {e.id for e in core}
    candidates_pool = [e for e in all_entities if e.id not in core_ids]

    # --- Adaylari KATMANLI topla. Katman = kartin ne kadar ise yaradigi:
    #   0 hamlede adi geciyor      -> dogrudan sahnenin konusu
    #   1 RAG metinlerinde geciyor -> eski malzeme, baska turlu gorunmuyor
    #   2 sorguya anlamca yakin    -> adi gecmese de ilgili (C4.2 entity embed'leri)
    #   3 son N bolumde geciyor    -> EN DUSUK: o bolumler zaten TAM METIN gidiyor, model
    #     onlari okuyabiliyor; kart tekrar olur. Butce daralinca ilk bunlar duser.
    tiers: dict[int, int] = {}
    distances: dict[int, float] = {}

    for eid in _mentioned_in(candidates_pool, [user_action or ""]):
        tiers[eid] = 0
    for eid in _mentioned_in(candidates_pool, result.texts):
        tiers.setdefault(eid, 1)
    if result.query_vec is not None:
        try:
            for entity, distance in await _semantically_close_entities(
                db, story.id, result.query_vec, SCENE_SEMANTIC_TOP
            ):
                if entity.id not in core_ids:
                    tiers.setdefault(entity.id, 2)
                    distances[entity.id] = distance
        except Exception:
            logger.warning("Anlamsal entity secimi atlandi", exc_info=True)
    for eid in _mentioned_in(candidates_pool, [c.content for c in story.chapters[-LAST_CHAPTERS_FULL_TEXT:]]):
        tiers.setdefault(eid, 3)

    candidates = [e for e in candidates_pool if e.id in tiers]
    candidates.sort(key=lambda e: (tiers[e.id], distances.get(e.id, 1.0), e.name))

    # --- Tavan: maliyet KARTIN PROMPTA GIRECEGI HALIYLE olculur (status/bicim dahil),
    # yoksa butce sessizce asilir.
    selected: list = []
    used = 0
    for entity in candidates[:SCENE_CARD_MAX]:
        cost = entity_card_tokens(entity)
        if used + cost > SCENE_CARD_TOKEN_BUDGET:
            break
        selected.append(entity)
        used += cost

    return _by_kind(core), _by_kind(selected)


async def retrieve_context_block(db: AsyncSession, story: Story, user_action: str) -> RetrievalResult:
    """Prompta girecek RAG blogunu kurar (7 adimin tamami). Chunk'i olmayan hikayede olay
    yoluna duser (C4.4 backfill'i doldurana kadar); ikisi de yoksa None (RAG blogu atlanir,
    uretim ozet + son N bolum + entity ile devam eder).

    Sorgu vektoru TEK kez uretilir, chunk ve olay aramalarinda paylasilir (kota: cagri basina).
    Hikayede ne chunk ne olay varsa hic embed yapilmaz — bosuna kota harcanmaz."""
    query = build_retrieval_query(story, user_action)
    if not query:
        return RetrievalResult()

    has_chunks = await story_has_embedded_chunks(db, story.id)
    has_events = await story_has_embedded_events(db, story.id)
    if not has_chunks and not has_events:
        return RetrievalResult()

    query_vec = await embed_query(db, story, query)
    excluded = _excluded_chapter_ids(story)
    blocks: list[dict] = []
    if has_chunks:
        hits = await find_relevant_chunks(db, story, query_vec, exclude_chapter_ids=excluded)
        blocks = await expand_and_merge_chunks(db, story, hits)

    blocks, used = _apply_budget(blocks, RAG_TOKEN_BUDGET)
    scene_chapter_ids = {b["chapter_id"] for b in blocks}

    # Adim 7: olaylar — YALNIZCA chunk isabeti OLMAYAN bolumlerden, ayri blok olarak.
    event_lines: list[str] = []
    entering: list[Event] = []
    remaining = RAG_TOKEN_BUDGET - used
    if remaining > 0 and has_events:
        # Chunk isabeti olan bolumler + son N bolum SORGUDAN elenir: ayni sey iki kez
        # soylenmesin ve limit'lik yer zaten baglamda olan bolumlere harcanmasin.
        event_hits = await find_relevant_events(
            db, story, query_vec, exclude_chapter_ids=scene_chapter_ids | excluded
        )
        id_to_index = {c.id: c.index for c in story.chapters}
        for event, _ in event_hits:
            line = f"- Chapter {id_to_index.get(event.chapter_id, '?')}: {event.text}"
            cost = count_tokens(line)
            if cost > remaining:
                break
            event_lines.append(line)
            entering.append(event)
            remaining -= cost
        # Dinamik onem YALNIZCA prompta gercekten girenlere uygulanir
        await bump_event_importance(entering)

    parts = []
    if blocks:
        parts.append(_format_scenes(blocks))
    if event_lines:
        parts.append("Key events from other chapters:\n" + "\n".join(event_lines))
    return RetrievalResult(
        block="\n\n".join(parts) if parts else None,
        event_ids={e.id for e in entering},
        scene_chapter_ids=scene_chapter_ids,
        texts=[block_text(b) for b in blocks] + event_lines,
        query_vec=query_vec,
    )
