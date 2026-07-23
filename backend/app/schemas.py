from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .models import Story

# Girdi tavanlari (kotuye kullanim / prompt sisirme onlemi)
MAX_PROMPT_LEN = 5_000     # kullanici talimatlari (konu, hamle, style/negative)
MAX_CHAPTER_LEN = 60_000   # bolum metni
MAX_SUMMARY_LEN = 2_000
MAX_NAME_LEN = 120
MAX_DESC_LEN = 2_000


class CamelModel(BaseModel):
    """Frontend camelCase beklediginden tum alanlar camelCase'e cevrilerek serialize edilir."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# --- Auth ---


class RegisterRequest(CamelModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)
    email: str | None = Field(default=None, max_length=255)


class AuthenticationRequest(CamelModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)


class GoogleAuthRequest(CamelModel):
    id_token: str = Field(max_length=4_096)


class TokenResponse(CamelModel):
    token: str


# --- Story ---


class CreateStoryRequest(CamelModel):
    title: str = Field(max_length=255)
    starting_prompt: str = Field(max_length=MAX_PROMPT_LEN)
    style_prompt: str | None = Field(default=None, max_length=MAX_PROMPT_LEN)
    negative_prompt: str | None = Field(default=None, max_length=MAX_PROMPT_LEN)


class ContinueStoryRequest(CamelModel):
    user_action: str = Field(max_length=MAX_PROMPT_LEN)


class EditChapterRequest(CamelModel):
    new_content: str = Field(max_length=MAX_CHAPTER_LEN)


class EditChapterSummaryRequest(CamelModel):
    new_summary: str = Field(max_length=MAX_SUMMARY_LEN)


class UpdateStorySettingsRequest(CamelModel):
    style_prompt: str | None = Field(default=None, max_length=MAX_PROMPT_LEN)
    negative_prompt: str | None = Field(default=None, max_length=MAX_PROMPT_LEN)


class ElementRequest(CamelModel):
    name: str = Field(max_length=MAX_NAME_LEN)
    description: str = Field(max_length=MAX_DESC_LEN)


class CreateElementRequest(CamelModel):
    story_id: int
    name: str = Field(max_length=MAX_NAME_LEN)
    description: str = Field(default="", max_length=MAX_DESC_LEN)


class ElementDto(CamelModel):
    id: int
    name: str
    description: str
    status: str | None = None


class ChapterDto(CamelModel):
    id: int
    index: int
    content: str
    summary: str | None = None


class StorySummaryResponse(CamelModel):
    """Dashboard listesi icin hafif DTO: bolum metinlerini TASIMAZ (tam icerik yalnizca
    tek-hikaye detay ucundan gelir). Uzun hikayelerde liste sisip yavaslamasin diye."""

    id: int
    title: str
    status: str
    action_count: int
    current_summary: str | None


class StoryDetailResponse(CamelModel):
    id: int
    title: str
    content: str
    status: str
    current_summary: str | None
    action_count: int
    style_prompt: str | None
    negative_prompt: str | None
    characters: list[ElementDto]
    locations: list[ElementDto]
    items: list[ElementDto]
    chapters: list[ChapterDto]


class SearchWindowChapter(CamelModel):
    index: int
    excerpt: str


class SearchHit(CamelModel):
    chapter_index: int
    distance: float
    # n-1 / n / n+1 penceresi: eslesen bolum ve komsulari, sirali
    window: list[SearchWindowChapter]


def _joined_summary(story: Story) -> str | None:
    joined = "\n\n".join(f"Bölüm {c.index}: {c.summary.strip()}" for c in story.chapters if c.summary)
    return joined or None


def story_summary(story: Story) -> StorySummaryResponse:
    """ORM Story -> dashboard liste ogesi (bolum metni olmadan)."""
    return StorySummaryResponse(
        id=story.id,
        title=story.title,
        status=story.status,
        action_count=len(story.chapters),
        current_summary=_joined_summary(story),
    )


def story_detail(story: Story) -> StoryDetailResponse:
    """ORM Story -> frontend'in bekledigi detay cevabi. content, bolumlerin birlesimidir;
    current_summary, bolum ozetlerinin kronolojik birlesimidir."""
    return StoryDetailResponse(
        id=story.id,
        title=story.title,
        content="\n\n".join(c.content for c in story.chapters),
        status=story.status,
        current_summary=_joined_summary(story),
        action_count=len(story.chapters),
        style_prompt=story.style_prompt,
        negative_prompt=story.negative_prompt,
        characters=[
            ElementDto(id=c.id, name=c.name, description=c.description, status=c.status)
            for c in story.characters
        ],
        locations=[ElementDto(id=l.id, name=l.name, description=l.description) for l in story.locations],
        items=[ElementDto(id=i.id, name=i.name, description=i.description) for i in story.items],
        chapters=[
            ChapterDto(id=c.id, index=c.index, content=c.content, summary=c.summary)
            for c in story.chapters
        ],
    )
