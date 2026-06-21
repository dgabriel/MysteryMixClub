from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(default="")
    secret_key: str = Field(default="")
    resend_api_key: str = Field(default="")
    odesli_api_key: str = Field(default="")
    youtube_api_key: str = Field(default="")
    allowed_origins: str = Field(default="")
    environment: Literal["development", "staging", "production"] = "development"
    app_base_url: str = Field(default="https://mysterymixclub.com")

    @field_validator("database_url")
    @classmethod
    def _normalize_async_driver(cls, value: str) -> str:
        # DO managed Postgres emits a bare postgresql:// (or postgres://) URL, but
        # the app and alembic use async engines that require the +asyncpg driver.
        # Prefix swap only; the rest (userinfo/host/port/path/query) is preserved
        # verbatim. Note: asyncpg ignores libpq's sslmode= param; rewriting it to
        # asyncpg's ssl= form is tracked separately and intentionally not done here.
        if value.startswith("postgresql+"):
            return value
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://") :]
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://") :]
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def secure_cookies(self) -> bool:
        """Set the Secure flag on auth cookies in every HTTPS environment.
        Local development is the only environment served over plain HTTP."""
        return self.environment != "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
