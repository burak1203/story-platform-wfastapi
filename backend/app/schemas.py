from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .ai.prompts import LAST_CHAPTERS_MAX, LAST_CHAPTERS_MIN
from .models import Story

# Girdi tavanlari (kotuye kullanim / prompt sisirme onlemi)
MAX_PROMPT_LEN = 5_000     # kullanici talimatlari (konu, hamle, style/negative)
MAX_PROMPT_ITEM_LEN = 1_000  # tek bir talimat maddesi
MAX_PROMPT_ITEMS = 50        # hikaye basina azami madde (prompt sisirme onlemi)
MAX_DESCRIPTION_LEN = 2_000  # yayin aciklamasi (ana sayfa/arama)
MAX_TAGS = 10                # hikaye basina azami etiket
MAX_TAG_LEN = 32
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
    """Hikaye bazli uretim ayarlari. style/negative talimatlar artik burada DEGIL —
    ayri madde uclarinda (prompt-items)."""

    last_chapters_full_text: int = Field(ge=LAST_CHAPTERS_MIN, le=LAST_CHAPTERS_MAX)


class UpdatePublishingRequest(CamelModel):
    """Yayimlama ayarlari. public'e gecerken kurallar onayi ZORUNLU (rules_accepted)."""

    visibility: str = Field(pattern="^(private|unlisted|public)$")
    description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LEN)
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    is_adult: bool = False
    rules_accepted: bool = False


class PublishingDto(CamelModel):
    visibility: str
    description: str | None
    tags: list[str]
    is_adult: bool
    is_showcase: bool
    published_at: datetime | None


class PromptItemDto(CamelModel):
    id: int
    kind: str
    text: str
    enabled: bool
    order: int


class CreatePromptItemRequest(CamelModel):
    kind: str = Field(pattern="^(style|negative)$")
    text: str = Field(min_length=1, max_length=MAX_PROMPT_ITEM_LEN)


class UpdatePromptItemRequest(CamelModel):
    text: str | None = Field(default=None, max_length=MAX_PROMPT_ITEM_LEN)
    enabled: bool | None = None


class ReorderPromptItemsRequest(CamelModel):
    """Maddelerin YENI sirasi: id listesi, istenen sirada. Listede olmayanlar sona alinir."""

    item_ids: list[int] = Field(max_length=MAX_PROMPT_ITEMS)


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
    last_chapters_full_text: int
    prompt_items: list[PromptItemDto]
    publishing: PublishingDto
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
    # Eslesen bolumun sahne pencereleri (chunk yolunda: eslesen chunk'in ETRAFINDAKI birlesik
    # bloklar, chunk sirasinda; olay yolunda: eslesen olay metinleri). Her ogenin index'i
    # eslesen bolumun indeksidir. Eski "bolum n-1/n/n+1 basindan alinti" mantigi kalkti.
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
        last_chapters_full_text=story.last_chapters_full_text,
        prompt_items=[
            PromptItemDto(id=p.id, kind=p.kind, text=p.text, enabled=p.enabled, order=p.order)
            for p in sorted(story.prompt_items, key=lambda p: (p.order, p.id))
        ],
        publishing=PublishingDto(
            visibility=story.visibility,
            description=story.description,
            tags=list(story.tags or []),
            is_adult=story.is_adult,
            is_showcase=story.is_showcase,
            published_at=story.published_at,
        ),
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
