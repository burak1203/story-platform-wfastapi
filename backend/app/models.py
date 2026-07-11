from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, func
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
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    stories: Mapped[list["Story"]] = relationship(back_populates="user", cascade="all, delete-orphan")


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


class Chapter(Base):
    __tablename__ = "chapters"
    __table_args__ = (UniqueConstraint("story_id", "chapter_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    index: Mapped[int] = mapped_column("chapter_index", Integer)
    content: Mapped[str] = mapped_column(Text)
    # Bolumun kendi kisa ozeti; tum ozetler sirayla birlesip hikayenin belini olusturur
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # deferred: bolum listesi cekilirken 768 float'lik vektorler bosuna yuklenmesin
    embedding = mapped_column(Vector(settings.embedding_dim), nullable=True, deferred=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    story: Mapped[Story] = relationship(back_populates="chapters")


class Character(Base):
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("story_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    # Karakterin guncel durumu; her bolumde modelin bildirdigi degisimle guncellenir
    status: Mapped[str | None] = mapped_column(Text, nullable=True)


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (UniqueConstraint("story_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("story_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
