"""Son bolumlerin token muhasebesini tek satirda gosterir (D3.1'de yakalanan veriler).

Kullanim (backend/ dizininden):
    PYTHONPATH=. ./venv/Scripts/python.exe scripts/show_tokens.py            # son 5 bolum
    PYTHONPATH=. ./venv/Scripts/python.exe scripts/show_tokens.py 10         # son 10 bolum
    PYTHONPATH=. ./venv/Scripts/python.exe scripts/show_tokens.py 10 <story_id>

Sutunlar:
  prompt/compl : SAGLAYICININ bildirdigi gercek token sayilari
  cached       : prefix cache ISABETI (DeepSeek prompt_cache_hit_tokens / OpenAI cached_tokens).
                 "-" ise saglayici bildirmiyor demektir, cache yok demek DEGIL.
  %hit         : cached / prompt -> prompt sirasi ve entity secimi calismalarinin gercek olcusu
  kirilim      : tiktoken ile bilesen bazli tahmin (fixed/rollup/entities/scene/pinned/rag/last/move)
"""

import asyncio
import json
import sys

from sqlalchemy import select, text

from app.database import SessionLocal, engine
from app.models import Chapter, Story

COMPONENT_ORDER = [
    "fixed", "rollup", "entities", "scene_entities", "pinned", "rag", "last_chapters",
    "edit_notes", "move",
]


async def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    story_id = int(sys.argv[2]) if len(sys.argv) > 2 else None

    async with SessionLocal() as db:
        if story_id is None:
            story_id = (await db.execute(select(Story.id).order_by(Story.id.desc()).limit(1))).scalar()
            if story_id is None:
                print("Hic hikaye yok.")
                return
        title = (await db.execute(select(Story.title).where(Story.id == story_id))).scalar()
        rows = (
            await db.execute(
                select(
                    Chapter.index, Chapter.prompt_tokens, Chapter.completion_tokens,
                    Chapter.cached_prompt_tokens, Chapter.token_breakdown,
                )
                .where(Chapter.story_id == story_id)
                .order_by(Chapter.index.desc())
                .limit(limit)
            )
        ).all()

        print(f"Hikaye {story_id}: {title!r} — son {len(rows)} bolum\n")
        print(f"{'bol':>4} | {'prompt':>7} | {'compl':>6} | {'cached':>7} | {'%hit':>5} | kirilim")
        print("-" * 110)
        for index, prompt, completion, cached, breakdown in rows:
            if prompt is None:
                print(f"{index:>4} |   (token verisi yok — bu bolum D3.1 oncesinde uretilmis)")
                continue
            pct = f"{cached * 100 // prompt}%" if cached and prompt else "-"
            parts = ""
            if breakdown:
                data = json.loads(breakdown)
                parts = " ".join(
                    f"{k}={data[k]}" for k in COMPONENT_ORDER if data.get(k)
                )
            print(
                f"{index:>4} | {prompt:>7} | {completion or 0:>6} | "
                f"{cached if cached is not None else '-':>7} | {pct:>5} | {parts}"
            )

        # Toplam maliyet hissi: kac token prompt'a, kac token uretime gitti
        totals = (
            await db.execute(
                text(
                    "select coalesce(sum(prompt_tokens),0), coalesce(sum(completion_tokens),0), "
                    "coalesce(sum(cached_prompt_tokens),0) from chapters where story_id=:s"
                ),
                {"s": story_id},
            )
        ).one()
        print("-" * 110)
        print(f"hikaye toplami: prompt={totals[0]} completion={totals[1]} cached={totals[2]}")
    await engine.dispose()


asyncio.run(main())
