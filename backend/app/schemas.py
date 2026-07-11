from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from .models import Story


class CamelModel(BaseModel):
    """Frontend camelCase beklediginden tum alanlar camelCase'e cevrilerek serialize edilir."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


# --- Auth ---


class RegisterRequest(CamelModel):
    username: str
    password: str
    email: str | None = None


class AuthenticationRequest(CamelModel):
    username: str
    password: str


class TokenResponse(CamelModel):
    token: str


# --- Story ---


class CreateStoryRequest(CamelModel):
    title: str
    starting_prompt: str
    style_prompt: str | None = None
    negative_prompt: str | None = None


class ContinueStoryRequest(CamelModel):
    user_action: str


class EditChapterRequest(CamelModel):
    new_content: str


class EditChapterSummaryRequest(CamelModel):
    new_summary: str


class UpdateStorySettingsRequest(CamelModel):
    style_prompt: str | None = None
    negative_prompt: str | None = None


class ElementRequest(CamelModel):
    name: str
    description: str


class CreateElementRequest(CamelModel):
    story_id: int
    name: str
    description: str = ""


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


def story_detail(story: Story) -> StoryDetailResponse:
    """ORM Story -> frontend'in bekledigi detay cevabi. content, bolumlerin birlesimidir;
    current_summary, bolum ozetlerinin kronolojik birlesimidir."""
    joined_summary = "\n\n".join(
        f"Bölüm {c.index}: {c.summary.strip()}" for c in story.chapters if c.summary
    )
    return StoryDetailResponse(
        id=story.id,
        title=story.title,
        content="\n\n".join(c.content for c in story.chapters),
        status=story.status,
        current_summary=joined_summary or None,
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
