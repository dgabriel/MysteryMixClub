"""MYS-38 — Settings must normalize DATABASE_URL to the asyncpg driver.

`app/db/session.py` and `migrations/env.py` both build async engines that
REQUIRE a `postgresql+asyncpg://` scheme, but DigitalOcean's managed Postgres
emits a bare `postgresql://...` (and sometimes the short `postgres://`) URL.

The fix adds a validator on `Settings.database_url` that coerces only bare
postgres schemes to `postgresql+asyncpg://`, leaving everything else
(empty values, already-asyncpg URLs, other drivers) untouched.

These tests are TDD-first and are expected to FAIL on the bare-scheme
coercion cases until that validator is implemented. Settings are constructed
directly with an explicit `database_url` kwarg (and `_env_file=None`) so the
real .env / env vars never leak into the assertions.
"""

from app.config import Settings


def _make(url: str) -> Settings:
    # Explicit kwarg overrides env; `_env_file=None` stops pydantic-settings
    # from reading a local .env during direct construction.
    return Settings(database_url=url, _env_file=None)


def test_bare_postgresql_scheme_is_coerced_to_asyncpg() -> None:
    settings = _make("postgresql://mmc:mmc@localhost:5432/db")
    assert settings.database_url == "postgresql+asyncpg://mmc:mmc@localhost:5432/db"


def test_short_postgres_scheme_is_coerced_to_asyncpg() -> None:
    settings = _make("postgres://mmc:mmc@localhost:5432/db")
    assert settings.database_url == "postgresql+asyncpg://mmc:mmc@localhost:5432/db"


def test_already_asyncpg_scheme_is_unchanged() -> None:
    url = "postgresql+asyncpg://mmc:mmc@localhost:5432/db"
    settings = _make(url)
    assert settings.database_url == url


def test_query_string_is_preserved_when_scheme_is_coerced() -> None:
    settings = _make("postgresql://u:p@host:5432/db?sslmode=require")
    result = settings.database_url
    assert result.startswith("postgresql+asyncpg://")
    # Host, path, and query must survive the scheme rewrite intact.
    assert "u:p@host:5432/db" in result
    assert "sslmode=require" in result
    assert result == "postgresql+asyncpg://u:p@host:5432/db?sslmode=require"


def test_empty_default_stays_empty() -> None:
    settings = _make("")
    assert settings.database_url == ""


def test_other_driver_scheme_is_not_rewritten() -> None:
    # Only bare `postgresql://` / `postgres://` are coerced. An explicit
    # non-asyncpg driver must be left exactly as provided.
    url = "postgresql+psycopg2://mmc:mmc@localhost:5432/db"
    settings = _make(url)
    assert settings.database_url == url
