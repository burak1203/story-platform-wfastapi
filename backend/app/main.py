import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from .config import settings
from .database import init_db
from .ratelimit import limiter, rate_limit_handler
from .routers import auth, elements, llm, public, stories

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="StoryPlatform API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(stories.router)
app.include_router(elements.router)
app.include_router(llm.router)
app.include_router(public.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Son çare ağı: HTTPException/validation/rate-limit zaten kendi handler'larında
    ele alınıyor; buraya yalnızca gözden kaçan (örn. beklenmeyen bir DB hatası) düşer.
    KRİTİK: request.headers/body LOGLANMAZ — Authorization ve X-LLM-API-Key buradan
    geçiyor. exc_info yalnızca stack trace basar, istek verisini içermez."""
    logger.error("Yakalanmamış istisna: %s %s", request.method, request.url.path, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Beklenmeyen bir hata oluştu."})


@app.get("/api/health")
async def health():
    return {"status": "ok"}
