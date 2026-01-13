"""
Tidal integration API endpoints.

WARNING: This uses an unofficial API that is not supported by Tidal.
This integration is marked as BETA and may break at any time.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional

from app.api.deps import get_db, get_current_active_user
from app.models.user import User
from app.services.tidal_service import tidal_service

router = APIRouter()


# Request/Response schemas
class AuthStartResponse(BaseModel):
    auth_url: str
    device_code: str
    user_code: str
    expires_in: int
    interval: int


class AuthCompleteRequest(BaseModel):
    device_code: str


class AuthCompleteResponse(BaseModel):
    success: bool
    message: str


class CreatePlaylistRequest(BaseModel):
    name: str
    description: Optional[str] = "Created by MysteryMixClub"
    tidal_urls: List[str]


class CreatePlaylistResponse(BaseModel):
    success: bool
    playlist_id: str
    playlist_url: str
    track_count: int
    skipped_count: int


class TidalStatusResponse(BaseModel):
    connected: bool
    user_id: Optional[str] = None


@router.get("/status", response_model=TidalStatusResponse)
async def get_tidal_status(
    current_user: User = Depends(get_current_active_user),
):
    """Check if user has connected their Tidal account"""
    return TidalStatusResponse(
        connected=current_user.tidal_user_id is not None,
        user_id=current_user.tidal_user_id,
    )


@router.get("/auth-start", response_model=AuthStartResponse)
async def start_tidal_auth(
    current_user: User = Depends(get_current_active_user),
):
    """
    Start Tidal device authorization flow.
    Returns a URL for the user to visit to authorize the app.
    """
    try:
        auth_data = tidal_service.start_device_auth()
        return AuthStartResponse(**auth_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start Tidal auth: {str(e)}")


@router.post("/auth-complete", response_model=AuthCompleteResponse)
async def complete_tidal_auth(
    request: AuthCompleteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Complete Tidal authorization after user has authorized in browser.
    Polls Tidal to check if authorization is complete.
    """
    try:
        result = tidal_service.check_auth_status(request.device_code)

        if result is None:
            return AuthCompleteResponse(
                success=False,
                message="Authorization not yet complete. Please complete authorization in your browser.",
            )

        # Save the session data to the user
        current_user.tidal_user_id = result["user_id"]
        current_user.tidal_session_data = result["session_data"]
        db.commit()

        return AuthCompleteResponse(
            success=True,
            message="Successfully connected to Tidal!",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to complete Tidal auth: {str(e)}")


@router.delete("/disconnect")
async def disconnect_tidal(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Disconnect Tidal account"""
    current_user.tidal_user_id = None
    current_user.tidal_session_data = None
    db.commit()

    return {"success": True, "message": "Tidal account disconnected"}


@router.post("/playlist", response_model=CreatePlaylistResponse)
async def create_tidal_playlist(
    request: CreatePlaylistRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """
    Create a Tidal playlist from a list of Tidal URLs.

    WARNING: This uses an unofficial API and may fail unexpectedly.
    """
    if not current_user.tidal_session_data:
        raise HTTPException(
            status_code=400,
            detail="Tidal account not connected. Please connect your Tidal account first.",
        )

    # Extract track IDs from URLs
    track_ids = []
    skipped = 0
    for url in request.tidal_urls:
        track_id = tidal_service.extract_track_id(url)
        if track_id:
            track_ids.append(track_id)
        else:
            skipped += 1

    if not track_ids:
        raise HTTPException(
            status_code=400,
            detail="No valid Tidal track URLs provided",
        )

    try:
        result = tidal_service.create_playlist(
            session_data=current_user.tidal_session_data,
            name=request.name,
            description=request.description or "Created by MysteryMixClub",
            track_ids=track_ids,
        )

        return CreatePlaylistResponse(
            success=True,
            playlist_id=result["playlist_id"],
            playlist_url=result["playlist_url"],
            track_count=result["track_count"],
            skipped_count=skipped,
        )
    except ValueError as e:
        # Session expired or invalid
        current_user.tidal_user_id = None
        current_user.tidal_session_data = None
        db.commit()
        raise HTTPException(
            status_code=401,
            detail="Tidal session expired. Please reconnect your Tidal account.",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create Tidal playlist: {str(e)}",
        )
