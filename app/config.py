from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    DB_PATH: str = "/data/db/app.db"

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Paths
    DATA_DIR: str = "/data"
    CURRENT_SECTION_PATH: str = "/data/projects/current"

    # Master user
    MASTER_EMAIL: str = "admin@axidia.com.br"
    MASTER_PASSWORD: str = "admin"

    # Auth
    SECRET_KEY: str = "change-me-in-production-use-a-real-secret"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24h
    ALGORITHM: str = "HS256"

    # Registration
    REGISTRATION_MODE: str = "invite_only"

    # Limits
    MAX_PROJECT_BYTES: int = 21_474_836_480  # 20 GB
    WORKER_CONCURRENCY: int = 1
    DEFAULT_PRESET: str = "balanced"

    # App
    BASE_URL: str = "http://localhost:8000"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
