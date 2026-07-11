import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import client as ai
from ..database import get_db
from ..models import Story, User
from ..schemas import (
    ContinueStoryRequest,
    CreateStoryRequest,
    EditChapterRequest,
    SearchHit,
    SearchWindowChapter,
    StoryDetailResponse,
    story_detail,
)
from ..security import get_current_user
from ..services.generation import find_similar_chapters, schedule_generation
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


@router.get("/my-stories", response_model=list[StoryDetailResponse])
async def my_stories(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stories = (
        (await db.execute(select(Story).where(Story.user_id == user.id).order_by(Story.id.desc())))
        .scalars()
        .all()
    )
    return [story_detail(s) for s in stories]


@router.post("", response_model=StoryDetailResponse)
async def create_story(
    request: CreateStoryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    title = request.title.strip()
    prompt = request.starting_prompt.strip()
    if not title or not prompt:
        raise HTTPException(status_code=400, detail="Başlık ve başlangıç konusu boş olamaz.")

    story = Story(user_id=user.id, title=title, status="PENDING", initial_prompt=prompt)
    db.add(story)
    await db.commit()
    # Yeni eklenen nesnenin iliskileri yuklu degil; async'te lazy-load patladigi icin tazele
    story = await db.get(Story, story.id, populate_existing=True)

    schedule_generation(story.id, None)
    return story_detail(story)


@router.get("/{story_id}", response_model=StoryDetailResponse)
async def get_story(
    story_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    story = await _get_owned_story(story_id, user, db)
    return story_detail(story)


@router.post("/{story_id}/continue")
async def continue_story(
    story_id: int,
    request: ContinueStoryRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    action = request.user_action.strip()
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

    schedule_generation(story_id, action)
    return {"status": new_status}


@router.delete("/{story_id}")
async def delete_story(
    story_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    story = await _get_owned_story(story_id, user, db)
    await db.delete(story)
    await db.commit()
    return {"deleted": story_id}


@router.put("/{story_id}/chapters/{chapter_index}", response_model=StoryDetailResponse)
async def edit_chapter(
    story_id: int,
    chapter_index: int,
    request: EditChapterRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    new_content = request.new_content.strip()
    if not new_content:
        raise HTTPException(status_code=400, detail="Bölüm içeriği boş olamaz.")

    story = await _get_owned_story(story_id, user, db)
    if story.status in BUSY_STATUSES:
        raise HTTPException(status_code=409, detail="Üretim sürerken bölüm düzenlenemez.")

    chapter = next((c for c in story.chapters if c.index == chapter_index), None)
    if chapter is None:
        raise HTTPException(status_code=404, detail="Bölüm bulunamadı.")

    chapter.content = new_content
    # Icerik degisti; vektor hafizayi da guncelle (basarisizsa eski vektorle devam etmek
    # yerine None birakiyoruz ki arama yanlis sonuc dondurmesin)
    try:
        chapter.embedding = await ai.embed(new_content)
    except Exception:
        logger.warning("Duzenlenen bolumun embeddingi guncellenemedi", exc_info=True)
        chapter.embedding = None

    await db.commit()
    story = await db.get(Story, story_id, populate_existing=True)
    return story_detail(story)


@router.get("/{story_id}/search", response_model=list[SearchHit])
async def search_story(
    story_id: int,
    query: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Arama sorgusu boş olamaz.")

    story = await _get_owned_story(story_id, user, db)
    if not story.chapters:
        return []

    hits = await find_similar_chapters(db, story, query, limit=3, exclude_last=False)
    chapter_map = {c.index: c for c in story.chapters}

    results: list[SearchHit] = []
    for index, distance in hits:
        window = [
            SearchWindowChapter(index=i, excerpt=chapter_map[i].content[:1200])
            for i in (index - 1, index, index + 1)
            if i in chapter_map
        ]
        results.append(SearchHit(chapter_index=index, distance=distance, window=window))
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
