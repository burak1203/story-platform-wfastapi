import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import client as ai
from ..ai.prompts import SINGLE_CHAPTER_SUMMARY_PROMPT, build_chapter_system_prompt
from ..config import settings
from ..database import SessionLocal
from ..models import Chapter, Character, Item, Location, Story
from ..schemas import story_detail
from .sse import broker

logger = logging.getLogger(__name__)

# Ayni hikaye icin ayni anda iki uretim calismasin diye hikaye bazli kilit.
# API katmanindaki atomik status guncellemesi ikinci savunma hattidir.
_story_locks: dict[int, asyncio.Lock] = {}
_background_tasks: set[asyncio.Task] = set()

RETRIEVAL_MIN_CHAPTERS = 3  # bu kadar bolum birikmeden gecmis aramasi yapmaya gerek yok
EXCERPT_CHARS = 1200


def schedule_generation(story_id: int, user_action: str | None) -> None:
    """Bolum uretimini arka plana atar; endpoint aninda doner, sonuc SSE ile iletilir."""
    task = asyncio.create_task(_run_generation(story_id, user_action))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _run_generation(story_id: int, user_action: str | None) -> None:
    lock = _story_locks.setdefault(story_id, asyncio.Lock())
    async with lock:
        try:
            async with SessionLocal() as db:
                await _generate_chapter(db, story_id, user_action)
        except Exception as exc:
            logger.exception("Hikaye %s icin bolum uretimi basarisiz oldu", story_id)
            await _recover_status(story_id)
            broker.publish(
                story_id,
                {"type": "AI_ERROR", "message": f"Yapay zeka bölümü üretemedi: {str(exc)[:200]}"},
            )


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


async def _generate_chapter(db: AsyncSession, story_id: int, user_action: str | None) -> None:
    story = await db.get(Story, story_id)
    if story is None:  # uretim beklerken hikaye silinmis
        return

    is_first = len(story.chapters) == 0

    retrieved_block = None
    if not is_first and user_action and len(story.chapters) >= RETRIEVAL_MIN_CHAPTERS:
        try:
            retrieved_block = await _retrieve_relevant_block(db, story, user_action)
        except Exception:
            logger.warning("Gecmis bolum aramasi atlandi", exc_info=True)

    system_prompt = build_chapter_system_prompt(story, retrieved_block)
    user_message = (
        f"Hikaye Konusu: {story.initial_prompt}" if is_first else f"Hamlem: {user_action}"
    )

    parsed = await ai.chat_json(settings.llm_story_model, system_prompt, user_message, temperature=0.8)
    content = str(parsed.get("content") or "").strip()
    if not content:
        raise ValueError("Model boş bölüm içeriği döndürdü.")

    # Bolum ozeti ayni cevaptan gelir; modelin yeni yazdigini en iyi yine kendisi ozetler
    summary = str(parsed.get("chapter_summary") or "").strip()[:2000] or None

    embedding = None
    try:
        embedding = await ai.embed(content)
    except Exception:
        logger.warning("Bolum embeddingi hesaplanamadi, vektorsuz kaydediliyor", exc_info=True)

    next_index = (story.chapters[-1].index + 1) if story.chapters else 1
    chapter = Chapter(
        story_id=story.id, index=next_index, content=content, summary=summary, embedding=embedding
    )
    db.add(chapter)
    _apply_entities(db, story, parsed)
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
            fallback = await summarize_chapter(content)
            if fallback:
                for c in story.chapters:
                    if c.index == next_index:
                        c.summary = fallback
                await db.commit()
                broker.publish(story.id, story_detail(story).model_dump(by_alias=True, mode="json"))
        except Exception:
            logger.warning("Bolum ozeti telafi edilemedi (bolum kaydedildi)", exc_info=True)


async def summarize_chapter(content: str) -> str | None:
    """Tek bolumun 2-3 cumlelik ozeti (uretim disi yollarda da kullanilir: bolum duzenleme)."""
    text = await ai.chat_text(
        settings.llm_util_model,
        SINGLE_CHAPTER_SUMMARY_PROMPT,
        f"Şu bölümü özetle:\n\n{content[:15000]}",
        temperature=0.3,
        max_tokens=512,
    )
    return text.strip() or None


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


def _apply_entities(db: AsyncSession, story: Story, parsed: dict) -> None:
    """Cikarilan varliklari isimle upsert eder; ayni isim ikinci kez kaydedilmez."""
    chars = {c.name.casefold(): c for c in story.characters}
    locs = {l.name.casefold(): l for l in story.locations}
    items = {i.name.casefold(): i for i in story.items}

    for entry in _clean_entries(parsed.get("new_characters"), "description"):
        key = entry["name"].casefold()
        if key in chars:
            if entry["description"] and not chars[key].description:
                chars[key].description = entry["description"]
            continue
        obj = Character(story_id=story.id, name=entry["name"], description=entry["description"])
        db.add(obj)
        chars[key] = obj

    for entry in _clean_entries(parsed.get("updated_characters"), "status_change"):
        key = entry["name"].casefold()
        obj = chars.get(key)
        if obj is None:
            # Model "bilinen" sanip yeni bir isim de verebilir; kaybetmek yerine olustur
            obj = Character(story_id=story.id, name=entry["name"], description="")
            db.add(obj)
            chars[key] = obj
        if entry["status_change"]:
            obj.status = entry["status_change"]

    for entry in _clean_entries(parsed.get("new_locations"), "description"):
        key = entry["name"].casefold()
        if key not in locs:
            obj = Location(story_id=story.id, name=entry["name"], description=entry["description"])
            db.add(obj)
            locs[key] = obj

    for entry in _clean_entries(parsed.get("new_items"), "description"):
        key = entry["name"].casefold()
        if key not in items:
            obj = Item(story_id=story.id, name=entry["name"], description=entry["description"])
            db.add(obj)
            items[key] = obj


def _excerpt(text: str) -> str:
    return text[:EXCERPT_CHARS] + ("..." if len(text) > EXCERPT_CHARS else "")


async def find_similar_chapters(
    db: AsyncSession, story: Story, query: str, limit: int = 2, exclude_from_index: int | None = None
) -> list[tuple[int, float]]:
    """Sorguya anlamca en yakin bolumleri (index, distance) olarak dondurur.
    exclude_from_index verilirse o indeks ve sonrasi aramaya girmez."""
    query_vec = await ai.embed(query)
    stmt = (
        select(Chapter.index, Chapter.embedding.cosine_distance(query_vec).label("dist"))
        .where(Chapter.story_id == story.id, Chapter.embedding.isnot(None))
        .order_by("dist")
        .limit(limit)
    )
    if exclude_from_index is not None:
        stmt = stmt.where(Chapter.index < exclude_from_index)
    rows = (await db.execute(stmt)).all()
    return [(row.index, float(row.dist)) for row in rows]


async def _retrieve_relevant_block(db: AsyncSession, story: Story, query: str) -> str | None:
    """n-1/n/n+1 penceresi: eslesen bolumlerin komsulariyla birlikte alintisini kurar."""
    # Son iki bolum zaten prompta tam metin olarak giriyor; aramaya dahil etme
    cutoff = story.chapters[-1].index - 1 if len(story.chapters) >= 2 else story.chapters[-1].index
    hits = await find_similar_chapters(db, story, query, limit=2, exclude_from_index=cutoff)
    if not hits:
        return None

    wanted: set[int] = set()
    for index, _ in hits:
        wanted.update({index - 1, index, index + 1})
    wanted = {i for i in wanted if 1 <= i < cutoff}

    chapter_map = {c.index: c for c in story.chapters}
    blocks = [
        f"--- Bölüm {i} ---\n{_excerpt(chapter_map[i].content)}"
        for i in sorted(wanted)
        if i in chapter_map
    ]
    return "\n\n".join(blocks) if blocks else None
