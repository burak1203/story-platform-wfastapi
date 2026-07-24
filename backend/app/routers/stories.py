import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import embeddings
from ..ai.client import LlmCtx
from ..database import get_db
from ..models import Story, User
from ..ai.prompts import parse_edit_notes
from ..schemas import (
    ContinueStoryRequest,
    CreateStoryRequest,
    EditChapterRequest,
    EditChapterSummaryRequest,
    SearchHit,
    SearchWindowChapter,
    StoryDetailResponse,
    StorySummaryResponse,
    UpdateStorySettingsRequest,
    story_detail,
    story_summary,
)
from ..ratelimit import GENERATION_LIMIT, SEARCH_LIMIT, limiter
from ..security import get_current_user, get_llm_ctx
from ..services.generation import (
    apply_new_entities_from_edit,
    find_relevant_events,
    rebuild_chapter_chunks,
    schedule_generation,
    story_has_embedded_events,
    summarize_chapter,
)
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

    story = Story(
        user_id=user.id,
        title=title,
        status="PENDING",
        initial_prompt=prompt,
        style_prompt=(payload.style_prompt or "").strip() or None,
        negative_prompt=(payload.negative_prompt or "").strip() or None,
    )
    db.add(story)
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
    story = await _get_owned_story(story_id, user, db)
    story.style_prompt = (request.style_prompt or "").strip() or None
    story.negative_prompt = (request.negative_prompt or "").strip() or None
    await db.commit()
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
    await db.commit()
    story = await db.get(Story, story_id, populate_existing=True)
    return story_detail(story)


def _chapter_window(chapter_map: dict[int, object], index: int) -> list[SearchWindowChapter]:
    """Bir bolumun n-1/n/n+1 penceresini (mevcut olanlarla) kurar."""
    return [
        SearchWindowChapter(index=i, excerpt=chapter_map[i].content[:1200])
        for i in (index - 1, index, index + 1)
        if i in chapter_map
    ]


def _keyword_search(story: Story, query: str, chapter_map: dict[int, object]) -> list[SearchHit]:
    """Olay-embed yoksa (eski hikaye / backfill oncesi) vektorsuz fallback: sorgu kelimelerini
    iceren bolumleri dondurur. Vektor uzayi karismaz; hicbir esdeger yoksa gercekten bos doner.
    distance=-1.0 = 'anahtar-kelime fallback, vektor mesafesi yok' isareti."""
    terms = [t for t in query.lower().split() if len(t) >= 3]
    if not terms:
        return []
    scored: list[tuple[int, int]] = []
    for chapter in story.chapters:
        text = chapter.content.lower()
        score = sum(text.count(t) for t in terms)
        if score > 0:
            scored.append((score, chapter.index))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [
        SearchHit(chapter_index=index, distance=-1.0, window=_chapter_window(chapter_map, index))
        for _, index in scored[:3]
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

    chapter_map = {c.index: c for c in story.chapters}
    id_to_index = {c.id: c.index for c in story.chapters}

    # Olay-embed varsa birincil yol: olay -> chapter_id -> distinct bolum (en iyi mesafe) -> pencere.
    # Olay yoksa vektor uzayi karistirmamak icin anahtar-kelime fallback'ine dus.
    if not await story_has_embedded_events(db, story.id):
        return _keyword_search(story, query, chapter_map)

    try:
        hits = await find_relevant_events(db, story, query, bump=False)
    except embeddings.EmbedQuotaExceeded:
        raise HTTPException(
            status_code=429, detail="Günlük arama/embed kotan doldu, yarın tekrar dene."
        )

    best: dict[int, float] = {}  # bolum indeksi -> en kucuk (en yakin) mesafe
    for event, distance in hits:
        index = id_to_index.get(event.chapter_id)
        if index is None:
            continue
        if index not in best or distance < best[index]:
            best[index] = distance

    return [
        SearchHit(chapter_index=index, distance=best[index], window=_chapter_window(chapter_map, index))
        for index in sorted(best, key=lambda i: best[i])
    ]


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
