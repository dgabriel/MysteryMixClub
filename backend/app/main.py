import logging
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    auth,
    health,
    invites,
    leagues,
    notes,
    rounds,
    submissions,
    users,
    votes,
)
from app.config import get_settings
from app.routers import songs


def _configure_dev_logging() -> None:
    """Surface ``app.*`` logs on stdout in development.

    Without this, uvicorn's default logging config swallows INFO records from
    the application loggers, so the console magic-link sender's output is never
    shown. Magic-link tokens are stored hashed, so that log line is the only
    way to obtain a sign-in link locally. Idempotent and dev-only.
    """
    logger = logging.getLogger("app")
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.environment == "development":
        _configure_dev_logging()
    app = FastAPI(title="MysteryMixClub API", version="0.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(leagues.router, prefix="/api/v1")
    app.include_router(invites.router, prefix="/api/v1")
    app.include_router(rounds.router, prefix="/api/v1")
    app.include_router(submissions.router, prefix="/api/v1")
    app.include_router(votes.router, prefix="/api/v1")
    app.include_router(notes.router, prefix="/api/v1")
    app.include_router(songs.router, prefix="/api/v1")

    return app


app = create_app()
