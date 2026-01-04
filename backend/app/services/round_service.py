from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.round import Round, Submission, RoundStatus
from app.models.league import LeagueMember
from app.models.user import User
from app.schemas.round import RoundCreate, RoundUpdate
from app.services import league_service
from typing import List, Optional
from datetime import datetime, timedelta


def create_round(db: Session, round_data: RoundCreate, user_id: int) -> Round:
    """Create a new round (admin only) - created in PENDING status with no deadlines"""
    # Check if user is admin of the league
    if not league_service.is_league_admin(db, round_data.league_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only league admins can create rounds"
        )

    # Determine order - if not specified, add to end of queue
    if round_data.order is None:
        max_order = db.query(Round).filter(
            Round.league_id == round_data.league_id
        ).count()
        order = max_order
    else:
        order = round_data.order

    round_obj = Round(
        league_id=round_data.league_id,
        theme=round_data.theme,
        description=round_data.description,
        order=order,
        status=RoundStatus.PENDING
        # Timestamps are NULL until round starts
    )

    db.add(round_obj)
    db.commit()
    db.refresh(round_obj)
    return round_obj


def start_round(db: Session, round_id: int, user_id: int) -> Round:
    """Start a pending round - calculates and sets deadlines (2 days submission, 5 days voting)"""
    round_obj = get_round_by_id(db, round_id)
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Round not found"
        )

    # Check admin
    if not league_service.is_league_admin(db, round_obj.league_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only league admins can start rounds"
        )

    # Must be pending
    if round_obj.status != RoundStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only pending rounds can be started"
        )

    # Check if another round is already active
    active_round = db.query(Round).filter(
        Round.league_id == round_obj.league_id,
        Round.status == RoundStatus.ACTIVE
    ).first()
    if active_round:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Round '{active_round.theme}' is already active. Complete it before starting a new round."
        )

    # Calculate deadlines
    now = datetime.utcnow()
    submission_deadline = now + timedelta(days=2)
    voting_deadline = submission_deadline + timedelta(days=5)

    # Update round
    round_obj.status = RoundStatus.ACTIVE
    round_obj.started_at = now
    round_obj.submission_deadline = submission_deadline
    round_obj.voting_deadline = voting_deadline

    db.commit()
    db.refresh(round_obj)
    return round_obj


def complete_round(db: Session, round_id: int, user_id: int) -> Round:
    """Complete a round and auto-start next pending round"""
    round_obj = get_round_by_id(db, round_id)
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Round not found"
        )

    # Check admin
    if not league_service.is_league_admin(db, round_obj.league_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only league admins can complete rounds"
        )

    # Must be active
    if round_obj.status != RoundStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only active rounds can be completed"
        )

    # Mark as completed
    round_obj.status = RoundStatus.COMPLETED
    round_obj.completed_at = datetime.utcnow()

    db.commit()
    db.refresh(round_obj)

    # Auto-start next pending round
    next_round = db.query(Round).filter(
        Round.league_id == round_obj.league_id,
        Round.status == RoundStatus.PENDING
    ).order_by(Round.order.asc()).first()

    if next_round:
        start_round(db, next_round.id, user_id)

    return round_obj


def reorder_rounds(db: Session, league_id: int, round_orders: List[dict], user_id: int) -> List[Round]:
    """Reorder pending rounds - round_orders format: [{"id": 1, "order": 0}, {"id": 2, "order": 1}]"""
    # Check admin
    if not league_service.is_league_admin(db, league_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only league admins can reorder rounds"
        )

    # Update each round's order
    for item in round_orders:
        round_obj = get_round_by_id(db, item["id"])
        if not round_obj:
            continue

        if round_obj.league_id != league_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Round {item['id']} does not belong to league {league_id}"
            )

        # Can only reorder pending rounds
        if round_obj.status != RoundStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Round '{round_obj.theme}' cannot be reordered (not pending)"
            )

        round_obj.order = item["order"]

    db.commit()

    # Return reordered rounds
    return get_league_rounds(db, league_id)


def check_submission_complete(db: Session, round_id: int) -> bool:
    """Check if all league members have submitted"""
    round_obj = get_round_by_id(db, round_id)
    if not round_obj:
        return False

    # Get all league members
    member_count = db.query(LeagueMember).filter(
        LeagueMember.league_id == round_obj.league_id
    ).count()

    # Get submission count
    submission_count = db.query(Submission).filter(
        Submission.round_id == round_id
    ).count()

    return submission_count >= member_count


def progress_to_voting(db: Session, round_id: int) -> Round:
    """Progress round from submission phase to voting phase"""
    round_obj = get_round_by_id(db, round_id)
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Round not found"
        )

    if round_obj.status != RoundStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Round must be active"
        )

    # Mark voting as started
    now = datetime.utcnow()
    round_obj.voting_started_at = now
    # Recalculate voting deadline (5 days from now)
    round_obj.voting_deadline = now + timedelta(days=5)

    db.commit()
    db.refresh(round_obj)
    return round_obj


def get_league_rounds(db: Session, league_id: int) -> List[Round]:
    """Get all rounds for a league, ordered by status and order"""
    return db.query(Round).filter(
        Round.league_id == league_id
    ).order_by(
        # Active rounds first, then pending by order, then completed by completion date desc
        Round.status.desc(),
        Round.order.asc(),
        Round.completed_at.desc()
    ).all()


def get_round_by_id(db: Session, round_id: int) -> Optional[Round]:
    """Get round by ID"""
    return db.query(Round).filter(Round.id == round_id).first()


def update_round(db: Session, round_id: int, round_data: RoundUpdate, user_id: int) -> Round:
    """Update round (admin only) - can only edit pending rounds"""
    round_obj = get_round_by_id(db, round_id)
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Round not found"
        )

    # Check admin
    if not league_service.is_league_admin(db, round_obj.league_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only league admins can update rounds"
        )

    # Can only edit pending rounds
    if round_obj.status != RoundStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only edit pending rounds. Use start/complete endpoints for active rounds."
        )

    # Update fields (only theme and description are editable)
    if round_data.theme is not None:
        round_obj.theme = round_data.theme
    if round_data.description is not None:
        round_obj.description = round_data.description

    db.commit()
    db.refresh(round_obj)
    return round_obj


def delete_round(db: Session, round_id: int, user_id: int) -> None:
    """Delete round (admin only) - can only delete pending rounds"""
    round_obj = get_round_by_id(db, round_id)
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Round not found"
        )

    if not league_service.is_league_admin(db, round_obj.league_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only league admins can delete rounds"
        )

    # Can only delete pending rounds
    if round_obj.status != RoundStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only delete pending rounds"
        )

    db.delete(round_obj)
    db.commit()


def get_round_submissions(db: Session, round_id: int) -> List[Submission]:
    """Get all submissions for a round"""
    return db.query(Submission).filter(Submission.round_id == round_id).all()


def user_has_submitted(db: Session, round_id: int, user_id: int) -> bool:
    """Check if user has already submitted for a round"""
    submission = db.query(Submission).filter(
        Submission.round_id == round_id,
        Submission.user_id == user_id
    ).first()
    return submission is not None
