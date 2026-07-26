from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .ai.client import LlmCtx
from .config import settings
from .database import get_db
from .models import User

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_token(username: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expires_minutes)
    return jwt.encode({"sub": username, "exp": expires}, settings.jwt_secret, algorithm=ALGORITHM)


def _extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    # EventSource header gonderemedigi icin SSE ucunda ?token= destekleniyor
    return request.query_params.get("token")


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> User:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Giris yapmalisiniz.")

    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Gecersiz veya suresi dolmus oturum.")

    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Gecersiz oturum.")

    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanici bulunamadi.")
    return user


async def get_optional_user(
    request: Request, db: AsyncSession = Depends(get_db)
) -> User | None:
    """Girisi ZORUNLU KILMAYAN uclar icin (public okuma). Token yoksa, bozuksa ya da suresi
    dolmussa 401 ATMAZ, None doner: okuma girissiz de calisan bir islem — oturumun suresi
    doldu diye okurun sayfasi kirilmamali. Yalnizca "bu okur bunu begenmis mi" gibi
    kisisellestirme icin kullanilir, YETKI KARARI icin ASLA (yetki gereken uclar
    get_current_user kullanir)."""
    token = _extract_token(request)
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
    except jwt.PyJWTError:
        return None
    if not username:
        return None
    return (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()


def get_llm_ctx(request: Request) -> LlmCtx:
    """BYOK: uretim yapan uclarda kullanicinin LLM ayarlarini header'dan alir. Sunucuda
    varsayilan YOK: base URL + model + anahtar UCU DE gelmeli; eksikse 401 llm_config_missing
    (frontend bunu ayar modaline yonlendirir). provider opsiyonel (reasoning-kapat icin)."""
    api_key = (request.headers.get("X-LLM-API-Key") or "").strip()
    base_url = (request.headers.get("X-LLM-Base-URL") or "").strip()
    model = (request.headers.get("X-LLM-Model") or "").strip()
    provider = (request.headers.get("X-LLM-Provider") or "").strip()
    if not (api_key and base_url and model):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="llm_config_missing")

    return LlmCtx(
        api_key=api_key,
        base_url=base_url,
        story_model=model,
        util_model=model,
        provider=provider,
    )
