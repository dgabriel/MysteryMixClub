from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.round import Round, Submission, RoundStatus
from app.models.league import LeagueMember
from app.schemas.round import SubmissionCreate, SubmissionUpdate
from typing import Optional
from datetime import datetime, timezone


def create_submission(db: Session, submission_data: SubmissionCreate, user_id: int) -> Submission:
    """Create a submission for a round"""
    # Get the round
    round_obj = db.query(Round).filter(Round.id == submission_data.round_id).first()
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Round not found"
        )

    # Check if user is a member of the league
    member = db.query(LeagueMember).filter(
        LeagueMember.league_id == round_obj.league_id,
        LeagueMember.user_id == user_id
    ).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a member of this league to submit"
        )

    # Check if round is in submission phase (ACTIVE and voting not started)
    if round_obj.status != RoundStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Round is not active"
        )

    if round_obj.voting_started_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Round is in voting phase - submissions are closed"
        )

    # Check if submission deadline has passed
    if round_obj.submission_deadline:
        now = datetime.now(timezone.utc)
        deadline = round_obj.submission_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Submission deadline has passed"
            )

    # Check if user already submitted
    existing = db.query(Submission).filter(
        Submission.round_id == submission_data.round_id,
        Submission.user_id == user_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already submitted for this round"
        )

    submission = Submission(
        round_id=submission_data.round_id,
        user_id=user_id,
        song_title=submission_data.song_title,
        artist_name=submission_data.artist_name,
        album_name=submission_data.album_name,
        songlink_url=submission_data.songlink_url,
        spotify_url=submission_data.spotify_url,
        apple_music_url=submission_data.apple_music_url,
        youtube_url=submission_data.youtube_url,
        artwork_url=submission_data.artwork_url
    )

    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


def get_submission_by_id(db: Session, submission_id: int) -> Optional[Submission]:
    """Get submission by ID"""
    return db.query(Submission).filter(Submission.id == submission_id).first()


def get_user_submission(db: Session, round_id: int, user_id: int) -> Optional[Submission]:
    """Get user's submission for a round"""
    return db.query(Submission).filter(
        Submission.round_id == round_id,
        Submission.user_id == user_id
    ).first()


def update_submission(db: Session, submission_id: int, submission_data: SubmissionUpdate, user_id: int) -> Submission:
    """Update a submission (only by owner, before deadline)"""
    submission = get_submission_by_id(db, submission_id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found"
        )

    # Check if user owns this submission
    if submission.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own submissions"
        )

    # Get the round to check status
    round_obj = db.query(Round).filter(Round.id == submission.round_id).first()
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Round not found"
        )

    # Check if voting has started
    if round_obj.voting_started_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot update submission during voting phase"
        )

    # Check if submission deadline has passed
    if round_obj.submission_deadline:
        now = datetime.now(timezone.utc)
        deadline = round_obj.submission_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot update submission after deadline"
            )

    # Update fields
    if submission_data.song_title is not None:
        submission.song_title = submission_data.song_title
    if submission_data.artist_name is not None:
        submission.artist_name = submission_data.artist_name
    if submission_data.album_name is not None:
        submission.album_name = submission_data.album_name
    if submission_data.songlink_url is not None:
        submission.songlink_url = submission_data.songlink_url
    if submission_data.spotify_url is not None:
        submission.spotify_url = submission_data.spotify_url
    if submission_data.apple_music_url is not None:
        submission.apple_music_url = submission_data.apple_music_url
    if submission_data.youtube_url is not None:
        submission.youtube_url = submission_data.youtube_url
    if submission_data.artwork_url is not None:
        submission.artwork_url = submission_data.artwork_url

    db.commit()
    db.refresh(submission)
    return submission


def delete_submission(db: Session, submission_id: int, user_id: int) -> None:
    """Delete a submission (only by owner, before deadline)"""
    submission = get_submission_by_id(db, submission_id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found"
        )

    # Check if user owns this submission
    if submission.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only delete your own submissions"
        )

    # Get the round to check status
    round_obj = db.query(Round).filter(Round.id == submission.round_id).first()
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Round not found"
        )

    # Check if voting has started
    if round_obj.voting_started_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete submission during voting phase"
        )

    # Check if submission deadline has passed
    if round_obj.submission_deadline:
        now = datetime.now(timezone.utc)
        deadline = round_obj.submission_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete submission after deadline"
            )

    db.delete(submission)
    db.commit()
