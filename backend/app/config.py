from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(default="")
    secret_key: str = Field(default="")
    resend_api_key: str = Field(default="")
    youtube_api_key: str = Field(default="")
    # Spotify app credentials for per-user OAuth playlist creation (MYS-83).
    # Server-side only; the client secret must never reach the browser.
    spotify_client_id: str = Field(default="")
    spotify_client_secret: str = Field(default="")
    # Where Spotify redirects after consent. Must match a redirect URI registered
    # on the Spotify app dashboard exactly, per environment.
    spotify_redirect_uri: str = Field(default="")
    allowed_origins: str = Field(default="")
    environment: Literal["development", "staging", "production"] = "development"
    app_base_url: str = Field(default="https://mysterymixclub.com")
    # Public base URL of the API itself, used to build links that must hit the
    # backend directly (e.g. the one-click email-unsubscribe endpoint). Falls
    # back to app_base_url when unset (same-host deployments that proxy /api).
    api_base_url: str = Field(default="")
    # Overrides the From address on all outbound email when set. Leave empty in
    # staging/prod to use the per-purpose defaults (login@ / notifications@) on
    # the verified domain. Locally, set to a sender Resend will accept without a
    # verified domain, e.g. onboarding@resend.dev (delivers only to your own
    # Resend account email until mysterymixclub.com is verified).
    email_from: str = Field(default="")
    # Comma-separated platform-admin identity (MYS-128): these emails may eject
    # bad actors via the /admin endpoints and see is_platform_admin on /users/me.
    # NOT a login gate — sign-in is open to existing users + valid invite links.
    # Normalized via seed_admin_email_set.
    seed_admin_emails: str = Field(default="")
    # Hard cap on total (non-deleted) accounts for the controlled beta (MYS-127);
    # new sign-ups are blocked at the cap, existing users unaffected. 0 = unlimited.
    max_users: int = Field(default=1500)
    # ----------------------------------------------------------------------- #
    # Feature flags
    #
    # App-level toggles, flipped per-environment via env vars (no redeploy).
    # Conventions: name the boolean flag clearly, default it OFF (safe in prod),
    # keep any companion config beside it, and document every flag in
    # docs/feature-flags.md (+ .env.example, + the DO app specs if used in a
    # deployed env). Add new flags below this banner.
    # ----------------------------------------------------------------------- #

    # Staging email sink: when on, every outbound email is redirected to
    # email_test_recipient instead of the real recipient — lets staging be
    # flipped between real delivery and a test inbox. If on but no recipient is
    # set, email is suppressed (fail-safe). See docs/feature-flags.md.
    email_redirect_to_test: bool = Field(default=False)
    email_test_recipient: str = Field(default="")

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
    def seed_admin_email_set(self) -> set[str]:
        return {
            email.strip().lower() for email in self.seed_admin_emails.split(",") if email.strip()
        }

    @property
    def secure_cookies(self) -> bool:
        """Set the Secure flag on auth cookies in every HTTPS environment.
        Local development is the only environment served over plain HTTP."""
        return self.environment != "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
