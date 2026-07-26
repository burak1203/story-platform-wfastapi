"""D2 rollup — ozet katmanlarinin URETIMI ve GECERSIZ KILINMASI.

Plan ve prompta yazim tarafi ai/prompts.py'de (saf, DB'siz): plan_rollup + _summaries_block.
Burasi DB + LLM tarafi. Boylece prompts.py'nin bu modulu import etmesi gerekmez (dairesel
import olmaz), rollup tek yonlu olarak prompts'tan okur.

Kurallar:
- Ark ozeti KULLANICININ anahtariyla, UTIL modelle, reasoning KAPALI uretilir.
- URETIMI BLOKLAMAZ: bolum kullaniciya SSE ile gonderildikten sonra calisir, patlarsa
  prompt ham bolum ozetleriyle devam eder (kayip yok, blok gecici olarak buyur).
- Ozetler DB'de saklanir, her uretimde YENIDEN URETILMEZ.
- Gecersiz kilma = SILME: bir bolum duzenlenince o bolumu iceren ark + onu kapsayan arka plan
  silinir; bir sonraki kosuda yeniden uretilir.
"""

import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ai import client as ai
from ..ai.client import LlmCtx
from ..ai.prompts import (
    ARC_SUMMARY_PROMPT,
    BACKGROUND_SUMMARY_PROMPT,
    ROLLUP_ARC_SIZE,
    plan_rollup,
)
from ..models import Arc, Chapter, Story

logger = logging.getLogger(__name__)

# Her uretimde EN FAZLA bu kadar ark ozeti uretilir. Her biri bir LLM cagrisi: bolum SSE ile
# gonderildikten sonra calissa da hikaye kilidi hala tutuldugu icin kullanici bir sonraki
# uretimi baslatana kadar beklemek zorunda kalabilir — bu yuzden bounded.
ROLLUP_PER_RUN = 2
ARC_INPUT_CHAR_CAP = 12000  # ark girdisinin (bolum ozetleri) kaba tavani

LEVEL_ARC = 0
LEVEL_BACKGROUND = 1


async def invalidate_for_chapter(db: AsyncSession, story_id: int, chapter_index: int) -> None:
    """Bir bolum DUZENLENDIGINDE cagrilir: o bolumu iceren ARK ve onu kapsayan ARKA PLAN
    silinir (silme = gecersiz kilma). Bir sonraki rollup kosusunda yeniden uretilirler; o ana
    kadar prompt o aralik icin ham bolum ozetlerine duser, yani bilgi kaybolmaz.
    Yalnizca ILGILI ark yenilenir — digerlerine dokunulmaz."""
    arc_start = ((chapter_index - 1) // ROLLUP_ARC_SIZE) * ROLLUP_ARC_SIZE + 1
    await db.execute(
        delete(Arc).where(
            Arc.story_id == story_id, Arc.level == LEVEL_ARC, Arc.start_index == arc_start
        )
    )
    # Arka plan bu bolumu kapsiyorsa o da bayat: kapsami degisen tek satir
    await db.execute(
        delete(Arc).where(
            Arc.story_id == story_id,
            Arc.level == LEVEL_BACKGROUND,
            Arc.end_index >= chapter_index,
        )
    )


async def _summaries_for_range(db: AsyncSession, story_id: int, start: int, end: int) -> str:
    rows = (
        await db.execute(
            select(Chapter.index, Chapter.summary)
            .where(
                Chapter.story_id == story_id,
                Chapter.index >= start,
                Chapter.index <= end,
                Chapter.summary.isnot(None),
            )
            .order_by(Chapter.index)
        )
    ).all()
    return "\n".join(f"Chapter {i}: {s.strip()}" for i, s in rows)[:ARC_INPUT_CHAR_CAP]


async def _compress(ctx: LlmCtx, system_prompt: str, payload: str) -> str | None:
    text = await ai.chat_text(
        ctx,
        ctx.util_model,
        system_prompt,
        payload,
        temperature=0.3,
        max_tokens=700,
        reasoning=False,  # util isi: reasoning gereksiz + output olarak faturalanir
    )
    return text.strip() or None


async def ensure_rollup(db: AsyncSession, story: Story, ctx: LlmCtx) -> int:
    """Eksik ark/arka plan ozetlerini uretir (lazy, bounded, idempotent). Uretilen ozet sayisini
    dondurur. Cagiran bunu try/except icinde cagirir: patlamasi uretimi ETKILEMEZ."""
    if not story.chapters:
        return 0
    plan = plan_rollup(story.chapters[-1].index)
    if not plan["all_arcs"]:
        return 0

    existing = {
        (a.level, a.start_index): a
        for a in (
            await db.execute(select(Arc).where(Arc.story_id == story.id))
        ).scalars().all()
    }
    made = 0

    # 1) Eksik ARK ozetleri (arka plan bunlara dayandigi icin once bunlar). En YENI eksikten
    #    geriye: prompta once onlar girer.
    for start, end in reversed(plan["all_arcs"]):
        if made >= ROLLUP_PER_RUN:
            return made
        if (LEVEL_ARC, start) in existing:
            continue
        payload = await _summaries_for_range(db, story.id, start, end)
        if not payload:
            continue  # bu aralikta hic ozet yok (ozet telafisi once tamamlansin)
        # LLM cagrisindan ONCE okuma islemini KAPAT. Aksi halde SQLAlchemy'nin acilan
        # transaction'i ag cagrisi boyunca (dakikalarca, retry'lerle) acik kalir ve tablo
        # kilitlerini tutar: bu, DDL'i (migration) ve baska istekleri bloke eder.
        await db.commit()
        summary = await _compress(ctx, ARC_SUMMARY_PROMPT, payload)
        if not summary:
            continue
        arc = Arc(
            story_id=story.id, level=LEVEL_ARC, start_index=start, end_index=end, summary=summary
        )
        db.add(arc)
        existing[(LEVEL_ARC, start)] = arc
        await db.commit()
        made += 1

    # 2) ARKA PLAN: yalnizca kapsadigi TUM arklar hazirsa uretilir (eksik ark varsa ertelenir —
    #    yarim bilgiyle sikistirma yapilmaz).
    background = plan["background"]
    if background and made < ROLLUP_PER_RUN:
        start, end = background
        current = existing.get((LEVEL_BACKGROUND, start))
        if current is None or current.end_index != end:
            parts = [
                existing.get((LEVEL_ARC, s)) for s, _ in plan["background_arcs"]
            ]
            if all(parts):
                payload = "\n\n".join(
                    f"Chapters {a.start_index}-{a.end_index}: {a.summary}" for a in parts
                )[:ARC_INPUT_CHAR_CAP]
                await db.commit()  # LLM cagrisi boyunca transaction acik kalmasin (yukariya bkz.)
                summary = await _compress(ctx, BACKGROUND_SUMMARY_PROMPT, payload)
                if summary:
                    # Kapsami degistiyse eskisini sil (unique: story_id+level+start_index)
                    if current is not None:
                        await db.execute(delete(Arc).where(Arc.id == current.id))
                    db.add(
                        Arc(
                            story_id=story.id,
                            level=LEVEL_BACKGROUND,
                            start_index=start,
                            end_index=end,
                            summary=summary,
                        )
                    )
                    await db.commit()
                    made += 1

    return made
