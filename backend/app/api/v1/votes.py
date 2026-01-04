from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from app.api import deps
from app.models.user import User
from app.schemas.vote import VoteCreate, VoteUpdate, UserVotesResponse
from app.services import vote_service, round_service

router = APIRouter()


@router.post("/", response_model=UserVotesResponse, status_code=status.HTTP_201_CREATED)
def cast_votes(
    vote_data: VoteCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Cast votes for a round (ranked 1-3 submissions)"""
    votes = vote_service.cast_votes(db, vote_data, current_user.id)

    # Check if all members have voted - if so, round is ready to complete
    # Note: Admin still needs to manually complete or it will auto-complete at deadline
    if vote_service.check_voting_complete(db, vote_data.round_id):
        # Could auto-complete here, but let's let admin do it or wait for deadline
        pass

    return UserVotesResponse(
        round_id=vote_data.round_id,
        ranked_submissions=vote_data.ranked_submissions,
        voted_at=votes[0].voted_at
    )


@router.get("/round/{round_id}/my-votes", response_model=Optional[UserVotesResponse])
def get_my_votes(
    round_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Get current user's votes for a round"""
    return vote_service.get_user_votes(db, round_id, current_user.id)


@router.put("/round/{round_id}", response_model=UserVotesResponse)
def update_votes(
    round_id: int,
    vote_data: VoteUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Update votes for a round"""
    votes = vote_service.update_votes(db, round_id, vote_data, current_user.id)

    # Check if all members have voted
    if vote_service.check_voting_complete(db, round_id):
        # Could auto-complete here, but let's let admin do it or wait for deadline
        pass

    return UserVotesResponse(
        round_id=round_id,
        ranked_submissions=vote_data.ranked_submissions,
        voted_at=votes[0].voted_at
    )


@router.delete("/round/{round_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_votes(
    round_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Delete votes for a round"""
    vote_service.delete_votes(db, round_id, current_user.id)
    return None
