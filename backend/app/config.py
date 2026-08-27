from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/onlinedb"
    db_schema: str = "metag"

    jwt_secret: str = "change-me-to-a-long-random-value"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 120

    upload_dir: str = "./uploads"

    allow_external_knowledge: bool = False
    embedding_dim: int = 384  # sentence-transformers/all-MiniLM-L6-v2

    log_level: str = "INFO"


settings = Settings()
