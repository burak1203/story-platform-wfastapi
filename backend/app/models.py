from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
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
    # Moderasyon yetkisi (Faz 4'te kullanilacak): rapor listesi, gizle/sil, dondur.
    # Yalnizca admin is_showcase isaretleyebilir.
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
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


# Hikaye gorunurlugu (Faz 2):
#   private  -> yalnizca sahibi (VARSAYILAN; hicbir public uctan SIZMAZ)
#   unlisted -> linki bilen herkes (listelenmez, aramada cikmaz)
#   public   -> ana sayfada ve aramada gorunur
VISIBILITY_PRIVATE = "private"
VISIBILITY_UNLISTED = "unlisted"
VISIBILITY_PUBLIC = "public"
VISIBILITIES = (VISIBILITY_PRIVATE, VISIBILITY_UNLISTED, VISIBILITY_PUBLIC)
# Auth'suz okunabilen gorunurlukler (private ASLA burada olmamali)
READABLE_WITHOUT_OWNER = (VISIBILITY_UNLISTED, VISIBILITY_PUBLIC)

# Arama vektoru: baslik + aciklama. Sorgu tarafi da AYNI ifadeyi kullanmali, yoksa Postgres
# indeksi kullanamaz (ifade indeksleri birebir eslesme ister).
SEARCH_VECTOR_SQL = "to_tsvector('simple', title || ' ' || coalesce(description, ''))"


class Story(Base):
    __tablename__ = "stories"
    __table_args__ = (
        # Ana sayfa: "son yayimlananlar" (visibility + published_at birlikte taranir)
        Index("ix_stories_visibility_published", "visibility", "published_at"),
        # Etiket filtresi: text[] uzerinde kapsama sorgulari
        Index("ix_stories_tags_gin", "tags", postgresql_using="gin"),
        # Tam metin arama: baslik + aciklama uzerinde GIN. 'simple' KONFIGURASYONU BILINCLI
        # SECIM — platform cok dilli hikaye destekliyor (bkz. prompts CRITICAL LANGUAGE RULE);
        # tek bir dilin stemmer'ini cok dilli korpusa uygulamak sessiz bir dogruluk hatasidir.
        # Hedef kitle ingilizce agirlikli oldugu kanitlanirsa 'english'e gecis tek migration
        # (ve tam yeniden indeksleme) meselesi.
        Index("ix_stories_search_gin", text(SEARCH_VECTOR_SQL), postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    initial_prompt: Mapped[str] = mapped_column(Text)
    # Prompta TAM METIN girecek son bolum sayisi (D3.3). Buyutmek tutarliligi bir miktar
    # artirir ama modeli taklide iter, yaraticiligi dusurur ve token maliyetini katlar;
    # sureklilik zayifsa cozum daha cok ham bolum degil daha iyi retrieval.
    last_chapters_full_text: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")

    # --- Okuyucu platformu (Faz 2) ---
    # VARSAYILAN private: yayimlama bilincli bir eylem olmali, kaza eseri degil.
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, server_default=VISIBILITY_PRIVATE)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    # public + is_adult KOMBINASYONU YASAK (operator TR'de, 5651). Kolon ileri icin rezerve.
    is_adult: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Cold-start: bos siteye gelen ziyaretci kaliteyi anahtar yapistirmadan gorsun.
    # YALNIZCA admin isaretleyebilir; sunucu anahtariyla uretilir.
    is_showcase: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # user|server — "server" yolu SIMDILIK yalnizca showcase+admin'de aktif (kredi katmani sonra)
    key_source: Mapped[str] = mapped_column(String(16), nullable=False, server_default="user")
    # Ilk yayimlanma ani. Yalnizca NULL iken doldurulur: yayindan alip geri koyarak
    # ana sayfada one cikma (gaming) olmasin.
    published_at: Mapped[datetime | None] = mapped_column(nullable=True)
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
    prompt_items: Mapped[list["PromptItem"]] = relationship(
        cascade="all, delete-orphan", order_by="PromptItem.order, PromptItem.id", lazy="selectin"
    )


class Comment(Base):
    """Bolum bazli yorum — DUZ LISTE, thread YOK (bilincli: moderasyon yuku ve UI karmasikligi
    launch icin gereksiz). Yazarin kendi yorumu rozetlenir ve sabitlenebilir."""

    __tablename__ = "comments"
    __table_args__ = (
        # Bolum sayfasi: sabitlenenler once, sonra kronolojik (sayfali)
        Index("ix_comments_chapter_created", "chapter_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    # Sabitleme yetkisi YALNIZCA hikayenin yazarindadir; kendi yorumunu da bir okurun
    # yorumunu da tepeye tasiyabilir. Yorumcunun kendisi sabitleyemez — aksi halde herkes
    # kendi yorumunu tepeye tasir ve sabitleme anlamini yitirir.
    is_author_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ChapterVote(Base):
    """Bolum begenisi: tek tik, geri alinabilir. UNIQUE(chapter_id, user_id) cift oyu
    VERITABANI SEVIYESINDE engeller — yaris kosulunda bile ikinci oy atilamaz.
    Yildiz/puan YOK: tek boyutlu begeni kotuye kullanimi zorlastirir ve okuru yormaz."""

    __tablename__ = "chapter_votes"
    __table_args__ = (UniqueConstraint("chapter_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Report(Base):
    """Kullanici bildirimi (Faz 4 moderasyon araclari bunu okuyacak). target_type ile
    hedef turu ayrilir (story|chapter|comment); FK KOYULMAZ cunku farkli tablolari
    isaret ediyor — silinen hedefin raporu kayit olarak kalsin."""

    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_status_created", "status", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    target_type: Mapped[str] = mapped_column(String(16))  # story | chapter | comment
    target_id: Mapped[int] = mapped_column(Integer)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PromptItem(Base):
    """Yazarin kalici talimatlari — tek blob yerine SIRALI MADDE listesi (D3.3).

    Faydasi: her maddeyi tek tek acip kapatabilmek, izole edebilmek, sirasini degistirebilmek.
    kind: "style" (uygulanacak) | "negative" (kacinilacak).

    NOT — cache icin ID-slot mantigi ISE YARAMAZ: prefix cache METIN sirasini eslestirir,
    ID'leri degil; ortadan yapilan her duzenleme o noktadan sonrasini zaten gecersiz kilar.
    Tek gercek optimizasyon kalici kurallari uste, deneysel olanlari alta koymak (sirayi
    yazar belirler). Yazar bunlari ayda bir duzenler, bolum basina degil — cache kirilmasi
    onemsiz."""

    __tablename__ = "prompt_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # style | negative
    text: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # "order" SQL'de ayrilmis kelime; kolon adi order_index
    order: Mapped[int] = mapped_column("order_index", Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


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
    # Token muhasebesi (D3.1). prompt/completion: SAGLAYICININ bildirdigi gercek sayilar.
    # cached_prompt_tokens: prefix cache isabeti (DeepSeek/OpenAI bildirirse) — prompt sirasi
    # calismalarinin gercek olcusu. token_breakdown: tiktoken ile bilesen bazli kirilim (JSON).
    # Saglayici usage dondurmezse NULL kalir. UI Faz 3 (developer mode).
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_breakdown: Mapped[str | None] = mapped_column(Text, nullable=True)
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
