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

Per-test isolation (ADR 0005): each test gets one real connection
(``connection``) with an outer transaction that is always rolled back at
teardown. Every ``Session`` in the test — ``db_session``, and each request the
``client`` fixture's ``get_db`` override serves — binds to that *same*
connection via a ``SAVEPOINT`` (``join_transaction_mode="create_savepoint"``),
so a test's own ``session.commit()`` calls only release the savepoint, never
the outer transaction. Rolling back the outer transaction at teardown undoes
everything the test did without ever fsync'ing a durable write, replacing the
old TRUNCATE-before/after fixture (see the ADR for the profiling that
motivated this).

This does mean every ``Session`` in a given test shares one physical
connection, so it cannot support genuine cross-connection concurrency (e.g.
racing two requests for a ``with_for_update()`` row lock — two coroutines
can't both have an operation in flight on the same asyncpg connection at
once, and even if they could, they wouldn't actually contend for a lock they
both "hold"). Tests that need that use the ``real_session_factory`` /
``real_client`` / ``real_db_session`` fixtures below instead, which bind to
the engine's connection pool directly (genuinely separate real connections,
real commits) and pay back a small, test-scoped TRUNCATE cost to clean up
after themselves.
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

# Tables truncated before and after each test that opts into
# ``real_session_factory`` (ADR 0005) — the rest of the suite is isolated by
# rolling back the test's outer transaction instead. ``sessions`` references
# ``users``; CASCADE on the TRUNCATE handles the FK, and magic_link_tokens is
# independent. Listed together so one statement covers all.
_TRUNCATE_TABLES = (
    "magic_link_tokens, password_reset_tokens, login_attempts, sessions, "
    "spotify_connections, invites, submissions, mixes, clubs, club_members, users"
)


@dataclass
class SpyEmailSender:
    """Records every send so tests can assert on arguments."""

    calls: list[tuple[str, str]] = field(default_factory=list)
    # Password-reset sends (ADR 0007): (email, link).
    reset_calls: list[tuple[str, str]] = field(default_factory=list)
    # General notification sends (MYS-109): (email, subject, html).
    sends: list[tuple[str, str, str]] = field(default_factory=list)
    # Extra MIME headers per send (e.g. List-Unsubscribe), parallel to `sends`.
    sent_headers: list[dict[str, str] | None] = field(default_factory=list)

    def send_magic_link(self, email: str, link: str) -> None:
        self.calls.append((email, link))

    def send_password_reset(self, email: str, link: str) -> None:
        self.reset_calls.append((email, link))

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
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def connection(engine) -> AsyncGenerator:
    """One real connection per test, wrapped in an outer transaction that's
    always rolled back at teardown (ADR 0005) — the test's isolation
    boundary. ``try/finally`` guarantees the rollback runs even if the test
    itself raises."""
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()


@pytest.fixture
def session_factory(connection):
    """Sessions bound to the test's single transactional ``connection``
    (ADR 0005) via a SAVEPOINT, so every Session in a test — ``db_session``,
    each ``client`` request — shares one rollback boundary. Not suitable for
    tests that need genuine cross-connection concurrency; see
    ``real_session_factory``."""
    return async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncGenerator[AsyncSession, None]:
    """A standalone session for tests to read/assert DB state directly."""
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def real_session_factory(engine) -> AsyncGenerator:
    """Sessions bound directly to the engine's connection pool — genuinely
    separate real connections per ``Session``, each able to commit
    independently.

    For the handful of tests that exercise real cross-connection concurrency
    (``with_for_update()`` row-locking races via ``asyncio.gather``): under
    the default ``session_factory`` fixture every Session in a test shares
    one connection/transaction (ADR 0005), so two "concurrent" requests can
    never actually contend for a row lock. This fixture keeps those tests on
    real, separate connections (the pre-ADR-0005 behavior) so the lock is
    genuinely contended, at the cost of its own TRUNCATE-based cleanup below
    — which is exactly why this is opt-in rather than the suite default."""
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {_TRUNCATE_TABLES} CASCADE"))
    try:
        yield async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE TABLE {_TRUNCATE_TABLES} CASCADE"))


@pytest_asyncio.fixture
async def real_db_session(real_session_factory) -> AsyncGenerator[AsyncSession, None]:
    """Like ``db_session``, but bound to a genuinely separate real connection
    (``real_session_factory``) rather than the test's rollback-scoped
    ``connection``. Pair with ``real_client`` for tests that need real
    cross-connection concurrency."""
    async with real_session_factory() as session:
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


@pytest.fixture
def waitlist_enabled() -> bool:
    """The waitlist flag (MYS-215) injected into the ``client`` fixture's
    settings. Defaults to False, matching the flag's production-safe
    default; waitlist tests override it to True."""
    return False


@pytest.fixture
def resend_webhook_secret() -> str:
    """Resend Inbound's Svix signing secret (MYS-242) injected into the
    ``client`` fixture's settings. Defaults to empty (route 503s); the
    webhook test module overrides it to exercise real signature
    verification."""
    return ""


class _OfflineYouTubeResolver:
    """Default resolver for the shared client fixture: never hits the real
    YouTube Data API. Tests that need resolution behaviour override this with
    their own fake; everyone else gets a safe no-op (always None)."""

    async def video_id_for(self, title: str, artist: str | None = None) -> str | None:
        return None


def _build_test_app(
    session_factory,
    email_spy: SpyEmailSender,
    seed_admin_emails: str,
    max_users: int,
    waitlist_enabled: bool,
    resend_webhook_secret: str,
):
    """Build a fresh ASGI app with the standard test dependency overrides,
    binding ``get_db`` to whichever ``session_factory`` the caller passes in.
    Shared by ``client`` (the ADR 0005 rollback-scoped ``session_factory``)
    and ``real_client`` (the real-connection ``real_session_factory`` used by
    cross-connection concurrency tests) so the two stay in lockstep."""
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
        waitlist_enabled=waitlist_enabled,
        resend_webhook_secret=resend_webhook_secret,
    )

    def override_get_settings() -> Settings:
        return test_settings

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_sender] = override_get_email_sender
    app.dependency_overrides[get_settings] = override_get_settings
    # Keep the whole suite offline by default — no live YouTube Data API calls.
    app.dependency_overrides[get_youtube_resolver] = lambda: _OfflineYouTubeResolver()
    return app


@pytest_asyncio.fixture
async def client(
    session_factory,
    email_spy: SpyEmailSender,
    seed_admin_emails: str,
    max_users: int,
    waitlist_enabled: bool,
    resend_webhook_secret: str,
) -> AsyncGenerator[AsyncClient, None]:
    """AsyncClient over the ASGI app with get_db / get_email_sender
    overridden. Bound to the test's single rollback-scoped ``connection``
    (ADR 0005) via ``session_factory`` — every request in a test shares that
    one connection, so a test's own writes are visible to ``db_session``
    assertions without a real commit. Not suitable for tests that need
    genuine cross-connection concurrency; use ``real_client`` for that."""
    app = _build_test_app(
        session_factory,
        email_spy,
        seed_admin_emails,
        max_users,
        waitlist_enabled,
        resend_webhook_secret,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def real_client(
    real_session_factory,
    email_spy: SpyEmailSender,
    seed_admin_emails: str,
    max_users: int,
    waitlist_enabled: bool,
    resend_webhook_secret: str,
) -> AsyncGenerator[AsyncClient, None]:
    """Like ``client``, but each request gets a genuinely separate real
    connection (``real_session_factory``) instead of sharing the test's
    single rollback-scoped connection. Only for tests that exercise real
    cross-connection concurrency — e.g. ``with_for_update()`` row-locking
    races via ``asyncio.gather`` (ADR 0005) — where every "concurrent"
    request must be able to actually contend for a lock, not serialize on one
    shared asyncpg connection."""
    app = _build_test_app(
        real_session_factory,
        email_spy,
        seed_admin_emails,
        max_users,
        waitlist_enabled,
        resend_webhook_secret,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
