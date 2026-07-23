"""Embedding erisimi — her zaman SUNUCUNUN anahtariyla (EMBEDDING_API_KEY).

Kullanicinin uretim anahtari buradan ASLA gecmez; kullanici embedding'i hic gormez.
Saglayici EMBEDDING_PROVIDER env'iyle secilir: "openai" (varsayilan, text-embedding-3-small
dimensions=768) veya "gemini" (openai-uyumlu uc; alternatif). Arayuz: embed(texts) ->
list[768 boyutlu vektor], TEK API cagrisiyla (batch).

DIKKAT: EMBEDDING_PROVIDER veya EMBEDDING_MODEL degisirse eski ve yeni vektorler
karsilastirilamaz (uzaylar farkli); ilgili tum kayitlarin bastan embed edilmesi gerekir.
Mevcut chapters.embedding kolonu GEMINI uzayindadir; olay-embed OpenAI uzayindadir —
ikisi ASLA ayni sorguda karsilastirilmaz.
"""

import logging
from datetime import date

from openai import AsyncOpenAI
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import EmbedUsage
from .client import LlmKeyInvalid, _with_retry, llm_semaphore

logger = logging.getLogger(__name__)

_SUPPORTED_PROVIDERS = ("openai", "gemini")

# Embedding girisinin token limitini asmamak icin kaba karakter siniri
EMBED_CHAR_LIMIT = 6000


class EmbedQuotaExceeded(Exception):
    """Kullanicinin gunluk embed kotasi doldu."""


# Sunucu anahtari sabittir; istemci modul seviyesinde bir kez kurulur
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if settings.embedding_provider not in _SUPPORTED_PROVIDERS:
        raise RuntimeError(f"Desteklenmeyen embedding saglayicisi: {settings.embedding_provider}")
    if not settings.embedding_api_key:
        raise RuntimeError("EMBEDDING_API_KEY tanimli degil; embedding yapilamaz.")
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.embedding_api_key,
            # openai icin bos -> SDK varsayilani (api.openai.com); gemini icin openai-uyumlu uc
            base_url=settings.embedding_base_url or None,
            max_retries=0,
            timeout=60.0,
        )
    return _client


async def embed(texts: list[str]) -> list[list[float]]:
    """Metin listesini ayni sirayla vektor listesine cevirir (tek API cagrisi)."""
    client = _get_client()
    inputs = [t[:EMBED_CHAR_LIMIT] for t in texts]

    async def call():
        async with llm_semaphore:
            return await client.embeddings.create(
                model=settings.embedding_model,
                input=inputs,
                dimensions=settings.embedding_dim,
            )

    try:
        response = await _with_retry(call, "Embedding cagrisi")
    except LlmKeyInvalid as exc:
        # Buradaki anahtar kullanicinin degil sunucunun; kullaniciya "anahtarin
        # gecersiz" dememek icin farkli bir hataya cevir
        raise RuntimeError("Sunucunun embedding anahtari saglayici tarafindan reddedildi") from exc
    # OpenAI her embedding icin `index` doner -> sirayi garantilemek icin ona gore sirala.
    # Gemini'nin openai-uyumlu ucu batch'te index vermez (None) -> API zaten giris sirasini
    # korur, oldugu gibi birak (aksi halde int/None karsilastirmasi patlar).
    data = response.data
    if all(item.index is not None for item in data):
        data = sorted(data, key=lambda d: d.index)
    return [item.embedding for item in data]


async def consume_quota(db: AsyncSession, user_id: int, calls: int = 1) -> None:
    """Gunluk sayaci atomik artirir; limit asilirsa EmbedQuotaExceeded firlatir.
    Commit cagirana birakilir (artis, istegin kendi commit'iyle kalicilasir)."""
    stmt = (
        pg_insert(EmbedUsage)
        .values(user_id=user_id, day=date.today(), count=calls)
        .on_conflict_do_update(
            index_elements=[EmbedUsage.user_id, EmbedUsage.day],
            set_={"count": EmbedUsage.count + calls},
        )
        .returning(EmbedUsage.count)
    )
    new_count = (await db.execute(stmt)).scalar_one()
    if new_count > settings.embed_daily_limit:
        raise EmbedQuotaExceeded()


async def embed_for_user(db: AsyncSession, user_id: int, texts: list[str]) -> list[list[float]]:
    """Kota denetimli embed: once kullanicinin gunluk sayacini artirir, sonra embed eder."""
    await consume_quota(db, user_id, calls=1)
    return await embed(texts)
