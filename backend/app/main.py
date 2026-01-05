from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1 import auth, leagues, rounds, submissions, votes

app = FastAPI(
    title="MysteryMixClub API",
    description="Music discovery league platform API",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(leagues.router, prefix="/api/v1/leagues", tags=["leagues"])
app.include_router(rounds.router, prefix="/api/v1/rounds", tags=["rounds"])
app.include_router(submissions.router, prefix="/api/v1/submissions", tags=["submissions"])
app.include_router(votes.router, prefix="/api/v1/votes", tags=["votes"])


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to MysteryMixClub API",
        "docs": "/docs",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {"status": "healthy"}
