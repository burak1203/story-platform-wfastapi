import asyncio
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Sema Alembic ile yonetilir. Auto-create/ALTER blocklari KALDIRILDI: acilista
# "alembic upgrade head" calisir (bos prod DB tablolari kurar, mevcut DB baseline'dan
# ileri migration'lari uygular). alembic.ini bu dosyanin iki ust dizininde (backend/).
_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

# Uygulama uretim ortasinda kapanirsa hikayeler PENDING/GENERATING'de takili kalir
# ve sonsuza dek 409 doner; acilista toparla (uretim gorevleri process'le birlikte olur,
# bu yuzden acilista "busy" hikaye olamaz): bolumu olmayan FAILED, digerleri COMPLETED.
_RECOVER_STUCK_STATUSES = (
    "UPDATE stories SET status = 'FAILED' WHERE status IN ('PENDING', 'GENERATING') "
    "AND NOT EXISTS (SELECT 1 FROM chapters WHERE chapters.story_id = stories.id)",
    "UPDATE stories SET status = 'COMPLETED' WHERE status IN ('PENDING', 'GENERATING')",
)


def _run_upgrade() -> None:
    """alembic upgrade head — senkron. to_thread icinden cagrilir: async env.py online
    modda kendi asyncio.run'ini kullaniyor, calisan event loop icinden dogrudan cagrilamaz."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_ALEMBIC_INI.parent / "alembic"))
    command.upgrade(cfg, "head")


# DB denetim raporu bulgusu: EMBEDDING_DIM .env'den okunur ama migration'larda vektor
# boyutu 768 SABIT yazili (bkz. models.py Vector(settings.embedding_dim) vs. migration'daki
# pgvector.sqlalchemy.vector.VECTOR(dim=768)). Biri degisip digeri migrationsuz kalirsa
# ORM'in bekledigi boyutla DB kolonunun gercek boyutu SESSIZCE ayrisir — bozuk embedding'den
# daha kotu, cunku hata hemen degil aylar sonra "queryyle hicbir sey eslesmiyor" olarak
# ortaya cikar. Acilista karsilastir, uyusmazsa ACILMA.
_VECTOR_TABLES = ("events", "chunks", "characters", "locations", "items")


async def _check_embedding_dim(conn) -> None:
    rows = (
        await conn.execute(
            text(
                """
                SELECT c.relname, a.atttypmod
                FROM pg_attribute a JOIN pg_class c ON a.attrelid = c.oid
                WHERE c.relname = ANY(:tables) AND a.attname = 'embedding' AND a.attnum > 0
                """
            ),
            {"tables": list(_VECTOR_TABLES)},
        )
    ).all()
    mismatched = [(table, dim) for table, dim in rows if dim != settings.embedding_dim]
    if mismatched:
        details = ", ".join(f"{table}={dim}" for table, dim in mismatched)
        raise RuntimeError(
            f"EMBEDDING_DIM ({settings.embedding_dim}) DB'deki gercek vektor boyutuyla "
            f"uyusmuyor: {details}. Byle baslatmak sessizce bozuk/yanlis-uzayli embedding "
            "uretir. EMBEDDING_DIM'i DB'deki gercek boyuta geri al, ya da boyutu kasitli "
            "degistirdiysen TUM vektor kolonlarini yeni boyuta tasiyan bir migration yaz "
            "ve mevcut kayitlari yeniden embed'le."
        )


async def init_db() -> None:
    # Semayi guncel migration'a getir (auto-create YOK)
    await asyncio.to_thread(_run_upgrade)
    async with engine.begin() as conn:
        await _check_embedding_dim(conn)
        # Runtime toparlama: acilistaki takili uretim durumlarini duzelt
        for statement in _RECOVER_STUCK_STATUSES:
            await conn.execute(text(statement))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
