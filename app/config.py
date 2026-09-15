from __future__ import annotations

from functools import lru_cache
from string import Formatter

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TRADING_", extra="ignore")

    database_url: str = "postgresql+psycopg://trading:trading@localhost:5432/trading"
    frontend_origins: str = "http://localhost:3000"
    public_base_url: str = "http://localhost:8000"
    sina_quotes_url: str = "https://hq.sinajs.cn/list={symbols}"

    admin_username: str = "admin"
    admin_password_hash: str = ""
    login_private_key_b64: SecretStr = SecretStr("")
    session_cookie: str = "trading_session"
    session_cookie_domain: str | None = None
    session_secure: bool = True
    session_hours: int = Field(default=2, ge=1, le=720)

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "trading-minio"
    minio_secret_key: str = "change-me"
    minio_bucket: str = "trading-attachments"
    minio_secure: bool = False

    @field_validator("frontend_origins", "public_base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("sina_quotes_url")
    @classmethod
    def validate_sina_quotes_url(cls, value: str) -> str:
        try:
            parts = list(Formatter().parse(value))
        except ValueError as error:
            raise ValueError("sina_quotes_url must contain exactly one {symbols} placeholder") from error
        fields = [field_name for _, field_name, _, _ in parts if field_name]
        if fields != ["symbols"] or any(
            field_name == "symbols" and (format_spec or conversion)
            for _, field_name, format_spec, conversion in parts
        ):
            raise ValueError("sina_quotes_url must contain exactly one {symbols} placeholder")
        return value

    @property
    def frontend_origin_list(self) -> list[str]:
        origins: list[str] = []
        for value in self.frontend_origins.split(","):
            origin = value.strip().rstrip("/")
            if origin and origin not in origins:
                origins.append(origin)
        return origins

    @field_validator("session_cookie_domain", mode="before")
    @classmethod
    def empty_domain_is_none(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("postgresql+psycopg_async://", "postgresql+psycopg://")


@lru_cache
def get_settings() -> Settings:
    return Settings()
