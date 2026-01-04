from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.api import deps
from app.models.user import User
from app.schemas.round import RoundCreate, RoundUpdate, RoundResponse, RoundDetailResponse
from app.services import round_service, vote_service

router = APIRouter()


@router.post("/", response_model=RoundResponse, status_code=status.HTTP_201_CREATED)
def create_round(
    round_data: RoundCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Create a new round (admin only)"""
    return round_service.create_round(db, round_data, current_user.id)


@router.get("/league/{league_id}", response_model=List[RoundResponse])
def get_league_rounds(
    league_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Get all rounds for a league"""
    from app.services import league_service
    rounds = round_service.get_league_rounds(db, league_id)

    # Add submission count and user_has_submitted for each round
    result = []
    for round_obj in rounds:
        submissions = round_service.get_round_submissions(db, round_obj.id)
        round_dict = {
            "id": round_obj.id,
            "league_id": round_obj.league_id,
            "theme": round_obj.theme,
            "description": round_obj.description,
            "order": round_obj.order,
            "status": round_obj.status,
            "started_at": round_obj.started_at,
            "submission_deadline": round_obj.submission_deadline,
            "voting_started_at": round_obj.voting_started_at,
            "voting_deadline": round_obj.voting_deadline,
            "completed_at": round_obj.completed_at,
            "created_at": round_obj.created_at,
            "submission_count": len(submissions),
            "user_has_submitted": round_service.user_has_submitted(db, round_obj.id, current_user.id),
            "is_admin": league_service.is_league_admin(db, round_obj.league_id, current_user.id)
        }
        result.append(round_dict)

    return result


@router.get("/{round_id}", response_model=RoundDetailResponse)
def get_round(
    round_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Get round details with submissions"""
    from app.services import league_service

    round_obj = round_service.get_round_by_id(db, round_id)
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Round not found"
        )

    submissions = round_service.get_round_submissions(db, round_id)

    # Build response
    round_dict = {
        "id": round_obj.id,
        "league_id": round_obj.league_id,
        "theme": round_obj.theme,
        "description": round_obj.description,
        "order": round_obj.order,
        "status": round_obj.status,
        "started_at": round_obj.started_at,
        "submission_deadline": round_obj.submission_deadline,
        "voting_started_at": round_obj.voting_started_at,
        "voting_deadline": round_obj.voting_deadline,
        "completed_at": round_obj.completed_at,
        "created_at": round_obj.created_at,
        "submission_count": len(submissions),
        "user_has_submitted": round_service.user_has_submitted(db, round_id, current_user.id),
        "is_admin": league_service.is_league_admin(db, round_obj.league_id, current_user.id),
        "submissions": []
    }

    # Add submissions (anonymize if in voting phase)
    from app.models.round import RoundStatus
    for sub in submissions:
        sub_dict = {
            "id": sub.id,
            "round_id": sub.round_id,
            "user_id": sub.user_id,
            "song_title": sub.song_title,
            "artist_name": sub.artist_name,
            "album_name": sub.album_name,
            "songlink_url": sub.songlink_url,
            "spotify_url": sub.spotify_url,
            "apple_music_url": sub.apple_music_url,
            "youtube_url": sub.youtube_url,
            "artwork_url": sub.artwork_url,
            "submitted_at": sub.submitted_at,
            "user_name": None  # Will be shown after voting
        }

        # Show user name only if round is completed
        if round_obj.status == RoundStatus.COMPLETED:
            sub_dict["user_name"] = sub.user.name

        round_dict["submissions"].append(sub_dict)

    return round_dict


@router.put("/{round_id}", response_model=RoundResponse)
def update_round(
    round_id: int,
    round_data: RoundUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Update a round (admin only)"""
    return round_service.update_round(db, round_id, round_data, current_user.id)


@router.delete("/{round_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_round(
    round_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Delete a round (admin only) - can only delete pending rounds"""
    round_service.delete_round(db, round_id, current_user.id)
    return None


@router.post("/{round_id}/start", response_model=RoundResponse)
def start_round(
    round_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Start a pending round (admin only) - calculates and sets deadlines"""
    round_obj = round_service.start_round(db, round_id, current_user.id)

    # Build response
    submissions = round_service.get_round_submissions(db, round_id)
    from app.services import league_service

    return {
        "id": round_obj.id,
        "league_id": round_obj.league_id,
        "theme": round_obj.theme,
        "description": round_obj.description,
        "order": round_obj.order,
        "status": round_obj.status,
        "started_at": round_obj.started_at,
        "submission_deadline": round_obj.submission_deadline,
        "voting_started_at": round_obj.voting_started_at,
        "voting_deadline": round_obj.voting_deadline,
        "completed_at": round_obj.completed_at,
        "created_at": round_obj.created_at,
        "submission_count": len(submissions),
        "user_has_submitted": round_service.user_has_submitted(db, round_id, current_user.id),
        "is_admin": league_service.is_league_admin(db, round_obj.league_id, current_user.id)
    }


@router.post("/{round_id}/complete", response_model=RoundResponse)
def complete_round(
    round_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Complete an active round (admin only) - auto-starts next pending round"""
    round_obj = round_service.complete_round(db, round_id, current_user.id)

    # Build response
    submissions = round_service.get_round_submissions(db, round_id)
    from app.services import league_service

    return {
        "id": round_obj.id,
        "league_id": round_obj.league_id,
        "theme": round_obj.theme,
        "description": round_obj.description,
        "order": round_obj.order,
        "status": round_obj.status,
        "started_at": round_obj.started_at,
        "submission_deadline": round_obj.submission_deadline,
        "voting_started_at": round_obj.voting_started_at,
        "voting_deadline": round_obj.voting_deadline,
        "completed_at": round_obj.completed_at,
        "created_at": round_obj.created_at,
        "submission_count": len(submissions),
        "user_has_submitted": round_service.user_has_submitted(db, round_id, current_user.id),
        "is_admin": league_service.is_league_admin(db, round_obj.league_id, current_user.id)
    }


@router.post("/league/{league_id}/reorder", response_model=List[RoundResponse])
def reorder_rounds(
    league_id: int,
    round_orders: List[dict],
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Reorder pending rounds (admin only) - format: [{"id": 1, "order": 0}, {"id": 2, "order": 1}]"""
    rounds = round_service.reorder_rounds(db, league_id, round_orders, current_user.id)

    # Build responses
    from app.services import league_service
    result = []
    for round_obj in rounds:
        submissions = round_service.get_round_submissions(db, round_obj.id)
        round_dict = {
            "id": round_obj.id,
            "league_id": round_obj.league_id,
            "theme": round_obj.theme,
            "description": round_obj.description,
            "order": round_obj.order,
            "status": round_obj.status,
            "started_at": round_obj.started_at,
            "submission_deadline": round_obj.submission_deadline,
            "voting_started_at": round_obj.voting_started_at,
            "voting_deadline": round_obj.voting_deadline,
            "completed_at": round_obj.completed_at,
            "created_at": round_obj.created_at,
            "submission_count": len(submissions),
            "user_has_submitted": round_service.user_has_submitted(db, round_obj.id, current_user.id),
            "is_admin": league_service.is_league_admin(db, round_obj.league_id, current_user.id)
        }
        result.append(round_dict)

    return result


@router.get("/{round_id}/results")
def get_round_results(
    round_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Get voting results for a completed round"""
    return vote_service.calculate_results(db, round_id)
