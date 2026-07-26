import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import embeddings
from ..ai.client import LlmCtx
from ..database import get_db
from ..models import (
    READABLE_WITHOUT_OWNER,
    VISIBILITY_PUBLIC,
    PromptItem,
    Story,
    User,
)
from ..ai.prompts import parse_edit_notes
from ..schemas import (
    MAX_PROMPT_ITEM_LEN,
    MAX_PROMPT_ITEMS,
    MAX_TAG_LEN,
    MAX_TAGS,
    ContinueStoryRequest,
    CreatePromptItemRequest,
    CreateStoryRequest,
    EditChapterRequest,
    EditChapterSummaryRequest,
    ReorderPromptItemsRequest,
    SearchHit,
    SearchWindowChapter,
    StoryDetailResponse,
    StorySummaryResponse,
    UpdatePromptItemRequest,
    UpdatePublishingRequest,
    UpdateStorySettingsRequest,
    story_detail,
    story_summary,
)
from ..ratelimit import GENERATION_LIMIT, SEARCH_LIMIT, limiter
from ..security import get_current_user, get_llm_ctx
from ..services.generation import (
    apply_new_entities_from_edit,
    rebuild_chapter_chunks,
    schedule_generation,
    summarize_chapter,
)
from ..services.retrieval import (
    block_text,
    embed_query,
    expand_and_merge_chunks,
    find_relevant_chunks,
    find_relevant_events,
    story_has_embedded_chunks,
    story_has_embedded_events,
)
from ..services.rollup import invalidate_for_chapter
from ..services.sse import broker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stories", tags=["stories"])

BUSY_STATUSES = ("PENDING", "GENERATING")
SSE_KEEPALIVE_SECONDS = 15


async def _get_owned_story(story_id: int, user: User, db: AsyncSession) -> Story:
    story = await db.get(Story, story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Hikaye bulunamadı.")
    if story.user_id != user.id:
        raise HTTPException(status_code=403, detail="Bu hikayeye erişim yetkiniz yok.")
    return story


@router.get("/my-stories", response_model=list[StorySummaryResponse])
async def my_stories(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stories = (
        (await db.execute(select(Story).where(Story.user_id == user.id).order_by(Story.id.desc())))
        .scalars()
        .all()
    )
    return [story_summary(s) for s in stories]


@router.post("", response_model=StoryDetailResponse)
@limiter.limit(GENERATION_LIMIT)
async def create_story(
    request: Request,
    payload: CreateStoryRequest,
    user: User = Depends(get_current_user),
    ctx: LlmCtx = Depends(get_llm_ctx),
    db: AsyncSession = Depends(get_db),
):
    title = payload.title.strip()
    prompt = payload.starting_prompt.strip()
    if not title or not prompt:
        raise HTTPException(status_code=400, detail="Başlık ve başlangıç konusu boş olamaz.")

    story = Story(user_id=user.id, title=title, status="PENDING", initial_prompt=prompt)
    db.add(story)
    await db.flush()  # maddelerin FK'si icin story.id gerekiyor
    # Olusturma formundaki talimatlar ilk MADDE olarak kaydedilir (bos olanlar madde uretmez)
    for order, (kind, raw) in enumerate(
        (("style", payload.style_prompt), ("negative", payload.negative_prompt))
    ):
        text_value = (raw or "").strip()
        if text_value:
            db.add(
                PromptItem(
                    story_id=story.id, kind=kind, text=text_value[:MAX_PROMPT_ITEM_LEN],
                    enabled=True, order=order,
                )
            )
    await db.commit()
    # Yeni eklenen nesnenin iliskileri yuklu degil; async'te lazy-load patladigi icin tazele
    story = await db.get(Story, story.id, populate_existing=True)

    schedule_generation(story.id, None, ctx)
    return story_detail(story)


@router.get("/{story_id}", response_model=StoryDetailResponse)
async def get_story(
    story_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    story = await _get_owned_story(story_id, user, db)
    return story_detail(story)


@router.post("/{story_id}/continue")
@limiter.limit(GENERATION_LIMIT)
async def continue_story(
    request: Request,
    story_id: int,
    payload: ContinueStoryRequest,
    user: User = Depends(get_current_user),
    ctx: LlmCtx = Depends(get_llm_ctx),
    db: AsyncSession = Depends(get_db),
):
    action = payload.user_action.strip()
    if not action:
        raise HTTPException(status_code=400, detail="Hamle boş olamaz.")

    story = await _get_owned_story(story_id, user, db)

    # Hic bolum yoksa (ilk uretim FAILED olduysa) bastan ilk bolum uretilir
    new_status = "PENDING" if len(story.chapters) == 0 else "GENERATING"

    # Atomik durum gecisi: iki es zamanli istekten yalnizca biri uretimi baslatabilir
    result = await db.execute(
        update(Story)
        .where(Story.id == story_id, Story.status.not_in(BUSY_STATUSES))
        .values(status=new_status)
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bu hikaye için zaten bir bölüm üretiliyor, lütfen bitmesini bekleyin.",
        )

    schedule_generation(story_id, action, ctx)
    return {"status": new_status}


@router.delete("/{story_id}")
async def delete_story(
    story_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    story = await _get_owned_story(story_id, user, db)
    await db.delete(story)
    await db.commit()
    return {"deleted": story_id}


@router.put("/{story_id}/settings", response_model=StoryDetailResponse)
async def update_story_settings(
    story_id: int,
    request: UpdateStorySettingsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hikaye bazli uretim ayarlari. Talimat maddeleri ayri uclarda (prompt-items)."""
    story = await _get_owned_story(story_id, user, db)
    story.last_chapters_full_text = request.last_chapters_full_text
    await db.commit()
    story = await db.get(Story, story_id, populate_existing=True)
    return story_detail(story)


def _normalize_tags(raw: list[str] | None) -> list[str]:
    """Etiketleri normalize eder: kirp, kucult, bosları ele, TEKRARI KALDIR (sira korunur).
    Normalizasyon YAZMA aninda yapilir ki arama tarafinda her sorguda tekrar edilmesin."""
    if raw is None:
        return []
    seen: set[str] = set()
    tags: list[str] = []
    for item in raw:
        tag = " ".join(str(item).split()).lower()[:MAX_TAG_LEN]
        if tag and tag not in seen:
            seen.add(tag)
            tags.append(tag)
    return tags[:MAX_TAGS]


@router.put("/{story_id}/publishing", response_model=StoryDetailResponse)
async def update_publishing(
    story_id: int,
    payload: UpdatePublishingRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Yayimlama ayarlari: gorunurluk, aciklama, etiketler, yetiskin isareti.

    IKI SERT KURAL:
      1. public + is_adult YASAK — bastan engellenir (operator TR'de, 5651). Faz 4'e
         birakilmaz: yasak icerigin bir an bile yayinda olmamasi gerekir.
      2. public'e gecerken kurallar onayi (rules_accepted) ZORUNLU.
    published_at yalnizca ILK yayimda doldurulur: yayindan alip geri koyarak ana sayfada
    one cikma (gaming) engellensin."""
    story = await _get_owned_story(story_id, user, db)

    is_adult = payload.is_adult
    if payload.visibility == VISIBILITY_PUBLIC and is_adult:
        raise HTTPException(
            status_code=400,
            detail="Yetişkin içerik olarak işaretlenen hikaye herkese açık yayımlanamaz.",
        )
    if payload.visibility == VISIBILITY_PUBLIC and story.visibility != VISIBILITY_PUBLIC:
        if not payload.rules_accepted:
            raise HTTPException(
                status_code=400, detail="Yayımlamak için içerik kurallarını onaylaman gerekiyor."
            )
        if not story.chapters:
            raise HTTPException(status_code=400, detail="Boş hikaye yayımlanamaz.")

    story.visibility = payload.visibility
    story.is_adult = is_adult
    if payload.description is not None:
        story.description = payload.description.strip() or None
    if payload.tags is not None:
        story.tags = _normalize_tags(payload.tags)
    if story.visibility in READABLE_WITHOUT_OWNER and story.published_at is None:
        story.published_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await db.commit()
    story = await db.get(Story, story_id, populate_existing=True)
    return story_detail(story)


# --- Yazarin talimat maddeleri (D3.3): tek blob yerine sirali, tek tek acilip kapanan liste ---


async def _get_owned_prompt_item(story_id: int, item_id: int, user: User, db: AsyncSession) -> PromptItem:
    """Sahiplik: madde hem kullaniciya ait hikayeye hem de URL'deki hikayeye ait olmali (IDOR)."""
    await _get_owned_story(story_id, user, db)
    item = await db.get(PromptItem, item_id)
    if item is None or item.story_id != story_id:
        raise HTTPException(status_code=404, detail="Talimat maddesi bulunamadı.")
    return item


@router.post("/{story_id}/prompt-items", response_model=StoryDetailResponse)
async def create_prompt_item(
    story_id: int,
    payload: CreatePromptItemRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    story = await _get_owned_story(story_id, user, db)
    text_value = payload.text.strip()
    if not text_value:
        raise HTTPException(status_code=400, detail="Talimat boş olamaz.")
    if len(story.prompt_items) >= MAX_PROMPT_ITEMS:
        raise HTTPException(
            status_code=400, detail=f"En fazla {MAX_PROMPT_ITEMS} talimat maddesi ekleyebilirsin."
        )
    next_order = max((p.order for p in story.prompt_items), default=-1) + 1
    db.add(
        PromptItem(
            story_id=story.id, kind=payload.kind, text=text_value, enabled=True, order=next_order
        )
    )
    await db.commit()
    story = await db.get(Story, story_id, populate_existing=True)
    return story_detail(story)


@router.put("/{story_id}/prompt-items/{item_id}", response_model=StoryDetailResponse)
async def update_prompt_item(
    story_id: int,
    item_id: int,
    payload: UpdatePromptItemRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Metni ve/veya aciklik durumunu gunceller (ac-kapa da bu uctan)."""
    item = await _get_owned_prompt_item(story_id, item_id, user, db)
    if payload.text is not None:
        text_value = payload.text.strip()
        if not text_value:
            raise HTTPException(status_code=400, detail="Talimat boş olamaz.")
        item.text = text_value
    if payload.enabled is not None:
        item.enabled = payload.enabled
    await db.commit()
    story = await db.get(Story, story_id, populate_existing=True)
    return story_detail(story)


@router.delete("/{story_id}/prompt-items/{item_id}", response_model=StoryDetailResponse)
async def delete_prompt_item(
    story_id: int,
    item_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await _get_owned_prompt_item(story_id, item_id, user, db)
    await db.delete(item)
    await db.commit()
    story = await db.get(Story, story_id, populate_existing=True)
    return story_detail(story)


@router.put("/{story_id}/prompt-items", response_model=StoryDetailResponse)
async def reorder_prompt_items(
    story_id: int,
    payload: ReorderPromptItemsRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Maddeleri verilen id sirasina gore yeniden siralar. Listede olmayanlar (yarista eklenmis
    olabilir) mevcut sirasini koruyarak sona alinir — hicbir madde kaybolmaz."""
    story = await _get_owned_story(story_id, user, db)
    by_id = {p.id: p for p in story.prompt_items}
    ordered = [by_id[i] for i in payload.item_ids if i in by_id]
    remaining = [p for p in sorted(story.prompt_items, key=lambda p: (p.order, p.id)) if p.id not in set(payload.item_ids)]
    for position, item in enumerate([*ordered, *remaining]):
        item.order = position
    await db.commit()
    story = await db.get(Story, story_id, populate_existing=True)
    return story_detail(story)


@router.put("/{story_id}/chapters/{chapter_index}", response_model=StoryDetailResponse)
@limiter.limit(GENERATION_LIMIT)
async def edit_chapter(
    request: Request,
    story_id: int,
    chapter_index: int,
    payload: EditChapterRequest,
    user: User = Depends(get_current_user),
    ctx: LlmCtx = Depends(get_llm_ctx),
    db: AsyncSession = Depends(get_db),
):
    new_content = payload.new_content.strip()
    if not new_content:
        raise HTTPException(status_code=400, detail="Bölüm içeriği boş olamaz.")

    story = await _get_owned_story(story_id, user, db)
    if story.status in BUSY_STATUSES:
        raise HTTPException(status_code=409, detail="Üretim sürerken bölüm düzenlenemez.")

    chapter = next((c for c in story.chapters if c.index == chapter_index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Bölüm bulunamadı.")

    old_summary = chapter.summary
    chapter.content = new_content

    # NOT: chapters.embedding'e ARTIK YAZILMAZ (eski Gemini uzayi, C4.2'de dusuruluyor; retrieval
    # olay/chunk-embed'de). Icerik degisince vektor hafiza chunk katmaninda yenilenir (asagida).

    # Chunk katmanini guncel metne gore yeniden bol+embedle (idempotent, LLM YOK). Entity/olay
    # cikariminin patlamasindan bagimsiz; kendi try/except'inde.
    try:
        await rebuild_chapter_chunks(db, story, chapter.id, new_content)
    except Exception:
        logger.warning("Duzenlenen bolumun chunk'lari yenilenemedi", exc_info=True)

    # Ozeti guncel metne gore yeniden cikar. Basarisizsa eski (artik yanlis) ozeti
    # tutmak yerine None birak; bir sonraki uretimdeki telafi adimi tamamlar.
    try:
        chapter.summary = await summarize_chapter(ctx, new_content)
    except Exception:
        logger.warning("Duzenlenen bolum yeniden ozetlenemedi", exc_info=True)
        chapter.summary = None

    # Duzenlenen metinde yeni beliren karakter/mekan/esyalar evrene EKLENIR. Yalnizca
    # ekleme: hicbir sey otomatik silinmez, mevcut varliklarin durumu degistirilmez
    # (silme yalnizca Studio'dan elle). Cikarim patlarsa duzenlemeyi engelleme.
    try:
        await apply_new_entities_from_edit(db, story, chapter.id, new_content, ctx)
    except Exception:
        logger.warning("Duzenlenen bolumden entity/olay cikarimi atlandi", exc_info=True)

    # Bolumun ozeti degisti -> onu iceren ark (ve kapsayan arka plan) bayat: gecersiz kil.
    # Yalnizca ILGILI ark silinir; bir sonraki uretimde yeniden uretilir, o ana kadar prompt
    # bu aralik icin ham bolum ozetlerine duser.
    await invalidate_for_chapter(db, story.id, chapter_index)

    # Bir SONRAKI uretime tasinacak not: modele "burada su degisti" diye soyle
    notes = parse_edit_notes(story.pending_edit_notes)
    notes.append(
        f"Bölüm {chapter_index} yazar tarafından değiştirildi. "
        f"Eski özeti: {old_summary or '(yoktu)'} | Güncel özeti: {chapter.summary or '(özetlenemedi)'}"
    )
    story.pending_edit_notes = json.dumps(notes[-5:], ensure_ascii=False)

    await db.commit()
    story = await db.get(Story, story_id, populate_existing=True)
    return story_detail(story)


@router.put("/{story_id}/chapters/{chapter_index}/summary", response_model=StoryDetailResponse)
async def edit_chapter_summary(
    story_id: int,
    chapter_index: int,
    request: EditChapterSummaryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    story = await _get_owned_story(story_id, user, db)
    chapter = next((c for c in story.chapters if c.index == chapter_index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Bölüm bulunamadı.")

    chapter.summary = request.new_summary.strip() or None
    # Ozet ark ozetinin GIRDISI: elle degistirilince o ark da bayat olur
    await invalidate_for_chapter(db, story.id, chapter_index)
    await db.commit()
    story = await db.get(Story, story_id, populate_existing=True)
    return story_detail(story)


SEARCH_EXCERPT_CHARS = 1200  # geri dusus yollarinda gosterilen alinti uzunlugu


def _excerpt_around(text: str, pos: int, span: int = SEARCH_EXCERPT_CHARS) -> str:
    """Eslesmenin ETRAFINDAN alinti (bolum BASINDAN degil): sahne bolumun sonundaysa bas
    alintida hic gorunmuyordu. Kirpilan taraflar '...' ile isaretlenir."""
    start = max(0, pos - span // 2)
    end = min(len(text), start + span)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return prefix + text[start:end].strip() + suffix


def _keyword_search(story: Story, query: str) -> list[SearchHit]:
    """Ne chunk ne olay embed'i varsa (cok eski hikaye / backfill oncesi) vektorsuz fallback:
    sorgu kelimelerini iceren bolumleri dondurur. Vektor uzayi karismaz; hicbir esdeger yoksa
    gercekten bos doner. distance=-1.0 = 'anahtar-kelime fallback, vektor mesafesi yok' isareti.
    Alinti ILK eslesmenin etrafindan alinir."""
    terms = [t for t in query.lower().split() if len(t) >= 3]
    if not terms:
        return []
    scored: list[tuple[int, int, int]] = []  # (skor, bolum indeksi, ilk eslesme konumu)
    for chapter in story.chapters:
        text = chapter.content.lower()
        score = sum(text.count(t) for t in terms)
        if score > 0:
            positions = [p for p in (text.find(t) for t in terms) if p >= 0]
            scored.append((score, chapter.index, min(positions) if positions else 0))
    scored.sort(key=lambda x: (-x[0], x[1]))
    chapter_map = {c.index: c for c in story.chapters}
    return [
        SearchHit(
            chapter_index=index,
            distance=-1.0,
            window=[
                SearchWindowChapter(index=index, excerpt=_excerpt_around(chapter_map[index].content, pos))
            ],
        )
        for _, index, pos in scored[:3]
    ]


@router.get("/{story_id}/search", response_model=list[SearchHit])
@limiter.limit(SEARCH_LIMIT)
async def search_story(
    request: Request,
    story_id: int,
    query: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = query.strip()[:500]
    if not query:
        raise HTTPException(status_code=400, detail="Arama sorgusu boş olamaz.")

    story = await _get_owned_story(story_id, user, db)
    if not story.chapters:
        return []

    id_to_index = {c.id: c.index for c in story.chapters}

    # Yol sirasi: chunk (birincil, en iyi kapsama) -> olay -> anahtar-kelime. Chunk'i olmayan
    # hikaye (C4.4 backfill oncesi) olay yoluna, ikisi de yoksa vektorsuz fallback'e duser.
    has_chunks = await story_has_embedded_chunks(db, story.id)
    has_events = await story_has_embedded_events(db, story.id)
    if not has_chunks and not has_events:
        return _keyword_search(story, query)

    try:
        query_vec = await embed_query(db, story, query)
    except embeddings.EmbedQuotaExceeded:
        raise HTTPException(
            status_code=429, detail="Günlük arama/embed kotan doldu, yarın tekrar dene."
        )

    if has_chunks:
        # Aramada son N bolum HARIC TUTULMAZ: kullanici tum hikayede ariyor (uretimdeki
        # disleme, o bolumlerin prompta zaten tam metin girmesinden kaynaklaniyordu).
        hits = await find_relevant_chunks(db, story, query_vec)
        blocks = await expand_and_merge_chunks(db, story, hits)
        by_chapter: dict[int, list[dict]] = {}
        for block in blocks:
            by_chapter.setdefault(block["chapter_index"], []).append(block)
        results = [
            SearchHit(
                chapter_index=index,
                distance=min(b["score"] for b in chapter_blocks),
                # Pencere artik bolum basindan degil, eslesen chunk'larin ETRAFINDAN
                window=[
                    SearchWindowChapter(index=index, excerpt=block_text(b))
                    for b in sorted(chapter_blocks, key=lambda b: b["start"])
                ],
            )
            for index, chapter_blocks in by_chapter.items()
        ]
        results.sort(key=lambda h: h.distance)
        return results

    # Chunk yok, olay var: pencere olarak olayin KENDI metni (kendi basina anlasilir yazilir)
    event_hits = await find_relevant_events(db, story, query_vec, bump=False)
    by_index: dict[int, list[tuple[float, str]]] = {}
    for event, distance in event_hits:
        index = id_to_index.get(event.chapter_id)
        if index is not None:
            by_index.setdefault(index, []).append((distance, event.text))
    results = [
        SearchHit(
            chapter_index=index,
            distance=min(d for d, _ in entries),
            window=[SearchWindowChapter(index=index, excerpt=text) for _, text in entries],
        )
        for index, entries in by_index.items()
    ]
    results.sort(key=lambda h: h.distance)
    return results


@router.get("/{story_id}/stream")
async def stream_story(
    story_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    await _get_owned_story(story_id, user, db)
    queue = broker.subscribe(story_id)

    async def event_generator():
        try:
            yield ": connected\n\n"
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=SSE_KEEPALIVE_SECONDS)
                    payload = json.dumps(data, ensure_ascii=False)
                    yield f"event: STORY_UPDATE\ndata: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broker.unsubscribe(story_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
