import secrets
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
from .params import IdPath

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
    """YALNIZCA Authorization header'i. Eskiden SSE icin query string'e (?token=) de bakiyordu
    (EventSource header gonderemedigi icin) — ama URL'e giren bir JWT erisim loguna DUZ METIN
    dusuyor, tarayici gecmisine yaziliyor, referrer ile sizabiliyordu. SSE artik ayri, kisa
    omurlu, tek-kullanimlik bir stream token kullaniyor (bkz. create_stream_token /
    get_stream_user) — ana JWT hicbir zaman URL'e girmez."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


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


STREAM_TOKEN_PURPOSE = "stream"
STREAM_TOKEN_TTL_SECONDS = 60

# Tek-kullanimliktan gecmis jti'ler: jti -> (utc) son gecerlilik ani. Tek uvicorn worker
# varsayimi projede zaten var (bkz. _story_locks, generation.py) — bu yuzden surec-ici bir
# set yeterli, DB/Redis gerekmiyor. TTL kisa oldugu icin dict hicbir zaman buyumez; her
# cagrida (hem consume hem de fazladan bir garanti icin burada) suresi gecenler budanir.
_used_stream_jti: dict[str, datetime] = {}


def _prune_used_stream_jti() -> None:
    now = datetime.now(timezone.utc)
    expired = [jti for jti, exp in _used_stream_jti.items() if exp <= now]
    for jti in expired:
        _used_stream_jti.pop(jti, None)


def create_stream_token(username: str, story_id: int) -> str:
    """SSE ucu icin, ANA JWT'DEN AYRI, dar kapsamli kisa omurlu token. EventSource header
    gonderemedigi icin bu token query string'e girer (?token=...) — ama ana JWT'nin aksine
    ~60sn sonra oleceginden ve TEK KULLANIMLIK oldugundan (bkz. consume), erisim loguna ya
    da tarayici gecmisine dusse bile ele gecirilmesinin degeri neredeyse sifirdir. Yalnizca
    bu story_id icin bu ucu acmaya yarar; baska hicbir uca karsi kullanilamaz (purpose claim'i
    get_current_user tarafindan asla kabul edilmez, cunku o yalnizca Authorization header'ina
    bakar — bu token URL'e gitmek ZORUNDA oldugu icin oraya hic girmez)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "story_id": story_id,
        "purpose": STREAM_TOKEN_PURPOSE,
        "jti": secrets.token_urlsafe(16),
        "exp": now + timedelta(seconds=STREAM_TOKEN_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def _consume_stream_token(token: str, story_id: int) -> str:
    """Dogrular VE tuketir (jti'yi kullanilmis isaretler) — ikinci kullanim (log'dan/gecmisten
    kopyalanmis olsa bile) reddedilir. Hata detaylari kasitli olarak jenerik: 'gecersiz mi,
    suresi mi dolmus, zaten kullanilmis mi' ayrimi disariya sizdirilmaz."""
    _prune_used_stream_jti()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Gecersiz veya suresi dolmus stream token'i.")

    if payload.get("purpose") != STREAM_TOKEN_PURPOSE or payload.get("story_id") != story_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Gecersiz stream token'i.")

    jti = payload.get("jti")
    username = payload.get("sub")
    if not jti or not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Gecersiz stream token'i.")
    if jti in _used_stream_jti:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bu stream token'i zaten kullanildi.")

    # exp zaten jwt.decode tarafindan dogrulandi; ayni sureyi burada da tutuyoruz ki
    # _used_stream_jti kendiliginden (asagida budanan) kucuk kalsin.
    _used_stream_jti[jti] = datetime.now(timezone.utc) + timedelta(seconds=STREAM_TOKEN_TTL_SECONDS)
    return username


async def get_stream_user(
    story_id: IdPath, request: Request, db: AsyncSession = Depends(get_db)
) -> User:
    """SSE ucu icin get_current_user'in YERINE gecer — ana JWT'yi ASLA URL'den kabul etmez.
    Yalnizca create_stream_token ile uretilmis, bu story_id'ye baglanmis, tek kullanimlik
    token'i kabul eder."""
    token = request.query_params.get("token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Giris yapmalisiniz.")
    username = _consume_stream_token(token, story_id)
    user = (await db.execute(select(User).where(User.username == username))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanici bulunamadi.")
    return user


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
