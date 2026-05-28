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

from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.services.email import EmailSender, get_email_sender

# Import models so they register on Base.metadata before create_all.
from app.models import MagicLinkToken, Session, User  # noqa: F401

TEST_ASYNC_DATABASE_URL = "postgresql+asyncpg://mmc:mmc@localhost:5432/mysterymixclub_test"

# Tables truncated before and after each test for isolation. ``sessions``
# references ``users``; CASCADE on the TRUNCATE handles the FK, and
# magic_link_tokens is independent. Listed together so one statement covers all.
_TRUNCATE_TABLES = "magic_link_tokens, sessions, users"


@dataclass
class SpyEmailSender:
    """Records every magic-link send so tests can assert on arguments."""

    calls: list[tuple[str, str]] = field(default_factory=list)

    def send_magic_link(self, email: str, link: str) -> None:
        self.calls.append((email, link))

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


@pytest_asyncio.fixture
async def client(session_factory, email_spy: SpyEmailSender) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient over the ASGI app with get_db / get_email_sender overridden."""
    app = create_app()

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    def override_get_email_sender() -> EmailSender:
        return email_spy

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_sender] = override_get_email_sender

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
