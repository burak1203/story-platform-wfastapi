import asyncio
import logging

from openai import RateLimitError
from sqlalchemy import delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import client as ai
from ..ai import embeddings
from ..ai.chunking import split_into_chunks
from ..ai.client import LlmCtx, LlmKeyInvalid
from ..ai.prompts import (
    ENTITY_EXTRACTION_PROMPT,
    EVENT_TEXT_CAP,
    MAX_EVENTS_PER_CHAPTER,
    SINGLE_CHAPTER_SUMMARY_PROMPT,
    build_chapter_system_prompt,
)
from ..database import SessionLocal
from ..models import Chapter, Character, Chunk, Event, Item, Location, Story
from ..schemas import story_detail
from .retrieval import retrieve_context_block
from .rollup import ensure_rollup
from .sse import broker

logger = logging.getLogger(__name__)

# Ayni hikaye icin ayni anda iki uretim calismasin diye hikaye bazli kilit.
# API katmanindaki atomik status guncellemesi ikinci savunma hattidir.
# _lock_refcount: her kilidi kac gorev tutuyor/bekliyor; sifira duserse kilit dict'ten
# ayiklanir (uzun omurlu serviste binlerce hikaye icin kilit sizmasin). Tek asyncio
# thread'inde setdefault+increment ve decrement+pop arasinda await olmadigi icin guvenli.
_story_locks: dict[int, asyncio.Lock] = {}
_lock_refcount: dict[int, int] = {}
_background_tasks: set[asyncio.Task] = set()

RETRIEVAL_MIN_CHAPTERS = 3  # bu kadar bolum birikmeden gecmis aramasi yapmaya gerek yok
EVENT_EMBED_BATCH = 128     # telafide tek seferde embedlenecek azami NULL olay/chunk sayisi
ENTITY_EMBED_BATCH = 64     # telafide tur basina azami NULL entity karti sayisi

# Lazy backfill (olay sisteminden onceki bolumler): her uretimde EN FAZLA bu kadar eski
# bolum islenir (kullanici yeni bolum uretirken 50 bolumluk backfill beklemesin), en yeni
# event'siz bolumden geriye dogru. Bir bolum ust uste basarisiz olursa MAX'a ulasinca artik
# denenmez (kullanicinin parasi bosuna yanmasin).
BACKFILL_PER_RUN = 3
MAX_BACKFILL_ATTEMPTS = 3

# Chunk backfill'i LLM ICERMEZ (duz metin bolme + tek batch embed) -> olay backfill'inden cok
# daha ucuz; koşu basina daha fazla bolum islenebilir. Yine de SSE'den SONRA calisir ve
# bounded'dir: 15 bolumluk bir hikaye iki uretimde tamamlanir, tek seferde hepsi yenmez.
CHUNK_BACKFILL_PER_RUN = 10


def schedule_generation(story_id: int, user_action: str | None, ctx: LlmCtx) -> None:
    """Bolum uretimini arka plana atar; endpoint aninda doner, sonuc SSE ile iletilir.
    Kullanicinin anahtari (ctx) yalnizca bu goreve arguman olarak tasinir."""
    task = asyncio.create_task(_run_generation(story_id, user_action, ctx))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _run_generation(story_id: int, user_action: str | None, ctx: LlmCtx) -> None:
    lock = _story_locks.setdefault(story_id, asyncio.Lock())
    _lock_refcount[story_id] = _lock_refcount.get(story_id, 0) + 1  # await'siz: atomik
    try:
        async with lock:
            try:
                async with SessionLocal() as db:
                    await _generate_chapter(db, story_id, user_action, ctx)
            except Exception as exc:
                # Saglayicinin ham hatasi kullaniciya gosterilmez (anahtar/detay sizdirmamak icin)
                if isinstance(exc, LlmKeyInvalid):
                    logger.warning("Hikaye %s: kullanicinin LLM anahtari reddedildi", story_id)
                    message = "API anahtarın sağlayıcı tarafından reddedildi. Ayarlar'dan anahtarını kontrol et."
                elif isinstance(exc, RateLimitError):
                    logger.warning("Hikaye %s: saglayici kota/hiz siniri", story_id)
                    message = "Sağlayıcının kota veya hız sınırına takıldın. Biraz bekleyip tekrar dene."
                else:
                    logger.exception("Hikaye %s icin bolum uretimi basarisiz oldu", story_id)
                    message = "Yapay zeka bölümü üretemedi. Lütfen tekrar dene."
                await _recover_status(story_id)
                broker.publish(story_id, {"type": "AI_ERROR", "message": message})
    finally:
        # Bu kilidi tutan/bekleyen kimse kalmadiysa dict'ten ayikla (await'siz: atomik)
        _lock_refcount[story_id] -= 1
        if _lock_refcount[story_id] <= 0:
            _lock_refcount.pop(story_id, None)
            _story_locks.pop(story_id, None)


async def _recover_status(story_id: int) -> None:
    """Uretim patlarsa hikayeyi kilitli birakma: bolumu olan hikaye tekrar COMPLETED,
    hic bolumu olmayan FAILED olur (continue ile yeniden denenebilir)."""
    try:
        async with SessionLocal() as db:
            story = await db.get(Story, story_id)
            if story is None:
                return
            story.status = "FAILED" if len(story.chapters) == 0 else "COMPLETED"
            await db.commit()
    except Exception:
        logger.exception("Hikaye %s statusu kurtarilamadi", story_id)


async def _generate_chapter(db: AsyncSession, story_id: int, user_action: str | None, ctx: LlmCtx) -> None:
    story = await db.get(Story, story_id)
    if story is None:  # uretim beklerken hikaye silinmis
        return

    await _repair_missing_derivatives(db, story, ctx)

    is_first = len(story.chapters) == 0

    retrieved_block = None
    if not is_first and user_action and len(story.chapters) >= RETRIEVAL_MIN_CHAPTERS:
        try:
            retrieved_block = await retrieve_context_block(db, story, user_action)
        except Exception:
            logger.warning("Gecmis bolum aramasi atlandi", exc_info=True)

    system_prompt = build_chapter_system_prompt(story, retrieved_block)
    # Kullanicinin hamlesi USER mesajinda (cache-dostu: sistem promptu sabit prefix, hamle degisken)
    user_message = (
        f"Story topic: {story.initial_prompt}" if is_first else f"Reader's move: {user_action}"
    )

    parsed = await ai.chat_json(ctx, ctx.story_model, system_prompt, user_message, temperature=0.8)
    content = str(parsed.get("content") or "").strip()
    if not content:
        raise ValueError("Model boş bölüm içeriği döndürdü.")

    # Bolum ozeti ayni cevaptan gelir; modelin yeni yazdigini en iyi yine kendisi ozetler
    summary = str(parsed.get("chapter_summary") or "").strip()[:2000] or None

    # NOT: chapters.embedding artik YAZILMAZ. Retrieval olay-embed'e (OpenAI uzayi) tasindi;
    # eski kolon GEMINI uzayindadir, dokunulmaz (yeni bolumlerde NULL kalir, sorgulanmaz).
    next_index = (story.chapters[-1].index + 1) if story.chapters else 1
    chapter = Chapter(story_id=story.id, index=next_index, content=content, summary=summary)
    db.add(chapter)
    await db.flush()  # olaylarin FK'si icin chapter.id gerekiyor
    dirty_entities = _apply_entities(db, story, parsed)
    created_events = _apply_events(db, story.id, chapter.id, parsed)
    await _embed_records(db, story.user_id, created_events)  # tek batch; patlarsa NULL kalir
    # Chunk katmani: bolumu deterministik parcalara bolup embedle (LLM YOK). Ayri batch cagri.
    created_chunks = await _apply_chunks(db, story.id, chapter.id, content)
    await _embed_records(db, story.user_id, created_chunks)
    # Entity kartlari: yalnizca YENI/DEGISEN olanlar (kullanimi D3'te). Degismeyen embedlenmez.
    await _embed_entities(db, story.user_id, dirty_entities)
    story.pending_edit_notes = None  # duzenleme notlari bu uretimde kullanildi
    story.status = "COMPLETED"
    await db.commit()

    # Bolum hazir: okuyucuya gonder
    story = await db.get(Story, story_id, populate_existing=True)
    if story is None:
        return
    broker.publish(story.id, story_detail(story).model_dump(by_alias=True, mode="json"))

    # Model chapter_summary vermediyse ucuz modelle telafi et
    if summary is None:
        try:
            fallback = await summarize_chapter(ctx, content)
            if fallback:
                for c in story.chapters:
                    if c.index == next_index:
                        c.summary = fallback
                await db.commit()
                broker.publish(story.id, story_detail(story).model_dump(by_alias=True, mode="json"))
        except Exception:
            logger.warning("Bolum ozeti telafi edilemedi (bolum kaydedildi)", exc_info=True)

    # Lazy backfill EN SON: bolum kullaniciya zaten gonderildi. Bounded + izole; patlarsa
    # uretim sonucu etkilenmez (asla _run_generation'a exception SIZDIRMA, yoksa basarili
    # uretim yanlislikla AI_ERROR olarak isaretlenir).
    # Sira: ONCE chunk (LLM yok -> hizli, retrieval kalitesini dogrudan yukseltir), SONRA olay
    # (LLM cagrisi basina saniyeler). Ikisi de kendi try'inda: biri patlarsa digeri calisir.
    try:
        await _backfill_chunks(db, story)
    except Exception:
        await db.rollback()
        logger.warning("Chunk backfill'i atlandi (uretim etkilenmedi)", exc_info=True)
    # Rollup (D2): eksik ark/arka plan ozetleri. Ozet blogunu sabit boyutta tutar; olay
    # backfill'inden ONCE, cunku prompt boyutuna dogrudan etkisi var.
    try:
        await ensure_rollup(db, story, ctx)
    except Exception:
        await db.rollback()
        logger.warning("Rollup atlandi (uretim etkilenmedi; ham ozetlerle devam)", exc_info=True)
    try:
        await _backfill_events(db, story, ctx)
    except Exception:
        logger.warning("Olay backfill'i atlandi (uretim etkilenmedi)", exc_info=True)


async def _repair_missing_derivatives(db: AsyncSession, story: Story, ctx: LlmCtx) -> None:
    """Onceki calismalarda uretilememis bolum ozetlerini + embedding'i NULL kalan olay VE
    chunk'lari tamamlar (idempotent: her uretimde eksikler yeniden denenir). Yazim aninda
    embedlenememis olay/chunk burada doldurulur. Basarisizlik uretimi engellemez.
    NOT: chapters.embedding'e DOKUNULMAZ (Gemini uzayi; retrieval artik olay/chunk-embed'de).
    Mevcut bolumler icin chunk URETIMI burada DEGIL, C4.4 backfill'inde yapilir (burasi yalnizca
    var olan chunk kayitlarinin NULL embedding'ini doldurur)."""
    try:
        for chapter in story.chapters:
            if chapter.summary is None:
                chapter.summary = await summarize_chapter(ctx, chapter.content)

        # embedding'i NULL kalan olaylari bul ve TEK batch cagriyla doldur (bounded)
        pending_events = (
            (
                await db.execute(
                    select(Event)
                    .where(Event.story_id == story.id, Event.embedding.is_(None))
                    .limit(EVENT_EMBED_BATCH)
                )
            )
            .scalars()
            .all()
        )
        await _embed_records(db, story.user_id, pending_events)

        # embedding'i NULL kalan chunk'lari da doldur (yazimda embed patlamis olabilir; bounded)
        pending_chunks = (
            (
                await db.execute(
                    select(Chunk)
                    .where(Chunk.story_id == story.id, Chunk.embedding.is_(None))
                    .limit(EVENT_EMBED_BATCH)
                )
            )
            .scalars()
            .all()
        )
        await _embed_records(db, story.user_id, pending_chunks)

        # embedding'i NULL kalan entity kartlari (C4.2 oncesi olusanlar + embed'i patlayanlar).
        # Uc tur TEK batch cagriya toplanir (kota: cagri basina). Aciklamasiz/durumsuz kartlar
        # sorguda elenir: embed edilecek metinleri yok, LIMIT'i bosuna doldurmasinlar.
        pending_entities: list = []
        for model in (Character, Location, Item):
            has_text = model.description != ""
            if model is Character:
                has_text = or_(has_text, Character.status.isnot(None))
            rows = (
                (
                    await db.execute(
                        select(model)
                        .where(model.story_id == story.id, model.embedding.is_(None), has_text)
                        .limit(ENTITY_EMBED_BATCH)
                    )
                )
                .scalars()
                .all()
            )
            pending_entities.extend(rows)
        await _embed_entities(db, story.user_id, pending_entities)
    except embeddings.EmbedQuotaExceeded:
        logger.warning("Kullanici %s embed kotasi doldu; telafi ertelendi", story.user_id)
    except Exception:
        logger.warning("Eksik ozet/olay-embed telafisi yarim kaldi", exc_info=True)
    finally:
        # Uretimin kendisi patlarsa bile tamamlanan telafiler kaybolmasin
        await db.commit()


async def summarize_chapter(ctx: LlmCtx, content: str) -> str | None:
    """Tek bolumun 2-3 cumlelik ozeti (uretim disi yollarda da kullanilir: bolum duzenleme)."""
    text = await ai.chat_text(
        ctx,
        ctx.util_model,
        SINGLE_CHAPTER_SUMMARY_PROMPT,
        f"Chapter to summarize:\n\n{content[:15000]}",
        temperature=0.3,
        max_tokens=512,
        reasoning=False,  # util isi: reasoning gereksiz + output olarak faturalanir
    )
    return text.strip() or None


async def apply_new_entities_from_edit(
    db: AsyncSession, story: Story, chapter_id: int, content: str, ctx: LlmCtx
) -> None:
    """Bolum DUZENLENDIGINDE cagrilir: duzenlenen metinden varliklari VE olaylari cikarir,
    YALNIZCA yeni girenleri ekler. Silme/hayalet-temizleme yok, mevcut varliklarin durumu
    degistirilmez (include_updates=False); olaylar da yalnizca eklenir (embedding'i C3 doldurur).
    Ana uretimde entity/olaylar uretim JSON'undan geldigi icin bu yol yalnizca duzenleme icindir."""
    parsed = await ai.chat_json(
        ctx,
        ctx.util_model,
        ENTITY_EXTRACTION_PROMPT,
        f"Chapter to process:\n\n{content[:15000]}",
        temperature=0.2,
        max_tokens=2048,
        reasoning=False,  # util isi: reasoning gereksiz + output olarak faturalanir
    )
    dirty_entities = _apply_entities(db, story, parsed, include_updates=False)
    created_events = _apply_events(db, story.id, chapter_id, parsed)
    await _embed_records(db, story.user_id, created_events)
    await _embed_entities(db, story.user_id, dirty_entities)


async def _backfill_chunks(db: AsyncSession, story: Story) -> int:
    """Chunk katmanindan ONCEKI bolumlere chunk uretir (lazy, bounded, idempotent).
    LLM YOK — duz metin bolme + tek batch embed, bu yuzden olay backfill'inden cok daha ucuz
    ve hizli; koşu basina daha fazla bolum islenebilir (CHUNK_BACKFILL_PER_RUN).

    DENEME SAYACI KOLONU GEREKMIYOR (olay backfill'indeki backfill_attempts'in muadili YOK):
      1. Idempotenslik bedava: "bu bolumun chunk'i var mi" sorgusu zaten filtre. Embed patlasa
         BILE chunk kayitlari NULL embedding ile YAZILIR, yani bolum bir daha secilmez.
      2. Korunacak bir deneme MALIYETI yok: olay backfill'i her denemede KULLANICININ
         anahtariyla LLM cagirir (para yanar) -> tavan sart. Burada bolme CPU'da bedava.
      3. Tek yeniden-deneme yolu (NULL embedding doldurma) zaten mevcut telafi adiminda ve
         kendi siniri (EVENT_EMBED_BATCH) ile bounded.
    Tek acik: icerigi BOS bir bolum 0 chunk uretip her koşuda yeniden secilirdi — sorguda
    `content != ''` filtresiyle kapatildi (uretim zaten bos icerik kaydetmiyor, savunmaci).

    En YENI chunk'siz bolumden geriye dogru: retrieval'da en cok ise yarayanlar onlar."""
    rows = (
        await db.execute(
            select(Chapter.id, Chapter.content)
            .where(
                Chapter.story_id == story.id,
                Chapter.content != "",
                ~select(Chunk.id).where(Chunk.chapter_id == Chapter.id).exists(),
            )
            .order_by(Chapter.index.desc())  # en yeni once
            .limit(CHUNK_BACKFILL_PER_RUN)
        )
    ).all()
    if not rows:
        return 0

    created: list[Chunk] = []
    for chap_id, content in rows:
        created.extend(await _apply_chunks(db, story.id, chap_id, content))
    # Embed'i dilimlere bol: 10 uzun bolum tek istekte saglayicinin token limitini zorlayabilir.
    # Embed patlarsa chunk'lar NULL ile KALIR (kayit korunur), telafi adimi doldurur.
    for i in range(0, len(created), EVENT_EMBED_BATCH):
        await _embed_records(db, story.user_id, created[i : i + EVENT_EMBED_BATCH])
    await db.commit()
    logger.info("Hikaye %s: %s bolum icin %s chunk backfill edildi", story.id, len(rows), len(created))
    return len(rows)


async def _backfill_events(db: AsyncSession, story: Story, ctx: LlmCtx) -> None:
    """Olay sisteminden onceki bolumlerden EKSIK OLAY katmanini cikarir (lazy, bounded,
    idempotent). YALNIZCA olay: eski bolumlerin entity'leri orijinal uretimde zaten cikarildi,
    burada entity eklemek (tekrar eden protagonist -> characters unique-constraint) hem
    gereksiz hem riskli. Constraint'ler: (1) her koşuda EN FAZLA BACKFILL_PER_RUN bolum;
    (2) uretimi BLOKLAMAZ — asil bolum zaten SSE ile gonderildi, buradaki patlama izole edilir;
    (3) en YENI event'siz bolumden geriye dogru (retrieval'da en cok ise yarar); (4) sonsuz
    deneme yok — backfill_attempts >= MAX ise atlanir.

    Cikarim KULLANICI anahtariyla (ctx), embed SUNUCU anahtariyla (embed_for_user).
    Aday bolumler DUZ DEGER olarak cekilir: commit/rollback arasi ORM nesnesi tutmak async'te
    bayat-nesne/lazy-load sorunlari cikarir."""
    rows = (
        await db.execute(
            select(Chapter.id, Chapter.index, Chapter.content, Chapter.backfill_attempts)
            .where(
                Chapter.story_id == story.id,
                Chapter.backfill_attempts < MAX_BACKFILL_ATTEMPTS,
                ~select(Event.id).where(Event.chapter_id == Chapter.id).exists(),
            )
            .order_by(Chapter.index.desc())  # en yeni once
            .limit(BACKFILL_PER_RUN)
        )
    ).all()
    for chap_id, chap_index, content, attempts in rows:
        # Denemeyi ONCE kalicilastir: cikarim patlasa bile sayilsin (sonsuz retry olmasin).
        await db.execute(update(Chapter).where(Chapter.id == chap_id).values(backfill_attempts=attempts + 1))
        await db.commit()
        try:
            parsed = await ai.chat_json(
                ctx,
                ctx.util_model,
                ENTITY_EXTRACTION_PROMPT,
                f"Chapter to process:\n\n{content[:15000]}",
                temperature=0.2,
                max_tokens=2048,
                reasoning=False,  # util isi: reasoning gereksiz + output olarak faturalanir
            )
            created = _apply_events(db, story.id, chap_id, parsed)
            await _embed_records(db, story.user_id, created)
            await db.commit()
        except Exception:
            # Bu bolumun yarim kalan event'lerini geri al (attempts zaten commit'li);
            # digerlerini denemeye devam et. Uretim etkilenmez.
            await db.rollback()
            logger.warning(
                "Bolum %s olay backfill'i basarisiz (deneme %s/%s)",
                chap_index, attempts + 1, MAX_BACKFILL_ATTEMPTS, exc_info=True,
            )


def _clean_entries(raw, *fields: str) -> list[dict]:
    """LLM'den gelen listeyi savunmaci sekilde temizler: dict olmayanlari,
    ismi bos olanlari eler; alanlari string'e cevirip kirpar."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()[:120]
        if not name:
            continue
        item = {"name": name}
        for field in fields:
            item[field] = str(entry.get(field) or "").strip()[:1000]
        cleaned.append(item)
    return cleaned


def _apply_entities(db: AsyncSession, story: Story, parsed: dict, *, include_updates: bool = True) -> list:
    """Cikarilan varliklari isimle upsert eder; ayni isim ikinci kez kaydedilmez.
    include_updates=False iken yalnizca YENI varliklar eklenir (updated_characters yok
    sayilir): bolum duzenleme yolunda mevcut karakterin durumu clobber'lanmasin ve
    hicbir sey silinmesin diye.

    Embed metni (description/status) DEGISEN veya yeni olusturulan entity'leri dondurur;
    cagiran bunlari tek batch cagriyla embedler. Degismeyen entity yeniden embed EDILMEZ
    (gereksiz cagri/kota harcanmasin)."""
    chars = {c.name.casefold(): c for c in story.characters}
    locs = {l.name.casefold(): l for l in story.locations}
    items = {i.name.casefold(): i for i in story.items}
    dirty: dict[int, object] = {}  # id(obj) -> obj (ayni entity iki kez degisirse tek kez embed)

    def touched(obj) -> None:
        # Bayat vektoru gecersiz kil: yeniden embed patlarsa NULL kalir ve telafi yolu
        # (embedding IS NULL taramasi) onu yakalar. Deferred kolona YAZMAK lazy-load tetiklemez.
        obj.embedding = None
        dirty[id(obj)] = obj

    for entry in _clean_entries(parsed.get("new_characters"), "description"):
        key = entry["name"].casefold()
        if key in chars:
            if entry["description"] and not chars[key].description:
                chars[key].description = entry["description"]
                touched(chars[key])
            continue
        obj = Character(story_id=story.id, name=entry["name"], description=entry["description"])
        db.add(obj)
        chars[key] = obj
        touched(obj)

    if include_updates:
        for entry in _clean_entries(parsed.get("updated_characters"), "status_change"):
            key = entry["name"].casefold()
            obj = chars.get(key)
            if obj is None:
                # Model "bilinen" sanip yeni bir isim de verebilir; kaybetmek yerine olustur
                obj = Character(story_id=story.id, name=entry["name"], description="")
                db.add(obj)
                chars[key] = obj
                touched(obj)
            if entry["status_change"] and entry["status_change"] != obj.status:
                obj.status = entry["status_change"]
                touched(obj)

    for entry in _clean_entries(parsed.get("new_locations"), "description"):
        key = entry["name"].casefold()
        if key not in locs:
            obj = Location(story_id=story.id, name=entry["name"], description=entry["description"])
            db.add(obj)
            locs[key] = obj
            touched(obj)

    for entry in _clean_entries(parsed.get("new_items"), "description"):
        key = entry["name"].casefold()
        if key not in items:
            obj = Item(story_id=story.id, name=entry["name"], description=entry["description"])
            db.add(obj)
            items[key] = obj
            touched(obj)

    return list(dirty.values())


def _clean_events(raw) -> list[dict]:
    """LLM'den gelen olay listesini savunmaci temizler: text bos olanlari eler, importance'i
    0.0-1.0'a kelepceler (model tanimsiz/gecersiz verirse 0.5), metni kirpar, en fazla
    MAX_EVENTS_PER_CHAPTER olay dondurur (uzun bolumde onlarca olay birikmesin)."""
    if not isinstance(raw, list):
        return []
    cleaned: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        text = str(entry.get("text") or "").strip()[:EVENT_TEXT_CAP]
        if not text:
            continue
        try:
            importance = float(entry.get("importance"))
        except (TypeError, ValueError):
            importance = 0.5
        importance = min(1.0, max(0.0, importance))
        cleaned.append({"text": text, "importance": importance})
        if len(cleaned) >= MAX_EVENTS_PER_CHAPTER:
            break
    return cleaned


def _apply_events(db: AsyncSession, story_id: int, chapter_id: int, parsed: dict) -> list[Event]:
    """Cikarilan olaylari events tablosuna EKLER ve olusturulan Event nesnelerini dondurur
    (cagiran bunlari tek batch cagriyla embedler). embedding once NULL'dur; silme yok —
    dusuk importance sadece omurgaya girmemek demek, depodan silinmek degil."""
    created: list[Event] = []
    for ev in _clean_events(parsed.get("events")):
        obj = Event(
            story_id=story_id,
            chapter_id=chapter_id,
            text=ev["text"],
            importance=ev["importance"],
        )
        db.add(obj)
        created.append(obj)
    return created


def _record_text(record) -> str:
    """Varsayilan metin cikarici: Event/Chunk icin .text."""
    return record.text or ""


def entity_embed_text(entity) -> str:
    """Entity kartinin embed metni: name + description (+ karakterde status). Kart SECIMI icin
    (D3: hangi kartlar prompta girecek) — C4.2'de yalnizca doldurulur, kullanilmaz.

    Isim DAHIL: isimler cogu zaman anlam tasir ("Sunfire Sword", "North Tower"); aciklama
    zayifsa eslesmeyi isim kurtarir. NOT: isim degisirse embed metni de degisir, yani
    yeniden embed edilir (update_element'teki karsilastirma bunu dogal olarak yakalar)."""
    parts = [entity.name or "", entity.description or ""]
    status = getattr(entity, "status", None)
    if status:
        parts.append(status)
    return "\n".join(p for p in parts if p.strip()).strip()


async def _embed_records(db: AsyncSession, user_id: int, records: list, text_of=_record_text) -> None:
    """Verilen kayitlari TEK embeddings cagrisiyla (batch) embedler. Kota bu yola baglidir
    (embed_for_user -> consume_quota). Cagri patlarsa kayitlar embedding'siz (NULL) kalir ve
    uretim BLOKLANMAZ; sonraki telafi adiminda yeniden denenir.

    text_of: kayittan embed metnini ureten callable. Varsayilan .text (Event/Chunk); entity'ler
    icin entity_embed_text gecilir (alan adi .description (+ .status)). Boylece tek batch yolu
    uc kayit turunu de tasir. Metni bos olanlar elenir (embed edilecek bir sey yok).

    Cagiranlar yalnizca embed'lenmesi gereken kayitlari verir (yeni olusturulanlar, degisenler
    ya da 'embedding IS NULL' ile sorgulanmis olanlar); burada r.embedding'i OKUMA — deferred
    kolon oldugu icin async'te lazy-load tetikleyip MissingGreenlet atar (yazmak sorunsuz)."""
    pending = [(r, t) for r in records if (t := text_of(r).strip())]
    if not pending:
        return
    try:
        vectors = await embeddings.embed_for_user(db, user_id, [t for _, t in pending])
    except embeddings.EmbedQuotaExceeded:
        logger.warning("Kullanici %s embed kotasi doldu; kayitlar NULL embedding ile kaldi", user_id)
        return
    except Exception:
        logger.warning("Embedleme basarisiz; kayitlar NULL embedding ile kaydedildi", exc_info=True)
        return
    for (record, _), vector in zip(pending, vectors):
        record.embedding = vector


async def _embed_entities(db: AsyncSession, user_id: int, entities: list) -> None:
    """Karakter/mekan/esya kartlarini TEK batch cagriyla embedler (karisik liste verilebilir).
    Bos aciklamali entity'ler _embed_records icinde elenir."""
    await _embed_records(db, user_id, entities, text_of=entity_embed_text)


async def embed_entities_safely(db: AsyncSession, user_id: int, entities: list) -> None:
    """Router'lar icin (Studio'dan elle entity ekleme/duzenleme): entity embed'ini dener,
    HICBIR durumda hata firlatmaz. Embed patlarsa entity NULL embedding ile kaydedilir ve
    telafi yolu (bir sonraki uretimde NULL taramasi) doldurur — kullanicinin kaydi engellenmez."""
    try:
        await _embed_entities(db, user_id, entities)
    except Exception:
        logger.warning("Entity embed'i atlandi (kayit etkilenmedi)", exc_info=True)


async def _apply_chunks(db: AsyncSession, story_id: int, chapter_id: int, content: str) -> list[Chunk]:
    """Bolumu deterministik olarak ~400-600 token'lik parcalara boler ve chunks tablosuna yazar.
    IDEMPOTENT: bu bolumun ESKI chunk'larini once siler, sonra yenilerini ekler — duzenlemede
    yetim chunk kalmaz, indeks tekrari olmaz. LLM YOK (split_into_chunks duz metin bolme).
    embedding NULL baslar; cagiran _embed_records ile tek batch embedler."""
    await db.execute(delete(Chunk).where(Chunk.chapter_id == chapter_id))
    created: list[Chunk] = []
    for i, text in enumerate(split_into_chunks(content)):
        obj = Chunk(story_id=story_id, chapter_id=chapter_id, chunk_index=i, text=text)
        db.add(obj)
        created.append(obj)
    return created


async def rebuild_chapter_chunks(db: AsyncSession, story: Story, chapter_id: int, content: str) -> None:
    """Bolum DUZENLENDIGINDE cagrilir: bolumun chunk'larini yeniden bolup embedler (idempotent).
    LLM icermedigi icin entity/olay cikariminden (apply_new_entities_from_edit) BAGIMSIZ — biri
    patlasa digeri calisir. Embed patlarsa chunk'lar NULL kalir, telafi doldurur."""
    created = await _apply_chunks(db, story.id, chapter_id, content)
    await _embed_records(db, story.user_id, created)


# NOT: RAG OKUMA yolu (chunk arama, ±1 penceresi, birlestirme, token tavani, olay blogu)
# services/retrieval.py'ye tasindi. Bu dosya YAZMA yolunda kaldi (chunk/olay/entity uretimi).
# Eski bolum bazli n±1 penceresi ve content[:1200] (bolum BASINDAN alinti) mantigi KALDIRILDI.
