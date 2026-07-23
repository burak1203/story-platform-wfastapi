import logging

from fastapi import APIRouter, Depends, Request

from ..ai import client as ai
from ..ai.client import LlmCtx
from ..models import User
from ..ratelimit import AUTH_LIMIT, limiter
from ..security import get_current_user, get_llm_ctx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.post("/validate")
@limiter.limit(AUTH_LIMIT)
async def validate_key(
    request: Request,
    ctx: LlmCtx = Depends(get_llm_ctx),
    user: User = Depends(get_current_user),
):
    """Header'daki ayarla (provider/base URL/model/anahtar) kucuk bir test cagrisi yapar.
    Ayarlardan biri eksikse get_llm_ctx zaten 401 llm_config_missing dondurur."""
    try:
        await ai.chat_text(
            ctx, ctx.util_model, "Reply with exactly: ok", "ok",
            temperature=0.0, max_tokens=5, reasoning=False,
        )
        return {"valid": True}
    except Exception:
        # Saglayicinin ham hatasi kullaniciya sizdirilmaz; gecersiz sayilir
        logger.info("LLM anahtari dogrulanamadi")
        return {"valid": False}
