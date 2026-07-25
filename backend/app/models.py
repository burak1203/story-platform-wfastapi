from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .config import settings
from .database import Base

# Hikaye durumlari:
#   PENDING    -> ilk bolum henuz uretiliyor (hikayede okunacak icerik yok)
#   GENERATING -> devam bolumu uretiliyor (mevcut bolumler okunabilir)
#   COMPLETED  -> uretim yok, hikaye kullanima hazir
#   FAILED     -> ilk bolum uretimi basarisiz oldu (tekrar denenebilir)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    # Google ile acilan hesaplarin sifresi yoktur (None); sifreli giriste None reddedilir
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    stories: Mapped[list["Story"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class EmbedUsage(Base):
    """Kullanici basina gunluk embed cagri sayaci (kotu niyetli kota tuketimine karsi)."""

    __tablename__ = "embed_usage"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class Story(Base):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    initial_prompt: Mapped[str] = mapped_column(Text)
    # Yazarin kalici talimatlari: her bolum uretiminde sisteme enjekte edilir
    style_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Yazar bolum duzenledikten sonra bir SONRAKI uretime tasinacak notlar (JSON listesi)
    pending_edit_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="stories")
    chapters: Mapped[list["Chapter"]] = relationship(
        back_populates="story",
        cascade="all, delete-orphan",
        order_by="Chapter.index",
        lazy="selectin",
    )
    characters: Mapped[list["Character"]] = relationship(
        cascade="all, delete-orphan", order_by="Character.id", lazy="selectin"
    )
    locations: Mapped[list["Location"]] = relationship(
        cascade="all, delete-orphan", order_by="Location.id", lazy="selectin"
    )
    items: Mapped[list["Item"]] = relationship(
        cascade="all, delete-orphan", order_by="Item.id", lazy="selectin"
    )
    # selectin: prompt kurucusu SENKRON ve saf; arklara async lazy-load olmadan erisebilsin
    arcs: Mapped[list["Arc"]] = relationship(
        cascade="all, delete-orphan", order_by="Arc.start_index", lazy="selectin"
    )


class Arc(Base):
    """Rollup katmani (D2): bolum ozetlerinin SIKISTIRILMIS ust katmanlari. Amac, hikaye kac
    bolum olursa olsun ozet blogunun token boyutunun SABIT kalmasi — ama hicbir sey unutulmadan
    (eski bilgi silinmez, sikisir).

    level 0 = ARK: ard arda ROLLUP_ARC_SIZE bolumun ozeti tek paragrafa iner.
    level 1 = ARKA PLAN: en eski arklarin ozeti tek paragraflik "buraya kadar hikaye"ye iner.

    Ozetler DB'de saklanir, HER URETIMDE YENIDEN URETILMEZ. Gecersiz kilma = SILME: icindeki
    bir bolum duzenlenince o ark (ve onu kapsayan arka plan) silinir; bir sonraki rollup
    kosusunda yeniden uretilir, o ana kadar prompt ham bolum ozetlerine duser (kayip yok)."""

    __tablename__ = "arcs"
    __table_args__ = (UniqueConstraint("story_id", "level", "start_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(Integer)  # 0 = ark, 1 = arka plan
    start_index: Mapped[int] = mapped_column(Integer)  # kapsanan ilk bolum indeksi (dahil)
    end_index: Mapped[int] = mapped_column(Integer)    # kapsanan son bolum indeksi (dahil)
    summary: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("story_id", "chapter_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column("chapter_index", Integer)
    content: Mapped[str] = mapped_column(Text)
    # Bolumun kendi kisa ozeti; tum ozetler sirayla birlesip hikayenin belini olusturur
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NOT: eski `embedding` kolonu C4.2'de DUSURULDU. Icindeki vektorler GEMINI uzayindaydi;
    # OpenAI sorgusuyla kiyaslanamiyordu ve yeni bolumlerde zaten NULL kaliyordu. Yerine
    # bolum basina chunk katmani (chunks tablosu, OpenAI uzayi) gecti.
    # Olay sisteminden onceki bolumler icin lazy backfill deneme sayaci: sonsuz yeniden
    # deneme olmasin diye (MAX'a ulasinca o bolum backfill'de artik denenmez).
    backfill_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    story: Mapped[Story] = relationship(back_populates="chapters")


class Event(Base):
    """Olay-tabanli hafizanin cekirdegi: her bolumden cikarilan, KENDI BASINA anlasilir
    olaylar. Her olay embed'lenip (C3) sonsuza dek saklanir; RAG'le geri cagrildikca
    importance'i yukselir (retrieved_count). Silme YOK: dusuk importance = "her turda sabit
    omurgada gitmez" demek, depodan silinmek degil.

    embedding NULLABLE: C2'de olaylar embedding'siz olusur; C3'te embedding'i NULL olan
    olaylar doldurulur. Bu sayede C2-C3 arasi uretilen olaylar kaybolmaz."""

    __tablename__ = "events"
    __table_args__ = (
        # Olay-embed uzerinden cosine retrieval (C3). NULL embedding'ler indekste yer tutmaz.
        Index(
            "ix_events_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    # 0.0-1.0: yazimda on-tahmin; RAG'le cekildikce yukselir (dinamik onem)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    retrieved_count: Mapped[int] = mapped_column(Integer, default=0)
    # deferred: olay listesi cekilirken 768 float bosuna yuklenmesin
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=True, deferred=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Chunk(Base):
    """RAG chunk katmani (C4): bolumun ~400-600 token'lik, LLM'siz, DETERMINISTIK parcalari.
    Olay katmani KAYIPLI (LLM'in sectigi 3-7 olay iskeleti tasir) — chunk'lar bolumun TAMAMINI
    kapsar, boylece olay listesine girmemis yerel detay ("1. bolumde dondurma yedi") ileri bir
    bolumde ilgili hamleyle RAG'le bulunabilir. Bolum uretilince/duzenlenince bolumun chunk'lari
    silinip yeniden yazilir (idempotent, yetim kalmaz).

    embedding NULLABLE: embed patlarsa chunk NULL ile kaydedilir ve uretim BLOKLANMAZ; telafi
    yolu (olaylardaki gibi) NULL'lari doldurur. Bu vektorler OpenAI uzayindadir (olaylarla ayni;
    eski chapters.embedding Gemini uzayindaydi, C4.2'de dusuruldu)."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("chapter_id", "chunk_index"),
        # Chunk-embed uzerinden cosine retrieval (C4.3). NULL embedding'ler indekste yer tutmaz.
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # deferred: chunk listesi cekilirken 768 float bosuna yuklenmesin
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=True, deferred=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


# Entity embed'leri (C4.2): description (+ karakterde status) birlestirilip embed'lenir.
# KULLANIMI D3'te — hangi kartlarin prompta girecegine karar vermek (kart secimi) icin.
# C4.2'de yalnizca DOLDURULUR; prompta hicbir sey degismez. Olay/chunk'larla AYNI uzayda
# (OpenAI text-embedding-3-small, 768). NULLABLE: embed patlarsa entity yine kaydedilir,
# telafi yolu NULL'lari doldurur.


class Character(Base):
    __tablename__ = "characters"
    __table_args__ = (
        UniqueConstraint("story_id", "name"),
        Index(
            "ix_characters_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    # Karakterin guncel durumu; her bolumde modelin bildirdigi degisimle guncellenir
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    # deferred: kart listesi cekilirken 768 float bosuna yuklenmesin
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=True, deferred=True)


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("story_id", "name"),
        Index(
            "ix_locations_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=True, deferred=True)


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("story_id", "name"),
        Index(
            "ix_items_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=True, deferred=True)
