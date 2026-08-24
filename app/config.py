from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TRADING_", extra="ignore")

    database_url: str = "postgresql+psycopg://trading:trading@localhost:5432/trading"
    frontend_origin: str = "http://localhost:3000"
    public_base_url: str = "http://localhost:8000"

    admin_username: str = "admin"
    admin_password_hash: str = ""
    session_cookie: str = "trading_session"
    session_secure: bool = True
    session_days: int = Field(default=7, ge=1, le=90)

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "trading-minio"
    minio_secret_key: str = "change-me"
    minio_bucket: str = "trading-attachments"
    minio_secure: bool = False

    @field_validator("frontend_origin", "public_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("postgresql+psycopg_async://", "postgresql+psycopg://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
