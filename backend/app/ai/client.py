import asyncio
import logging

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError

from ..config import settings
from .json_utils import parse_llm_json

logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    api_key=settings.llm_api_key,
    base_url=settings.llm_base_url,
    max_retries=0,  # retry'i asagida kendimiz yonetiyoruz (backoff surelerini kontrol etmek icin)
    timeout=180.0,
)

# Ucretsiz kotayi ve aninda gelen es zamanli istekleri dizginlemek icin global limit
llm_semaphore = asyncio.Semaphore(settings.llm_concurrency)

# Gemini embedding girisinin token limitini asmamak icin kaba karakter siniri
EMBED_CHAR_LIMIT = 6000


async def _with_retry(coro_factory, what: str):
    delay = 2.0
    last_exc: Exception | None = None
    for attempt in range(settings.llm_max_retries + 1):
        try:
            return await coro_factory()
        except (RateLimitError, APITimeoutError, APIConnectionError) as e:
            last_exc = e
        except APIStatusError as e:
            if e.status_code < 500:
                raise
            last_exc = e
        if attempt < settings.llm_max_retries:
            logger.warning("%s basarisiz (%s), %.0f sn sonra tekrar denenecek...", what, type(last_exc).__name__, delay)
            await asyncio.sleep(delay)
            delay *= 2
    raise last_exc


async def chat_json(model: str, system: str, user: str, temperature: float = 0.8, max_tokens: int = 8192) -> dict:
    async def call():
        async with llm_semaphore:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
        return response

    # Model gecerli JSON uretmezse bir kez daha sans ver (onarim da tutmazsa)
    last_error: Exception | None = None
    for attempt in range(2):
        response = await _with_retry(call, f"LLM cagrisi ({model})")
        choice = response.choices[0]
        if choice.finish_reason == "length":
            logger.warning("LLM cevabi max_tokens sinirinda kesildi; JSON onarimi denenecek.")
        raw = choice.message.content or ""
        try:
            return parse_llm_json(raw)
        except ValueError as exc:
            last_error = exc
            logger.warning("LLM ciktisi JSON olarak ayiklanamadi (deneme %d/2)", attempt + 1)
    raise last_error


async def chat_text(model: str, system: str, user: str, temperature: float = 0.4, max_tokens: int = 1024) -> str:
    async def call():
        async with llm_semaphore:
            response = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return response

    response = await _with_retry(call, f"LLM cagrisi ({model})")
    return (response.choices[0].message.content or "").strip()


async def embed(text: str) -> list[float]:
    async def call():
        async with llm_semaphore:
            response = await client.embeddings.create(
                model=settings.embedding_model,
                input=text[:EMBED_CHAR_LIMIT],
                dimensions=settings.embedding_dim,
            )
        return response

    response = await _with_retry(call, "Embedding cagrisi")
    return response.data[0].embedding
