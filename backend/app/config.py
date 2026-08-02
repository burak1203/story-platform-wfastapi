import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = "development"

    database_url: str = "postgresql+asyncpg://kurgu_admin:admin_password_123@localhost:5432/kurgu_db"

    jwt_secret: str = "dev-secret-change-me"
    jwt_expires_minutes: int = 60 * 24

    # Bos birakilirsa Google girisi kapali kalir (buton frontend'de gizlenir)
    google_oauth_client_id: str = ""

    # BYOK: uretim tarafinda SUNUCUDA HICBIR varsayilan YOK. base URL + model + anahtar
    # UCU DE her istekte kullanicidan gelir (X-LLM-Base-URL / X-LLM-Model / X-LLM-API-Key);
    # eksikse istek reddedilir. Sunucu uretim saglayicisi/modeli DAYATMAZ.

    # Embedding SUNUCU anahtariyla yapilir; kullanici anahtari asla kullanilmaz.
    # Olay-retrieval OpenAI uzayindadir (text-embedding-3-small, dimensions=768).
    # gemini alternatif olarak durur; provider degisimi = tam re-embed gerektirir.
    embedding_api_key: str = ""
    embedding_provider: str = "openai"
    # openai icin bos birak (SDK varsayilani api.openai.com kullanilir); gemini icin openai-uyumlu uc
    embedding_base_url: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 768
    embed_daily_limit: int = 300  # kullanici basina gunluk embed cagri kotasi

    llm_concurrency: int = 2
    llm_max_retries: int = 3

    cors_origins: str = "http://localhost:5173"

    # --- Depolama/kotuye kullanim sinirlari (ADIM 2) ---
    # Bolum metni: HEM yazarin manuel duzenlemesinde (schemas.py Field) HEM DE LLM
    # URETIMINDE (generation.py) uygulanir. Ikincisi kritik: BYOK'ta base_url kullanicinin
    # kendi sunucusu olabilir, yani "LLM yaniti" tamamen kullanicinin kontrolunde — Pydantic
    # bunu goremez, tavan olmadan sinirsiz metin doğrudan DB'ye yazilirdi.
    max_chapter_chars: int = 60_000
    max_story_description_chars: int = 2_000
    max_entity_description_chars: int = 2_000
    # Ozet alanlari: TASMA -> KIRPMA degil, uretim BASARISIZ sayilir (None doner). Sessizce
    # kirpilmis bir ozet ileri bolumlerin tek bilgi kaynagi olarak yanlis kalir; mevcut lazy
    # telafi (chapter.summary=None -> bir sonraki uretimde yeniden dene; arc summary=None ->
    # ensure_rollup o ark satirini hic yazmaz, prompt ham ozetlere duser) bunu zaten karsiliyor.
    max_chapter_summary_chars: int = 2_000
    max_arc_summary_chars: int = 6_000
    # Kullanici basina hikaye sayisi ve hikaye basina bolum/toplam-karakter tavani:
    # ham metin depolamayi hicbir sey sinirlamiyordu, import ozelligi gelmeden kapatilmali.
    max_stories_per_user: int = 50
    max_chapters_per_story: int = 1_000
    max_story_total_chars: int = 3_000_000


settings = Settings()

# --- Prod acilis denetimi: _check_embedding_dim (database.py) ile AYNI desen ---
# Sessiz yanlis yapilandirma bozuk calismaktan daha kotu; ENV=production'da bunlardan
# biri guvensizse ACILMAZ. ENV != production'da (lokal gelistirme) ENGELLENMEZ — dev-secret
# ile calismak mumkun kalir — ama uyari basilir, gozden kacmasin.
MIN_JWT_SECRET_BYTES = 32
_DEFAULT_JWT_SECRET = "dev-secret-change-me"
# Substring karsilastirmasi (tam URL esitligi degil): host/port/db adini degistirip
# sifreyi unutan biri de yakalansin.
_DEFAULT_DB_PASSWORD_MARKER = "admin_password_123"


def _production_config_problems(s: Settings) -> list[str]:
    """DIKKAT: donen mesajlarda hicbir sirrin kendisi (JWT_SECRET, DATABASE_URL icindeki
    sifre) YAZILMAZ — yalnizca uzunluk/varlik gibi sizdirmayan bilgiler."""
    problems: list[str] = []

    secret_bytes = len(s.jwt_secret.encode("utf-8"))
    if secret_bytes < MIN_JWT_SECRET_BYTES or s.jwt_secret == _DEFAULT_JWT_SECRET:
        problems.append(
            f"JWT_SECRET zayif ({secret_bytes} byte, en az {MIN_JWT_SECRET_BYTES} gerekli "
            "ve varsayilan degerde OLMAMALI). Uret: openssl rand -hex 32"
        )

    if not s.embedding_api_key:
        # Bu SESSIZCE basarisiz olur (bkz. ai/embeddings.py _get_client): her embed cagrisi
        # RuntimeError firlatir ama cagiran taraflar hepsi try/except icinde ("uretim
        # BLOKLANMAZ" deseni) — yani hikaye uretimi calisir gibi gorunur, retrieval/arama
        # sonsuza dek NULL embedding'lerle sessizce bos doner.
        problems.append(
            "EMBEDDING_API_KEY bos — embedding sessizce basarisiz olur, hicbir kayit "
            "vektorlenmez ve arama/hafiza calismiyor gibi gorunmeden bozuk kalir."
        )

    if _DEFAULT_DB_PASSWORD_MARKER in s.database_url:
        problems.append(
            "DATABASE_URL hala ornek/varsayilan gelistirme sifresini iceriyor. "
            "Guclu bir sifre uret (openssl rand -hex 16) ve hem POSTGRES_PASSWORD "
            "hem de DATABASE_URL'de kullan."
        )

    return problems


def validate_production_settings(s: Settings = settings) -> None:
    problems = _production_config_problems(s)
    if not problems:
        return
    if s.env == "production":
        raise RuntimeError(
            "Prod acilis reddedildi — asagidaki ayarlar guvensiz:\n- " + "\n- ".join(problems)
        )
    for problem in problems:
        logger.warning(
            "Guvensiz ayar (ENV=%s oldugu icin acilis ENGELLENMIYOR, ama prod'da ENGELLENIR): %s",
            s.env, problem,
        )
