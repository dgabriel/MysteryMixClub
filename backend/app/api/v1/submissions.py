from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.api import deps
from app.models.user import User
from app.schemas.round import SubmissionCreate, SubmissionUpdate, SubmissionResponse
from app.services import submission_service, round_service

router = APIRouter()


@router.post("/", response_model=SubmissionResponse, status_code=status.HTTP_201_CREATED)
def create_submission(
    submission_data: SubmissionCreate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Submit a song for a round"""
    submission = submission_service.create_submission(db, submission_data, current_user.id)

    # Check if all members have submitted - if so, auto-progress to voting
    if round_service.check_submission_complete(db, submission_data.round_id):
        round_service.progress_to_voting(db, submission_data.round_id)

    return submission


@router.get("/round/{round_id}/my-submission", response_model=SubmissionResponse)
def get_my_submission(
    round_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Get current user's submission for a round"""
    submission = submission_service.get_user_submission(db, round_id, current_user.id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No submission found for this round"
        )
    return submission


@router.put("/{submission_id}", response_model=SubmissionResponse)
def update_submission(
    submission_id: int,
    submission_data: SubmissionUpdate,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Update a submission (before deadline)"""
    return submission_service.update_submission(db, submission_id, submission_data, current_user.id)


@router.delete("/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission(
    submission_id: int,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """Delete a submission (before deadline)"""
    submission_service.delete_submission(db, submission_id, current_user.id)
    return None
