"""Okuyucu (public) uclari — GIRIS GEREKTIRMEZ.

GUVENLIK SOZLESMESI (bu dosyada calisirken bunlari BOZMA):
 1. private hikaye HICBIR uctan gorunmez. Gorunurluk filtresi SORGUNUN ICINDEDIR — once
    cek sonra kontrol et YAPILMAZ; boylece "bulundu ama yetkin yok" gibi bir ara durum
    hic olusmaz.
 2. Erisilemeyen her sey 404 doner, 403 DEGIL: 403 "bu id'de bir hikaye var" bilgisini
    sizdirir. Sahibi bile kendi private hikayesini buradan degil, yazar uclarindan okur.
 3. Yanitlar app.schemas'taki Public* DTO'lari ile kurulur; story_detail YENIDEN KULLANILMAZ.
    Yazar verisi (talimatlar, entity/olay/chunk, token muhasebesi, bolum ozetleri,
    initial_prompt) buraya asla girmez.
 4. Auth'suz erisildikleri icin hepsi rate-limitlidir.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import (
    READABLE_WITHOUT_OWNER,
    SEARCH_VECTOR_SQL,
    VISIBILITY_PUBLIC,
    Chapter,
    ChapterVote,
    Comment,
    Story,
    User,
)
from ..ratelimit import PUBLIC_READ_LIMIT, PUBLIC_SEARCH_LIMIT, limiter
from ..schemas import (
    PublicAuthorProfile,
    PublicChapterRef,
    PublicChapterView,
    PublicStoryCard,
    PublicStoryDetail,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/public", tags=["public"])

PAGE_SIZE_MAX = 50
MAX_QUERY_LEN = 200

# Arama sorgusu, indeksteki ifadenin BIREBIR AYNISI olmali (ifade indeksleri birebir
# eslesme ister); farkli yazilirsa Postgres ix_stories_search_gin'i kullanamaz.
_SEARCH_MATCH_SQL = f"{SEARCH_VECTOR_SQL} @@ plainto_tsquery('simple', :q)"


def _chapter_count_subq():
    return (
        select(func.count(Chapter.id))
        .where(Chapter.story_id == Story.id)
        .correlate(Story)
        .scalar_subquery()
    )


def _story_like_count_subq():
    return (
        select(func.count(ChapterVote.id))
        .select_from(ChapterVote)
        .join(Chapter, Chapter.id == ChapterVote.chapter_id)
        .where(Chapter.story_id == Story.id)
        .correlate(Story)
        .scalar_subquery()
    )


def _card_columns():
    """Liste ogesi icin secilen kolonlar — ALAN ALAN. `Story` nesnesini butun olarak
    dondurmek yazar alanlarini (initial_prompt vb.) yanlislikla sizdirmeye acik kapi birakir."""
    return (
        Story.id,
        Story.title,
        Story.description,
        Story.tags,
        User.username,
        Story.published_at,
        _chapter_count_subq().label("chapter_count"),
        _story_like_count_subq().label("like_count"),
    )


def _to_card(row) -> PublicStoryCard:
    return PublicStoryCard(
        id=row.id,
        title=row.title,
        description=row.description,
        tags=list(row.tags or []),
        author=row.username,
        chapter_count=row.chapter_count or 0,
        like_count=row.like_count or 0,
        published_at=row.published_at,
    )


@router.get("/stories", response_model=list[PublicStoryCard])
@limiter.limit(PUBLIC_SEARCH_LIMIT)
async def list_public_stories(
    request: Request,
    q: str | None = Query(default=None, max_length=MAX_QUERY_LEN),
    tag: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=20, ge=1, le=PAGE_SIZE_MAX),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Son yayimlananlar + arama. YALNIZCA visibility=public: unlisted hikayeler burada
    CIKMAZ (linki bilen okur), private zaten hic ulasamaz."""
    stmt = (
        select(*_card_columns())
        .join(User, User.id == Story.user_id)
        .where(Story.visibility == VISIBILITY_PUBLIC)
    )

    query = (q or "").strip()
    if query:
        # Indeksteki ifadenin AYNISI (bkz. _SEARCH_MATCH_SQL)
        stmt = stmt.where(text(_SEARCH_MATCH_SQL)).params(q=query)
    if tag:
        normalized = " ".join(tag.split()).lower()
        if normalized:
            stmt = stmt.where(Story.tags.contains([normalized]))

    # En yeni yayimlanan once; published_at esitse id ile deterministik sirala
    stmt = stmt.order_by(Story.published_at.desc().nullslast(), Story.id.desc())
    rows = (await db.execute(stmt.limit(limit).offset(offset))).all()
    return [_to_card(r) for r in rows]


async def _readable_story(story_id: int, db: AsyncSession):
    """Okunabilir hikayeyi getirir: public VEYA unlisted. Gorunurluk filtresi SORGUDA —
    private hicbir zaman eslesmez, dolayisiyla varligi bile ele verilmez (404)."""
    row = (
        await db.execute(
            select(
                Story.id,
                Story.title,
                Story.description,
                Story.tags,
                Story.visibility,
                Story.is_showcase,
                Story.published_at,
                User.username,
            )
            .join(User, User.id == Story.user_id)
            .where(Story.id == story_id, Story.visibility.in_(READABLE_WITHOUT_OWNER))
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Hikaye bulunamadı.")
    return row


@router.get("/stories/{story_id}", response_model=PublicStoryDetail)
@limiter.limit(PUBLIC_READ_LIMIT)
async def get_public_story(
    request: Request, story_id: int, db: AsyncSession = Depends(get_db)
):
    """Hikaye sayfasi: bolum listesi (METIN YOK) + sayaclar. unlisted id ile okunur."""
    story = await _readable_story(story_id, db)

    like_counts = dict(
        (
            await db.execute(
                select(ChapterVote.chapter_id, func.count(ChapterVote.id))
                .join(Chapter, Chapter.id == ChapterVote.chapter_id)
                .where(Chapter.story_id == story_id)
                .group_by(ChapterVote.chapter_id)
            )
        ).all()
    )
    comment_counts = dict(
        (
            await db.execute(
                select(Comment.chapter_id, func.count(Comment.id))
                .join(Chapter, Chapter.id == Comment.chapter_id)
                .where(Chapter.story_id == story_id)
                .group_by(Comment.chapter_id)
            )
        ).all()
    )
    chapters = (
        await db.execute(
            select(Chapter.id, Chapter.index)
            .where(Chapter.story_id == story_id)
            .order_by(Chapter.index)
        )
    ).all()

    return PublicStoryDetail(
        id=story.id,
        title=story.title,
        description=story.description,
        tags=list(story.tags or []),
        author=story.username,
        visibility=story.visibility,
        is_showcase=story.is_showcase,
        published_at=story.published_at,
        chapter_count=len(chapters),
        like_count=sum(like_counts.values()),
        chapters=[
            PublicChapterRef(
                index=c.index,
                like_count=like_counts.get(c.id, 0),
                comment_count=comment_counts.get(c.id, 0),
            )
            for c in chapters
        ],
    )


@router.get("/stories/{story_id}/chapters/{index}", response_model=PublicChapterView)
@limiter.limit(PUBLIC_READ_LIMIT)
async def get_public_chapter(
    request: Request, story_id: int, index: int, db: AsyncSession = Depends(get_db)
):
    """Okuma ucu: YALNIZCA bolum metni + gezinme. Bolum OZETI bilincli olarak DONMEZ —
    ozet hem spoiler hem yazar tarafi bir uretim artifakti."""
    story = await _readable_story(story_id, db)

    chapter = (
        await db.execute(
            select(Chapter.id, Chapter.index, Chapter.content).where(
                Chapter.story_id == story_id, Chapter.index == index
            )
        )
    ).first()
    if chapter is None:
        raise HTTPException(status_code=404, detail="Bölüm bulunamadı.")

    like_count = (
        await db.execute(
            select(func.count(ChapterVote.id)).where(ChapterVote.chapter_id == chapter.id)
        )
    ).scalar_one()
    neighbours = (
        await db.execute(
            select(Chapter.index).where(Chapter.story_id == story_id).order_by(Chapter.index)
        )
    ).scalars().all()
    position = neighbours.index(chapter.index)

    return PublicChapterView(
        story_id=story.id,
        story_title=story.title,
        author=story.username,
        index=chapter.index,
        content=chapter.content,
        like_count=like_count,
        previous_index=neighbours[position - 1] if position > 0 else None,
        next_index=neighbours[position + 1] if position + 1 < len(neighbours) else None,
    )


@router.get("/users/{username}", response_model=PublicAuthorProfile)
@limiter.limit(PUBLIC_READ_LIMIT)
async def get_author_profile(
    request: Request, username: str, db: AsyncSession = Depends(get_db)
):
    """Yazar profili: YALNIZCA public hikayeleri ve o hikayelerden toplanan begeniler.
    unlisted/private hikayeler burada ne listelenir ne de begeni sayisina katilir."""
    user = (
        await db.execute(
            select(User.id, User.username, User.created_at).where(User.username == username)
        )
    ).first()
    if user is None:
        raise HTTPException(status_code=404, detail="Kullanıcı bulunamadı.")

    rows = (
        await db.execute(
            select(*_card_columns())
            .join(User, User.id == Story.user_id)
            .where(Story.user_id == user.id, Story.visibility == VISIBILITY_PUBLIC)
            .order_by(Story.published_at.desc().nullslast(), Story.id.desc())
        )
    ).all()
    cards = [_to_card(r) for r in rows]

    return PublicAuthorProfile(
        username=user.username,
        joined_at=user.created_at,
        total_likes=sum(card.like_count for card in cards),
        stories=cards,
    )
