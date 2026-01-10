from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.league import League, LeagueMember
from app.models.user import User
from app.schemas.league import LeagueCreate, LeagueUpdate
from app.utils.invite_codes import generate_invite_code
from typing import List, Optional


def create_league(db: Session, league_data: LeagueCreate, user_id: int) -> League:
    """Create a new league and add creator as admin member"""
    # Generate unique invite code
    invite_code = generate_invite_code()
    while db.query(League).filter(League.invite_code == invite_code).first():
        invite_code = generate_invite_code()
    
    # Create league
    league = League(
        name=league_data.name,
        description=league_data.description,
        songs_per_round=league_data.songs_per_round or 1,
        invite_code=invite_code,
        created_by_id=user_id
    )
    db.add(league)
    db.flush()  # Get league.id without committing
    
    # Add creator as admin member
    member = LeagueMember(
        league_id=league.id,
        user_id=user_id,
        is_admin=True
    )
    db.add(member)
    db.commit()
    db.refresh(league)
    
    return league


def get_user_leagues(db: Session, user_id: int) -> List[League]:
    """Get all leagues a user is a member of"""
    memberships = db.query(LeagueMember).filter(LeagueMember.user_id == user_id).all()
    league_ids = [m.league_id for m in memberships]
    leagues = db.query(League).filter(League.id.in_(league_ids)).all()
    return leagues


def get_league_by_id(db: Session, league_id: int) -> Optional[League]:
    """Get league by ID"""
    return db.query(League).filter(League.id == league_id).first()


def get_league_by_invite_code(db: Session, invite_code: str) -> Optional[League]:
    """Get league by invite code"""
    return db.query(League).filter(League.invite_code == invite_code).first()


def join_league(db: Session, invite_code: str, user_id: int) -> LeagueMember:
    """Join a league using invite code"""
    # Find league
    league = get_league_by_invite_code(db, invite_code)
    if not league:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid invite code"
        )
    
    # Check if already a member
    existing = db.query(LeagueMember).filter(
        LeagueMember.league_id == league.id,
        LeagueMember.user_id == user_id
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Already a member of this league"
        )
    
    # Add as member
    member = LeagueMember(
        league_id=league.id,
        user_id=user_id,
        is_admin=False
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    
    return member


def leave_league(db: Session, league_id: int, user_id: int) -> None:
    """Leave a league"""
    member = db.query(LeagueMember).filter(
        LeagueMember.league_id == league_id,
        LeagueMember.user_id == user_id
    ).first()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not a member of this league"
        )
    
    db.delete(member)
    db.commit()


def update_league(db: Session, league_id: int, league_data: LeagueUpdate, user_id: int) -> League:
    """Update league (admin only)"""
    league = get_league_by_id(db, league_id)
    if not league:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="League not found"
        )
    
    # Check if user is admin
    member = db.query(LeagueMember).filter(
        LeagueMember.league_id == league_id,
        LeagueMember.user_id == user_id,
        LeagueMember.is_admin == True
    ).first()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update league"
        )
    
    # Update fields
    if league_data.name is not None:
        league.name = league_data.name
    if league_data.description is not None:
        league.description = league_data.description
    if league_data.songs_per_round is not None:
        league.songs_per_round = league_data.songs_per_round
    
    db.commit()
    db.refresh(league)
    return league


def delete_league(db: Session, league_id: int, user_id: int) -> None:
    """Delete league (creator only)"""
    league = get_league_by_id(db, league_id)
    if not league:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="League not found"
        )
    
    if league.created_by_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the creator can delete the league"
        )
    
    db.delete(league)
    db.commit()


def get_league_members(db: Session, league_id: int) -> List[LeagueMember]:
    """Get all members of a league"""
    return db.query(LeagueMember).filter(LeagueMember.league_id == league_id).all()


def is_league_member(db: Session, league_id: int, user_id: int) -> bool:
    """Check if user is a member of a league"""
    member = db.query(LeagueMember).filter(
        LeagueMember.league_id == league_id,
        LeagueMember.user_id == user_id
    ).first()
    return member is not None


def is_league_admin(db: Session, league_id: int, user_id: int) -> bool:
    """Check if user is an admin of a league"""
    member = db.query(LeagueMember).filter(
        LeagueMember.league_id == league_id,
        LeagueMember.user_id == user_id,
        LeagueMember.is_admin == True
    ).first()
    return member is not None


def get_league_leaderboard(db: Session, league_id: int) -> dict:
    """Calculate cumulative points leaderboard for a league"""
    from collections import defaultdict
    from app.models.round import Round, RoundStatus
    from app.services import vote_service

    # Get all completed rounds for this league
    completed_rounds = db.query(Round).filter(
        Round.league_id == league_id,
        Round.status == RoundStatus.COMPLETED
    ).order_by(Round.completed_at.asc()).all()

    # Track points by user across all rounds
    user_points = defaultdict(int)
    user_round_details = defaultdict(list)  # Track per-round performance
    user_info = {}  # Store user details

    # Process each completed round
    for round_obj in completed_rounds:
        results = vote_service.calculate_results(db, round_obj.id)

        for result in results["results"]:
            user_id = result["submitter_id"]
            points = result["total_points"]

            # Add to cumulative total
            user_points[user_id] += points

            # Track per-round details
            user_round_details[user_id].append({
                "round_id": round_obj.id,
                "round_theme": round_obj.theme,
                "points": points,
                "song_title": result["song_title"],
                "artist_name": result["artist_name"]
            })

            # Store user info (from first encounter)
            if user_id not in user_info:
                user_info[user_id] = {
                    "user_id": user_id,
                    "user_name": result["submitter_name"]
                }

    # Build leaderboard entries
    leaderboard = []
    for user_id, total_points in user_points.items():
        leaderboard.append({
            "user_id": user_id,
            "user_name": user_info[user_id]["user_name"],
            "total_points": total_points,
            "rounds_participated": len(user_round_details[user_id]),
            "round_details": user_round_details[user_id]
        })

    # Sort by total points descending
    leaderboard.sort(key=lambda x: x["total_points"], reverse=True)

    return {
        "league_id": league_id,
        "completed_rounds_count": len(completed_rounds),
        "leaderboard": leaderboard
    }
