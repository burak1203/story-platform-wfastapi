"""Okuyucu (public) uclari.

OKUMA giris gerektirmez; ETKILESIM (begeni, yorum) gerektirir. Ikisi bilincli olarak ayni
dosyada: "private hicbir yerden sizmaz" degismezini uygulayan gorunurluk kapisi TEK YERDE
kalsin — iki dosyaya bolunurse ikinci dosyada kapiyi atlamak kolaylasir ve denetlenmesi
gereken yuzey ikiye cikar.

GUVENLIK SOZLESMESI (bu dosyada calisirken bunlari BOZMA):
 1. private hikaye HICBIR uctan gorunmez ve HICBIR uc uzerinden etkilesime girilemez.
    Gorunurluk filtresi SORGUNUN ICINDEDIR — once cek sonra kontrol et YAPILMAZ; boylece
    "bulundu ama yetkin yok" gibi bir ara durum hic olusmaz. Her ucun giris kapisi
    _readable_story / _readable_chapter'dir; DOGRUDAN Chapter/Story sorgusu yazma.
 2. Erisilemeyen HIKAYE/BOLUM 404 doner, 403 DEGIL: 403 "bu id'de bir hikaye var" bilgisini
    sizdirir. Sahibi bile kendi private hikayesini buradan degil, yazar uclarindan okur.
    (Yorum silme/sabitleme bunun ISTISNASI ve 403 doner — bkz. _authorize_comment.)
 3. Yanitlar app.schemas'taki Public* DTO'lari ile kurulur; story_detail YENIDEN KULLANILMAZ.
    Yazar verisi (talimatlar, entity/olay/chunk, token muhasebesi, bolum ozetleri,
    initial_prompt) buraya asla girmez.
 4. Hepsi rate-limitlidir: okuma auth'suz erisildigi icin, yazma spam'e acik oldugu icin.
 5. XSS: yorum govdesi OLDUGU GIBI saklanir, HTML temizlenmez. Sunucuda "temizlemek" hem
    kayipli (yorumda `<` yazamamak) hem de yaniltici bir guven verir; gercek savunma
    frontend'in metni TEXT olarak render etmesidir (v-html YASAK, bkz. CLAUDE.md).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
from ..params import IdPath
from ..ratelimit import (
    COMMENT_WRITE_LIMIT,
    PUBLIC_READ_LIMIT,
    PUBLIC_SEARCH_LIMIT,
    VOTE_LIMIT,
    limiter,
)
from ..schemas import (
    ChapterLikeState,
    CreateCommentRequest,
    PinCommentRequest,
    PublicAuthorProfile,
    PublicChapterRef,
    PublicChapterView,
    PublicCommentDto,
    PublicCommentPage,
    PublicStoryCard,
    PublicStoryDetail,
)
from ..security import get_current_user, get_optional_user

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
    request: Request, story_id: IdPath, db: AsyncSession = Depends(get_db)
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
    request: Request,
    story_id: IdPath,
    index: IdPath,
    db: AsyncSession = Depends(get_db),
    viewer: User | None = Depends(get_optional_user),
):
    """Okuma ucu: YALNIZCA bolum metni + gezinme. Bolum OZETI bilincli olarak DONMEZ —
    ozet hem spoiler hem yazar tarafi bir uretim artifakti.

    Giris ZORUNLU DEGIL; token varsa yalnizca `liked` alanini doldurmak icin kullanilir."""
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
    liked = viewer is not None and await _has_voted(chapter.id, viewer.id, db)
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
        liked=liked,
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


# --- Etkilesim: begeni ve yorumlar (GIRIS ISTER) -------------------------------------------


async def _readable_chapter(story_id: int, index: int, db: AsyncSession):
    """Okunabilir bir hikayenin bolumunu getirir — TEK sorguda UC sey birden dogrulanir:
      1. hikaye okunabilir mi (private ise HIC eslesmez -> 404, varligi ele verilmez),
      2. bolum var mi,
      3. bolum GERCEKTEN bu hikayeye mi ait (IDOR: baskasinin bolum id'si kendi hikayesinin
         URL'ine takilamaz).
    Yazarin id'si (author_id) yalnizca DAHILI kullanim icindir: rozet ve sabitleme yetkisi.
    DTO'ya ASLA konmaz."""
    row = (
        await db.execute(
            select(
                Chapter.id,
                Chapter.index,
                Story.id.label("story_id"),
                Story.user_id.label("author_id"),
            )
            .join(Story, Story.id == Chapter.story_id)
            .where(
                Chapter.story_id == story_id,
                Chapter.index == index,
                Story.visibility.in_(READABLE_WITHOUT_OWNER),
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Bölüm bulunamadı.")
    return row


async def _has_voted(chapter_id: int, user_id: int, db: AsyncSession) -> bool:
    return (
        await db.execute(
            select(ChapterVote.id).where(
                ChapterVote.chapter_id == chapter_id, ChapterVote.user_id == user_id
            )
        )
    ).first() is not None


async def _like_state(chapter_id: int, user_id: int, db: AsyncSession) -> ChapterLikeState:
    count = (
        await db.execute(
            select(func.count(ChapterVote.id)).where(ChapterVote.chapter_id == chapter_id)
        )
    ).scalar_one()
    return ChapterLikeState(like_count=count, liked=await _has_voted(chapter_id, user_id, db))


@router.post("/stories/{story_id}/chapters/{index}/like", response_model=ChapterLikeState)
@limiter.limit(VOTE_LIMIT)
async def like_chapter(
    request: Request,
    story_id: IdPath,
    index: IdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tek tik begeni — IDEMPOTENT. Iki kez basmak (ya da iki istek yarissa) ikinci kayit
    olusturmaz ve HATA DA VERMEZ: ON CONFLICT DO NOTHING, UNIQUE(chapter_id,user_id)
    kisitini veritabani seviyesinde sessizce yutar. try/except IntegrityError tercih
    EDILMEDI cunku patlayan bir INSERT transaction'i zehirler; ON CONFLICT hic patlamaz."""
    chapter = await _readable_chapter(story_id, index, db)
    await db.execute(
        pg_insert(ChapterVote.__table__)
        .values(chapter_id=chapter.id, user_id=user.id)
        .on_conflict_do_nothing(index_elements=["chapter_id", "user_id"])
    )
    await db.commit()
    return await _like_state(chapter.id, user.id, db)


@router.delete("/stories/{story_id}/chapters/{index}/like", response_model=ChapterLikeState)
@limiter.limit(VOTE_LIMIT)
async def unlike_chapter(
    request: Request,
    story_id: IdPath,
    index: IdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Begeniyi geri alir. Bu da idempotent: begenmemis birinin geri almasi hata degil."""
    chapter = await _readable_chapter(story_id, index, db)
    await db.execute(
        delete(ChapterVote).where(
            ChapterVote.chapter_id == chapter.id, ChapterVote.user_id == user.id
        )
    )
    await db.commit()
    return await _like_state(chapter.id, user.id, db)


@router.get(
    "/stories/{story_id}/chapters/{index}/comments", response_model=PublicCommentPage
)
@limiter.limit(PUBLIC_READ_LIMIT)
async def list_comments(
    request: Request,
    story_id: IdPath,
    index: IdPath,
    limit: int = Query(default=20, ge=1, le=PAGE_SIZE_MAX),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Duz liste, THREAD YOK. Sabitlenenler ustte, sonra KRONOLOJIK (eskiden yeniye).
    Eskiden yeniye siralama sayfalamayi kararli kilar: yeni bir yorum gelince onceki
    sayfalar kaymaz. Okumak icin giris gerekmez."""
    chapter = await _readable_chapter(story_id, index, db)

    total = (
        await db.execute(
            select(func.count(Comment.id)).where(Comment.chapter_id == chapter.id)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(
                Comment.id,
                Comment.body,
                Comment.is_author_pinned,
                Comment.created_at,
                Comment.user_id,
                User.username,
            )
            .join(User, User.id == Comment.user_id)
            .where(Comment.chapter_id == chapter.id)
            .order_by(Comment.is_author_pinned.desc(), Comment.created_at, Comment.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return PublicCommentPage(
        total=total,
        comments=[_to_comment(r, chapter.author_id) for r in rows],
    )


def _to_comment(row, author_id: int) -> PublicCommentDto:
    """DTO'ya YALNIZCA kullanici adi gecer; row.user_id burada kalir (rozet hesabi icin)."""
    return PublicCommentDto(
        id=row.id,
        author=row.username,
        body=row.body,
        is_author=row.user_id == author_id,
        is_pinned=row.is_author_pinned,
        created_at=row.created_at,
    )


@router.post(
    "/stories/{story_id}/chapters/{index}/comments",
    response_model=PublicCommentDto,
    status_code=201,
)
@limiter.limit(COMMENT_WRITE_LIMIT)
async def create_comment(
    request: Request,
    story_id: IdPath,
    index: IdPath,
    payload: CreateCommentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Yorum ekler. Govde OLDUGU GIBI saklanir — HTML temizlenmez (bkz. modul basligi 5)."""
    chapter = await _readable_chapter(story_id, index, db)
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=400, detail="Yorum boş olamaz.")

    comment = Comment(chapter_id=chapter.id, user_id=user.id, body=body)
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return PublicCommentDto(
        id=comment.id,
        author=user.username,
        body=comment.body,
        is_author=user.id == chapter.author_id,
        is_pinned=comment.is_author_pinned,
        created_at=comment.created_at,
    )


async def _owned_comment(story_id: int, index: int, comment_id: int, db: AsyncSession):
    """Yorumu getirir ve ZINCIRI dogrular: yorum -> bolum -> hikaye. _readable_chapter zaten
    "bolum bu hikayeye ait mi" sorusunu kapatiyor; burada "yorum bu bolume ait mi" eklenir.
    Iki kontrol birlikte, baska bir hikayenin yorumunu bu URL uzerinden yonetmeyi imkansiz kilar."""
    chapter = await _readable_chapter(story_id, index, db)
    comment = await db.get(Comment, comment_id)
    if comment is None or comment.chapter_id != chapter.id:
        raise HTTPException(status_code=404, detail="Yorum bulunamadı.")
    return chapter, comment


@router.delete(
    "/stories/{story_id}/chapters/{index}/comments/{comment_id}", status_code=204
)
@limiter.limit(PUBLIC_READ_LIMIT)
async def delete_comment(
    request: Request,
    story_id: IdPath,
    index: IdPath,
    comment_id: IdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Silme yetkisi: yorumun SAHIBI veya hikayenin YAZARI (kendi bolumunun altini temizleyebilmeli).

    Burada 404 degil 403 doniyoruz — modul basligindaki kuralin bilincli istisnasi. Gerekce:
    yorum ZATEN herkese acik olarak listeleniyor, varligi sir degil; gizlenecek bir sey yokken
    404 donmek kullaniciyi "yorum silinmis" diye yaniltir."""
    chapter, comment = await _owned_comment(story_id, index, comment_id, db)
    if comment.user_id != user.id and chapter.author_id != user.id:
        raise HTTPException(status_code=403, detail="Bu yorumu silme yetkiniz yok.")
    await db.delete(comment)
    await db.commit()


@router.put(
    "/stories/{story_id}/chapters/{index}/comments/{comment_id}/pin",
    response_model=PublicCommentDto,
)
@limiter.limit(PUBLIC_READ_LIMIT)
async def pin_comment(
    request: Request,
    story_id: IdPath,
    index: IdPath,
    comment_id: IdPath,
    payload: PinCommentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sabitleme YALNIZCA hikayenin yazarina aittir — kendi yorumunu da, bir okurun iyi bir
    yorumunu da sabitleyebilir. Yorumcunun kendisi sabitleyemez (aksi halde herkes kendi
    yorumunu tepeye tasir)."""
    chapter, comment = await _owned_comment(story_id, index, comment_id, db)
    if chapter.author_id != user.id:
        raise HTTPException(status_code=403, detail="Yalnızca hikayenin yazarı sabitleyebilir.")

    comment.is_author_pinned = payload.pinned
    await db.commit()

    author_name = (
        await db.execute(select(User.username).where(User.id == comment.user_id))
    ).scalar_one()
    return PublicCommentDto(
        id=comment.id,
        author=author_name,
        body=comment.body,
        is_author=comment.user_id == chapter.author_id,
        is_pinned=comment.is_author_pinned,
        created_at=comment.created_at,
    )
