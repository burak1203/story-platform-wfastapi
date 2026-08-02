from pydantic_settings import BaseSettings, SettingsConfigDict


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
