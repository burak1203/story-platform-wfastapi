from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# create_all mevcut tablolara yeni kolon EKLEMEZ; kucuk sema degisiklikleri icin
# elle migration listesi (Alembic gelene kadar yeterli)
_MIGRATIONS = (
    "ALTER TABLE stories ADD COLUMN IF NOT EXISTS style_prompt TEXT",
    "ALTER TABLE stories ADD COLUMN IF NOT EXISTS negative_prompt TEXT",
    "ALTER TABLE stories ADD COLUMN IF NOT EXISTS pending_edit_notes TEXT",
    "ALTER TABLE chapters ADD COLUMN IF NOT EXISTS summary TEXT",
)


async def init_db() -> None:
    from . import models  # noqa: F401 - tablolarin metadata'ya kaydolmasi icin

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
        for migration in _MIGRATIONS:
            await conn.execute(text(migration))


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
