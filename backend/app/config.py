from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://kurgu_admin:admin_password_123@localhost:5432/kurgu_db"

    jwt_secret: str = "dev-secret-change-me"
    jwt_expires_minutes: int = 60 * 24

    llm_api_key: str = ""
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_story_model: str = "gemini-3.5-flash"
    llm_util_model: str = "gemini-3.5-flash"

    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768

    llm_concurrency: int = 2
    llm_max_retries: int = 3

    cors_origins: str = "http://localhost:5173"


settings = Settings()
