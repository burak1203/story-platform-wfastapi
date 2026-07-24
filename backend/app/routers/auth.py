import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models import User
from ..ratelimit import AUTH_LIMIT, limiter
from ..schemas import AuthenticationRequest, GoogleAuthRequest, RegisterRequest, TokenResponse
from ..security import create_token, hash_password, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
@limiter.limit(AUTH_LIMIT)
async def register(
    request: Request, payload: RegisterRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    username = payload.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Kullanıcı adı en az 3 karakter olmalı.")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Şifre en az 6 karakter olmalı.")

    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Bu kullanıcı adı zaten kullanılıyor.")

    email = payload.email.strip().lower() if payload.email else None
    if email:
        existing_email = await db.execute(select(User).where(User.email == email))
        if existing_email.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Bu e-posta zaten kayıtlı.")

    user = User(username=username, email=email, password_hash=hash_password(payload.password))
    db.add(user)
    await db.commit()

    return TokenResponse(token=create_token(username))


@router.post("/authenticate", response_model=TokenResponse)
@limiter.limit(AUTH_LIMIT)
async def authenticate(
    request: Request, payload: AuthenticationRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    user = (
        await db.execute(select(User).where(User.username == payload.username.strip()))
    ).scalar_one_or_none()

    # password_hash None ise hesap Google ile acilmis; sifreyle giris reddedilir
    if user is None or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanıcı adı veya şifre hatalı.")

    return TokenResponse(token=create_token(user.username))


@router.get("/google-config")
async def google_config():
    """Frontend'in Google butonunu gosterip gostermeyecegine karar vermesi icin."""
    return {"clientId": settings.google_oauth_client_id or None}


async def _unique_username(db: AsyncSession, email: str) -> str:
    """E-postanin yerel kismindan bosta olan bir kullanici adi uretir."""
    base = "".join(ch for ch in email.split("@")[0] if ch.isalnum() or ch in "._-")[:56] or "yazar"
    candidate = base
    suffix = 1
    while (
        await db.execute(select(User.id).where(User.username == candidate))
    ).scalar_one_or_none() is not None:
        suffix += 1
        candidate = f"{base}{suffix}"
    return candidate


@router.post("/google", response_model=TokenResponse)
@limiter.limit(AUTH_LIMIT)
async def google_auth(
    request: Request, payload: GoogleAuthRequest, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    if not settings.google_oauth_client_id:
        raise HTTPException(status_code=503, detail="Google girişi bu sunucuda etkin değil.")

    try:
        # verify_oauth2_token blocking (Google sertifikalarini indirir); event loop'u tikamasin
        info = await asyncio.to_thread(
            google_id_token.verify_oauth2_token,
            payload.id_token,
            google_requests.Request(),
            settings.google_oauth_client_id,
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Google doğrulaması başarısız.")

    email = (info.get("email") or "").strip().lower()
    if not email or not info.get("email_verified", False):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Google hesabının doğrulanmış bir e-postası yok.",
        )

    # Ayni e-posta hangi yontemle gelirse gelsin tek hesap: e-posta ile upsert
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is None:
        user = User(username=await _unique_username(db, email), email=email, password_hash=None)
        db.add(user)
        await db.commit()

    return TokenResponse(token=create_token(user.username))
