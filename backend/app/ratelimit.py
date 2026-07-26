"""Istek hiz limitleri (slowapi, in-memory — tek worker icin yeterli).

Anahtar secimi: gecerli JWT tasiyan istekler kullanici basina, digerleri IP basina
sayilir. Boylece uretim uclarinda ayni kullanici farkli IP'lerden de olsa tek
kovada toplanir; auth uclarinda ise dogal olarak IP basina limit uygulanir.
"""

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import settings

GENERATION_LIMIT = "3/minute"  # LLM'e giden pahali uclar (uretim, bolum duzenleme)
AUTH_LIMIT = "5/minute"        # kayit/giris (IP basina; brute-force onlemi)
SEARCH_LIMIT = "20/minute"     # embed harcayan arama (yazarin hikaye ici aramasi)

# Public okuma uclari: auth'suz erisilir, cogu istek IP basina sayilir.
# Okuma GEVSEK (okur bolum bolum gezer), arama daha SIKI (full-text tarama + kazima onlemi).
PUBLIC_READ_LIMIT = "120/minute"
PUBLIC_SEARCH_LIMIT = "30/minute"


def user_or_ip(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            payload = jwt.decode(auth_header[7:], settings.jwt_secret, algorithms=["HS256"])
            sub = payload.get("sub")
            if sub:
                return f"user:{sub}"
        except jwt.PyJWTError:
            pass
    return get_remote_address(request)


limiter = Limiter(key_func=user_or_ip)


def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Çok fazla istek gönderdin, lütfen biraz bekleyip tekrar dene."},
    )
