"""Prompt templates.

Component order is CACHE-FRIENDLY: slowest-changing first, so providers that cache the longest
matching prefix (DeepSeek: cached input ~47x cheaper) keep the cache across chapters. Putting a
cache-breaker (e.g. last-2 chapters, which change every turn) early would throw away the discount.

Order:
  1. FIXED (never changes across a story's chapters): base identity, genre modules, author
     style_prompt, negative prompt, task, output format.
  2. GROWING (append-only -> prefix stays cached): chapter summaries, chronological.
  3. SLOW variables: entity cards, pinned events.
  4. CACHE-BREAKERS (change every chapter -> last): last 2 chapters full text, RAG window,
     author's recent edits.
The reader's move goes in the USER message, not here.

Language-agnostic: scaffolding labels are English, but the model is told to WRITE IN THE STORY'S
OWN LANGUAGE. Embedded story content (summaries, chapter text, entity descriptions) stays in the
story's language.
"""

import json
from pathlib import Path

from ..models import Story

# Context budget constants
SUMMARY_CHAR_CAP = 300        # max length of a single chapter summary in the prompt
MAX_SUMMARIES_IN_PROMPT = 60  # older summaries beyond this are dropped
LAST_CHAPTER_CAP = 12000      # char cap for the last chapter's full text
PREV_CHAPTER_CAP = 6000       # char cap for the chapter before last
MAX_ENTITIES_PER_KIND = 60    # cap per character/location/item list; oldest dropped if exceeded
STATUS_CHAR_CAP = 200         # cap for a character's current-status text
MAX_EVENTS_PER_CHAPTER = 7    # per-chapter event cap (long chapters mustn't pile up dozens)
EVENT_TEXT_CAP = 600          # cap for a single event's text

# ---- Fixed identity / task (language-agnostic; part of the cacheable prefix) ----
BASE_IDENTITY = (
    "[IDENTITY]\n"
    "You are a versatile storyteller who can write in any genre and any style. You are writing an "
    "interactive story: the reader's moves drive it. You have no fixed style of your own — derive "
    "tone, pacing and voice from the story's genre, everything written so far, and the author's "
    "instructions. Do not impose a style; write what the story needs. The author's instructions "
    "always take priority.\n"
    "CRITICAL LANGUAGE RULE: Write in the SAME LANGUAGE as the story — its topic and the reader's "
    "moves. If they are in Turkish, write in Turkish; if in English, write in English. Never switch "
    "languages on your own."
)

TASK_CONTINUATION = (
    "[TASK]\n"
    "Based on the reader's move, write ONLY the NEXT chapter of the story. Do not repeat or "
    "summarize earlier text; continue from where it left off. Stay CONSISTENT with the summaries and "
    "the known universe, and move the story in the direction the move requires. Let the story's own "
    "flow decide the chapter's length, pace and tone; introduce new characters, locations, items or "
    "events as needed."
)

TASK_FIRST = (
    "[TASK]\n"
    "Based on the given topic, write the FIRST chapter of the story. Choose tone, style and pace to "
    "fit the topic and lay the groundwork for later chapters. You are free to introduce the "
    "characters, locations and items you see fit."
)

# Event extraction rules — language-agnostic. Shared by main generation JSON and the edit-path
# extraction (single source, no drift). Events are pulled out of context as standalone retrieval
# results, so each must be SELF-CONTAINED.
EVENTS_INSTRUCTION = (
    'An "events" array: 3 to 7 KEY events from this chapter, most important first. '
    'Each event is an object {"text": ..., "importance": ...}:\n'
    '- "text": a SELF-CONTAINED description understandable on its own, out of context. Use explicit '
    'names — NEVER pronouns or vague references. Write "Elian traveled to the North Tower to find his '
    'father\'s letter", NOT "he went there". Write it in the SAME LANGUAGE as the story.\n'
    '- "importance": a float from 0.0 to 1.0. Scale: 0.9+ = a turning point that changes the story\'s '
    'direction; ~0.5 = character or relationship development; ~0.2 = a small detail that adds color.\n'
    "- Output AT MOST 7 events; fewer is fine for a short chapter."
)

JSON_FORMAT_BLOCK = """[OUTPUT FORMAT - STRICT RULE]
Respond with ONLY the following JSON. Do not write a single word outside the JSON:
{
  "content": "The full chapter you wrote (only the new chapter; do not repeat earlier ones)...",
  "chapter_summary": "A 2-3 sentence summary of what happened this chapter (who did what, what changed), in the story's language",
  "new_characters": [{"name": "New character name", "description": "Who they are, physical traits and role"}],
  "updated_characters": [{"name": "Known character name", "status_change": "What they did / how their situation changed this chapter"}],
  "new_locations": [{"name": "New location name", "description": "Atmosphere and detail"}],
  "new_items": [{"name": "New item name", "description": "Its properties and importance"}],
  "events": [{"text": "Self-contained description of a key event, in the story's language", "importance": 0.7}]
}
Rules:
- Add characters/locations/items that appear for the FIRST TIME in this chapter to the "new_..." lists.
- If a known character experienced something important, add it to "updated_characters".
- Leave a list empty if nothing applies: []
""" + EVENTS_INSTRUCTION


# ---- Genre modules (data-driven: adding a genre = a line in genres.json, no code change) ----
_GENRES_PATH = Path(__file__).resolve().parent.parent / "prompts" / "genres.json"


def _load_genres() -> dict:
    try:
        return json.loads(_GENRES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


GENRE_MODULES: dict = _load_genres()


def _genre_block(genres, lang: str = "en") -> str | None:
    """Concatenate selected genre modules from genres.json. Genre selection isn't wired to the UI
    yet, so this is normally empty (default []); the infra is ready for when a genres field exists.
    Adding a genre is a line in genres.json — no code change."""
    if not genres:
        return None
    lines = []
    for key in genres:
        module = GENRE_MODULES.get(key)
        if module and module.get(lang):
            lines.append(module[lang])
    return "\n".join(lines) if lines else None


def _head(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _tail(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else "..." + text[-limit:]


def _entity_lines(entities, with_status: bool = False, desc_limit: int = 200) -> str:
    skipped = len(entities) - MAX_ENTITIES_PER_KIND
    shown = entities[skipped:] if skipped > 0 else entities
    lines = []
    if skipped > 0:
        lines.append(f"(oldest {skipped} entries omitted)")
    for e in shown:
        line = f"- {e.name}: {_head(e.description or '', desc_limit)}"
        if with_status and getattr(e, "status", None):
            line += f" (current status: {_head(e.status, STATUS_CHAR_CAP)})"
        lines.append(line)
    return "\n".join(lines) if lines else "(none yet)"


def _summaries_block(story: Story) -> str | None:
    summarized = [c for c in story.chapters if c.summary]
    if not summarized:
        return None
    skipped = len(summarized) - MAX_SUMMARIES_IN_PROMPT
    if skipped > 0:
        summarized = summarized[skipped:]
    lines = [f"Chapter {c.index}: {_head(c.summary, SUMMARY_CHAR_CAP)}" for c in summarized]
    header = ""
    if skipped > 0:
        header = f"(summaries of the oldest {skipped} chapters omitted; see 'relevant past scenes' if needed)\n"
    return header + "\n".join(lines)


def parse_edit_notes(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        notes = json.loads(raw)
        return [str(n) for n in notes if str(n).strip()]
    except (json.JSONDecodeError, TypeError):
        return []


def build_chapter_system_prompt(
    story: Story,
    retrieved_block: str | None,
    pinned_block: str | None = None,
    genres: list[str] | None = None,
) -> str:
    """Single template for both the first chapter and continuations. Components are ordered
    slowest-changing first for provider prefix caching (see module docstring)."""
    is_continuation = bool(story.chapters)

    # ===== 1. FIXED PREFIX (never changes across a story's chapters -> cache lands here) =====
    parts: list[str] = [BASE_IDENTITY, f"[STORY TITLE]\n{story.title}"]

    genre_block = _genre_block(genres or [])
    if genre_block:
        parts.append("[GENRE MODULES]\n" + genre_block)
    if story.style_prompt and story.style_prompt.strip():
        parts.append("[AUTHOR'S PERSISTENT INSTRUCTION - APPLY EVERY CHAPTER]\n" + story.style_prompt.strip())
    if story.negative_prompt and story.negative_prompt.strip():
        parts.append("[FORBIDDEN - STRICTLY AVOID]\n" + story.negative_prompt.strip())
    parts.append(TASK_CONTINUATION if is_continuation else TASK_FIRST)
    parts.append(JSON_FORMAT_BLOCK)

    # ===== 2. GROWING (append-only -> shared prefix stays cached as chapters accrue) =====
    summaries = _summaries_block(story)
    if summaries:
        parts.append("[CHAPTER SUMMARIES - CHRONOLOGICAL]\n" + summaries)

    # ===== 3. SLOW VARIABLES (change occasionally) =====
    if is_continuation:
        parts.append(
            "[KNOWN UNIVERSE]\n"
            f"Characters:\n{_entity_lines(story.characters, with_status=True)}\n\n"
            f"Locations:\n{_entity_lines(story.locations)}\n\n"
            f"Items:\n{_entity_lines(story.items)}"
        )
    if pinned_block:
        parts.append("[PINNED KEY EVENTS - ALWAYS RELEVANT]\n" + pinned_block)

    # ===== 4. CACHE-BREAKERS (change every chapter -> kept last so they don't spoil the prefix) =====
    if is_continuation:
        last = story.chapters[-1]
        if len(story.chapters) >= 2:
            prev = story.chapters[-2]
            parts.append(
                f"[PREVIOUS CHAPTER (Chapter {prev.index}) - FULL TEXT]\n{_tail(prev.content, PREV_CHAPTER_CAP)}"
            )
        parts.append(
            f"[LAST CHAPTER (Chapter {last.index}) - FULL TEXT]\n{_tail(last.content, LAST_CHAPTER_CAP)}"
        )
    if retrieved_block:
        parts.append(
            "[RELEVANT SCENES FROM PAST CHAPTERS]\n"
            "Older scenes that may relate to the reader's move (use for consistency):\n" + retrieved_block
        )

    edit_notes = parse_edit_notes(story.pending_edit_notes)
    if edit_notes:
        parts.append(
            "[AUTHOR'S RECENT EDITS - VERY IMPORTANT]\n"
            "The author manually changed past chapters. The CURRENT state of the story is below; "
            "do not contradict the old version:\n- " + "\n- ".join(edit_notes)
        )

    return "\n\n".join(parts)


# Language-agnostic: the summary is ALWAYS written in the chapter's language.
SINGLE_CHAPTER_SUMMARY_PROMPT = (
    "You will be given a single chapter of a story. Summarize what happens in it in AT MOST 3 SHORT SENTENCES: "
    "who did what, what changed, what new thing appeared. Do not comment on style; report only what happens. "
    "Always complete your sentences. Write the summary in the SAME LANGUAGE as the chapter. "
    "Output ONLY the summary text, nothing else."
)


# Used on the chapter EDIT path: extracts entities appearing in the edited text so newcomers can
# be added (in main generation the entities come from the generation JSON). Additive only; existing
# entities are never modified or deleted here. Language-agnostic: names/descriptions in the chapter's language.
ENTITY_EXTRACTION_PROMPT = (
    "You will be given the text of a story chapter. Extract the characters, locations, items and key events "
    "that APPEAR in it. Respond with ONLY the following JSON and nothing outside it:\n"
    "{\n"
    '  "new_characters": [{"name": "Character name", "description": "Who they are, physical traits and role"}],\n'
    '  "new_locations": [{"name": "Location name", "description": "Its atmosphere and details"}],\n'
    '  "new_items": [{"name": "Item name", "description": "Its properties and significance"}],\n'
    '  "events": [{"text": "Self-contained description of a key event, in the chapter\'s language", "importance": 0.7}]\n'
    "}\n"
    "Only include what clearly appears in this chapter. Use the SAME LANGUAGE as the chapter for names and descriptions. "
    "If there is nothing relevant, leave the list empty: [].\n" + EVENTS_INSTRUCTION
)
