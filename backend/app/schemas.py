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


class ContinueStoryRequest(CamelModel):
    user_action: str


class EditChapterRequest(CamelModel):
    new_content: str


class ElementRequest(CamelModel):
    name: str
    description: str


class ElementDto(CamelModel):
    id: int
    name: str
    description: str
    status: str | None = None


class ChapterDto(CamelModel):
    id: int
    index: int
    content: str


class StoryDetailResponse(CamelModel):
    id: int
    title: str
    content: str
    status: str
    current_summary: str | None
    action_count: int
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
    """ORM Story -> frontend'in bekledigi detay cevabi. content, bolumlerin birlesimidir."""
    return StoryDetailResponse(
        id=story.id,
        title=story.title,
        content="\n\n".join(c.content for c in story.chapters),
        status=story.status,
        current_summary=story.running_summary,
        action_count=len(story.chapters),
        characters=[
            ElementDto(id=c.id, name=c.name, description=c.description, status=c.status)
            for c in story.characters
        ],
        locations=[ElementDto(id=l.id, name=l.name, description=l.description) for l in story.locations],
        items=[ElementDto(id=i.id, name=i.name, description=i.description) for i in story.items],
        chapters=[ChapterDto(id=c.id, index=c.index, content=c.content) for c in story.chapters],
    )
