"""Shared fixtures for the backend test suite.

Tests run against a dedicated test database (``mysterymixclub_test``) so they
never touch dev data. The app's ``get_db`` and ``get_email_sender`` dependencies
are overridden so requests use a session bound to a test engine created inside
the same event loop as the HTTP client. This avoids the asyncpg
"attached to a different loop" failure the developer hit with TestClient.

pytest-asyncio (auto mode) runs each test in its own event loop, and asyncpg
pins connections to the loop they were created in. So the engine is
function-scoped: a fresh engine is built inside each test's loop. The schema is
created once per session via a synchronous engine so we don't pay create_all on
every test or straddle event loops.
"""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.services.email import EmailSender, get_email_sender
from app.services.youtube_resolver import get_youtube_resolver

# Import models so they register on Base.metadata before create_all.
from app.models import MagicLinkToken, Session, User  # noqa: F401

TEST_ASYNC_DATABASE_URL = "postgresql+asyncpg://mmc:mmc@localhost:5432/mysterymixclub_test"

# Tables truncated before and after each test for isolation. ``sessions``
# references ``users``; CASCADE on the TRUNCATE handles the FK, and
# magic_link_tokens is independent. Listed together so one statement covers all.
_TRUNCATE_TABLES = (
    "magic_link_tokens, sessions, spotify_connections, invites, submissions, "
    "rounds, leagues, league_members, users"
)


@dataclass
class SpyEmailSender:
    """Records every send so tests can assert on arguments."""

    calls: list[tuple[str, str]] = field(default_factory=list)
    # General notification sends (MYS-109): (email, subject, html).
    sends: list[tuple[str, str, str]] = field(default_factory=list)
    # Extra MIME headers per send (e.g. List-Unsubscribe), parallel to `sends`.
    sent_headers: list[dict[str, str] | None] = field(default_factory=list)

    def send_magic_link(self, email: str, link: str) -> None:
        self.calls.append((email, link))

    def send(
        self, email: str, subject: str, html: str, headers: dict[str, str] | None = None
    ) -> None:
        self.sends.append((email, subject, html))
        self.sent_headers.append(headers)

    @property
    def call_count(self) -> int:
        return len(self.calls)


@pytest.fixture(scope="session", autouse=True)
def _schema() -> None:
    """Build the schema once per session in a throwaway event loop.

    Runs and fully disposes its own engine before any per-test loop starts, so
    no asyncpg connection is ever shared across loops.
    """

    async def _create() -> None:
        eng = create_async_engine(TEST_ASYNC_DATABASE_URL, future=True)
        async with eng.begin() as conn:
            # Drop first so schema changes (new columns, constraints, indexes)
            # are always applied — create_all silently skips existing tables.
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        await eng.dispose()

    asyncio.run(_create())


@pytest_asyncio.fixture
async def engine(_schema) -> AsyncGenerator:
    """Function-scoped async engine, created inside the running test's loop."""
    eng = create_async_engine(TEST_ASYNC_DATABASE_URL, future=True)
    # Clean slate before the test.
    async with eng.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {_TRUNCATE_TABLES} CASCADE"))
    yield eng
    async with eng.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {_TRUNCATE_TABLES} CASCADE"))
    await eng.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """A standalone session for tests to read/assert DB state directly."""
    async with session_factory() as session:
        yield session


@pytest.fixture
def email_spy() -> SpyEmailSender:
    return SpyEmailSender()


@pytest.fixture
def seed_admin_emails() -> str:
    """Comma-separated platform-admin identity injected into the ``client``
    fixture's settings (MYS-128).

    Defaults to empty. This is NOT a login gate in v2 — it only controls
    ``is_platform_admin`` on /users/me and access to the /admin endpoints. Admin
    tests override it to make a caller a platform admin."""
    return ""


@pytest.fixture
def max_users() -> int:
    """Hard cap on non-deleted accounts injected into the ``client`` fixture's
    settings (MYS-127). Defaults to 0 (unlimited) so ordinary tests aren't
    blocked by the beta cap; the cap test overrides it to a small number."""
    return 0


class _OfflineYouTubeResolver:
    """Default resolver for the shared client fixture: never hits the real
    YouTube Data API. Tests that need resolution behaviour override this with
    their own fake; everyone else gets a safe no-op (always None)."""

    async def video_id_for(self, title: str, artist: str | None = None) -> str | None:
        return None


@pytest_asyncio.fixture
async def client(
    session_factory, email_spy: SpyEmailSender, seed_admin_emails: str, max_users: int
) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient over the ASGI app with get_db / get_email_sender overridden."""
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    def override_get_email_sender() -> EmailSender:
        return email_spy

    # Inject settings so tests can control platform-admin identity
    # (``seed_admin_emails``, MYS-128) and the beta sign-up cap (``max_users``,
    # MYS-127). environment stays development (the suite's default), matching the
    # global lru_cached settings.
    test_settings = Settings(
        environment="development",
        seed_admin_emails=seed_admin_emails,
        max_users=max_users,
    )

    def override_get_settings() -> Settings:
        return test_settings

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_sender] = override_get_email_sender
    app.dependency_overrides[get_settings] = override_get_settings
    # Keep the whole suite offline by default — no live YouTube Data API calls.
    app.dependency_overrides[get_youtube_resolver] = lambda: _OfflineYouTubeResolver()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
