"""Uretim LLM'ine erisim — BYOK (kullanicinin kendi anahtari).

Global client YOKTUR: her cagri, istekten gelen LlmCtx ile kendi gecici
istemcisini kurar. Kullanicinin anahtari sunucuda saklanmaz, loglanmaz,
DB'ye yazilmaz ve hata mesajlarina sizdirilmaz.
Embedding icin bkz. embeddings.py (SUNUCU anahtariyla calisir).
"""

import asyncio
import logging
from dataclasses import dataclass

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError

from ..config import settings
from .json_utils import parse_llm_json

logger = logging.getLogger(__name__)

# Ucretsiz kotayi ve aninda gelen es zamanli istekleri dizginlemek icin global limit
llm_semaphore = asyncio.Semaphore(settings.llm_concurrency)


class LlmKeyInvalid(Exception):
    """Kullanicinin verdigi anahtar saglayici tarafindan reddedildi."""


@dataclass(frozen=True, repr=False)
class LlmCtx:
    """Kullanicinin LLM ayarlarini istekten arka plan gorevine tasir. Uretim tarafinda
    sunucu varsayilani YOK: base_url, story_model, util_model ucu de kullanicidan gelir.
    provider yalnizca reasoning/thinking-kapat parametresini secmek icin (opsiyonel)."""

    api_key: str
    base_url: str
    story_model: str
    util_model: str
    provider: str = ""

    def __repr__(self) -> str:  # yanlislikla loglansa bile anahtar gorunmesin
        return f"LlmCtx(provider={self.provider!r}, base_url={self.base_url!r}, story_model={self.story_model!r})"


@dataclass(frozen=True)
class LlmUsage:
    """Saglayicinin bildirdigi GERCEK token sayilari (tahmin degil). cached_prompt_tokens
    prefix cache isabeti: DeepSeek `prompt_cache_hit_tokens`, OpenAI
    `prompt_tokens_details.cached_tokens` alaninda doner — saglayici bildirmezse None."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cached_prompt_tokens: int | None = None


def _extract_usage(response) -> LlmUsage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return LlmUsage()
    cached = getattr(usage, "prompt_cache_hit_tokens", None)  # DeepSeek
    if cached is None:
        details = getattr(usage, "prompt_tokens_details", None)  # OpenAI
        cached = getattr(details, "cached_tokens", None) if details is not None else None
    return LlmUsage(
        prompt_tokens=getattr(usage, "prompt_tokens", None),
        completion_tokens=getattr(usage, "completion_tokens", None),
        cached_prompt_tokens=cached,
    )


def _make_client(ctx: LlmCtx) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=ctx.api_key,
        base_url=ctx.base_url,
        max_retries=0,  # retry'i asagida kendimiz yonetiyoruz (backoff surelerini kontrol etmek icin)
        timeout=180.0,
    )


def _reasoning_off_body(provider: str) -> dict | None:
    """Saglayici bazli reasoning/thinking 'kapat' govdesi; bilinmeyen saglayiciya None
    (hicbir sey gonderme -> hata cikmasin)."""
    p = (provider or "").lower()
    if p == "deepseek":
        return {"thinking": {"type": "disabled"}}  # DeepSeek resmi dokumani
    if p == "openrouter":
        return {"reasoning": {"enabled": False}}
    if p == "gemini":
        return {"google": {"thinking_config": {"thinking_budget": 0}}}
    # openai / custom / bos: gonderme.
    return None


def _disable_body(ctx: LlmCtx, reasoning: bool) -> dict | None:
    """Bu cagride reasoning/thinking'i kapatacak govde. Util cagrilarinda (reasoning=False)
    her saglayicida kapatilir (output olarak faturalaniyor, cikarim isinde gereksiz).
    DeepSeek'te AYRICA hikaye uretiminde de kapatilir: thinking modunda temperature/top_p/
    presence_penalty/frequency_penalty sessizce yok sayiliyor; bizim temperature=0.8 cesit-
    liligimiz olur, uretimler tekduzelesir. (Ileride gelismis modda toggle olacak.)"""
    if not reasoning or (ctx.provider or "").lower() == "deepseek":
        return _reasoning_off_body(ctx.provider)
    return None


async def _create(client: AsyncOpenAI, reasoning_off_body: dict | None, **kwargs):
    """chat.completions.create; reasoning_off_body verildiyse extra_body ile gonderir.
    Saglayici parametreyi reddederse (400) parametresiz BIR kez daha dener -> destekleme-
    yen saglayicida util cagrisi patlamaz."""
    if reasoning_off_body:
        try:
            return await client.chat.completions.create(extra_body=reasoning_off_body, **kwargs)
        except APIStatusError as exc:
            if exc.status_code == 400:
                logger.info("Saglayici reasoning-kapat parametresini reddetti; parametresiz denenecek")
                return await client.chat.completions.create(**kwargs)
            raise
    return await client.chat.completions.create(**kwargs)


def _is_bad_key(exc: APIStatusError) -> bool:
    # Gemini gecersiz anahtara bazen 400 "API key not valid" dondurur
    return exc.status_code in (401, 403) or (
        exc.status_code == 400 and "api key" in str(exc).lower()
    )


async def _with_retry(coro_factory, what: str):
    delay = 2.0
    last_exc: Exception | None = None
    for attempt in range(settings.llm_max_retries + 1):
        try:
            return await coro_factory()
        except (RateLimitError, APITimeoutError, APIConnectionError) as e:
            last_exc = e
        except APIStatusError as e:
            if _is_bad_key(e):
                raise LlmKeyInvalid() from e
            if e.status_code < 500:
                raise
            last_exc = e
        if attempt < settings.llm_max_retries:
            logger.warning("%s basarisiz (%s), %.0f sn sonra tekrar denenecek...", what, type(last_exc).__name__, delay)
            await asyncio.sleep(delay)
            delay *= 2
    raise last_exc


async def chat_json_with_usage(ctx: LlmCtx, model: str, system: str, user: str, temperature: float = 0.8, max_tokens: int = 8192, reasoning: bool = True) -> tuple[dict, LlmUsage]:
    """chat_json + saglayicinin bildirdigi gercek token sayilari. Bolum uretimi bunu kullanir
    (token paneli, D3); usage'a ihtiyaci olmayan cagrilar sade chat_json'i cagirir."""
    client = _make_client(ctx)
    reasoning_off = _disable_body(ctx, reasoning)
    try:
        async def call():
            async with llm_semaphore:
                response = await _create(
                    client,
                    reasoning_off,
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
                return parse_llm_json(raw), _extract_usage(response)
            except ValueError as exc:
                last_error = exc
                logger.warning("LLM ciktisi JSON olarak ayiklanamadi (deneme %d/2)", attempt + 1)
        raise last_error
    finally:
        await client.close()


async def chat_json(ctx: LlmCtx, model: str, system: str, user: str, temperature: float = 0.8, max_tokens: int = 8192, reasoning: bool = True) -> dict:
    parsed, _ = await chat_json_with_usage(ctx, model, system, user, temperature, max_tokens, reasoning)
    return parsed


async def chat_text(ctx: LlmCtx, model: str, system: str, user: str, temperature: float = 0.4, max_tokens: int = 1024, reasoning: bool = True) -> str:
    client = _make_client(ctx)
    reasoning_off = _disable_body(ctx, reasoning)
    try:
        async def call():
            async with llm_semaphore:
                response = await _create(
                    client,
                    reasoning_off,
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
    finally:
        await client.close()
