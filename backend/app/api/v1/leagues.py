from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from app.core.database import get_db
from app.api.deps import get_current_active_user
from app.models.user import User
from app.schemas.league import (
    LeagueCreate,
    LeagueUpdate,
    LeagueResponse,
    LeagueDetailResponse,
    JoinLeagueRequest,
    LeagueMemberResponse
)
from app.services import league_service

router = APIRouter()


@router.post("/", response_model=LeagueResponse, status_code=status.HTTP_201_CREATED)
async def create_league(
    league_data: LeagueCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Create a new league"""
    league = league_service.create_league(db, league_data, current_user.id)
    
    return LeagueResponse(
        id=league.id,
        name=league.name,
        description=league.description,
        invite_code=league.invite_code,
        created_by_id=league.created_by_id,
        created_at=league.created_at,
        member_count=1,
        is_member=True,
        is_admin=True
    )


@router.get("/", response_model=List[LeagueResponse])
async def get_my_leagues(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get all leagues the current user is a member of"""
    leagues = league_service.get_user_leagues(db, current_user.id)
    
    response = []
    for league in leagues:
        members = league_service.get_league_members(db, league.id)
        is_admin = league_service.is_league_admin(db, league.id, current_user.id)
        
        response.append(LeagueResponse(
            id=league.id,
            name=league.name,
            description=league.description,
            invite_code=league.invite_code,
            created_by_id=league.created_by_id,
            created_at=league.created_at,
            member_count=len(members),
            is_member=True,
            is_admin=is_admin
        ))
    
    return response


@router.get("/{league_id}", response_model=LeagueDetailResponse)
async def get_league(
    league_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get league details with member list"""
    league = league_service.get_league_by_id(db, league_id)
    if not league:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="League not found"
        )
    
    # Check if user is a member
    if not league_service.is_league_member(db, league_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a member to view league details"
        )
    
    # Get members with user info
    members = league_service.get_league_members(db, league_id)
    member_responses = []
    for member in members:
        user = db.query(User).filter(User.id == member.user_id).first()
        member_responses.append(LeagueMemberResponse(
            id=member.id,
            league_id=member.league_id,
            user_id=member.user_id,
            is_admin=member.is_admin,
            joined_at=member.joined_at,
            user_name=user.name if user else None,
            user_email=user.email if user else None
        ))
    
    is_admin = league_service.is_league_admin(db, league_id, current_user.id)
    
    return LeagueDetailResponse(
        id=league.id,
        name=league.name,
        description=league.description,
        invite_code=league.invite_code,
        created_by_id=league.created_by_id,
        created_at=league.created_at,
        member_count=len(members),
        is_member=True,
        is_admin=is_admin,
        members=member_responses
    )


@router.post("/join", response_model=LeagueResponse)
async def join_league(
    join_data: JoinLeagueRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Join a league using invite code"""
    member = league_service.join_league(db, join_data.invite_code, current_user.id)
    league = league_service.get_league_by_id(db, member.league_id)
    
    members = league_service.get_league_members(db, league.id)
    
    return LeagueResponse(
        id=league.id,
        name=league.name,
        description=league.description,
        invite_code=league.invite_code,
        created_by_id=league.created_by_id,
        created_at=league.created_at,
        member_count=len(members),
        is_member=True,
        is_admin=False
    )


@router.post("/{league_id}/leave")
async def leave_league(
    league_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Leave a league"""
    league_service.leave_league(db, league_id, current_user.id)
    return {"message": "Successfully left the league"}


@router.put("/{league_id}", response_model=LeagueResponse)
async def update_league(
    league_id: int,
    league_data: LeagueUpdate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Update league (admin only)"""
    league = league_service.update_league(db, league_id, league_data, current_user.id)
    
    members = league_service.get_league_members(db, league.id)
    is_admin = league_service.is_league_admin(db, league.id, current_user.id)
    
    return LeagueResponse(
        id=league.id,
        name=league.name,
        description=league.description,
        invite_code=league.invite_code,
        created_by_id=league.created_by_id,
        created_at=league.created_at,
        member_count=len(members),
        is_member=True,
        is_admin=is_admin
    )


@router.delete("/{league_id}")
async def delete_league(
    league_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Delete league (creator only)"""
    league_service.delete_league(db, league_id, current_user.id)
    return {"message": "League deleted successfully"}


@router.get("/{league_id}/leaderboard")
async def get_league_leaderboard(
    league_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Get cumulative leaderboard for a league"""
    # Check if user is a member
    if not league_service.is_league_member(db, league_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a member to view the leaderboard"
        )

    return league_service.get_league_leaderboard(db, league_id)
