from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.round import Round, Submission, Vote, RoundStatus
from app.models.song import Song
from app.models.league import LeagueMember
from app.schemas.vote import VoteCreate, VoteUpdate, UserVotesResponse
from typing import List, Optional
from datetime import datetime, timezone


def cast_votes(db: Session, vote_data: VoteCreate, user_id: int) -> List[Vote]:
    """Cast votes for a round - creates/replaces all votes at once"""
    # Get the round
    round_obj = db.query(Round).filter(Round.id == vote_data.round_id).first()
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
            detail="You must be a member of this league to vote"
        )

    # Check if round is in voting phase
    if round_obj.status != RoundStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Round is not active"
        )

    if round_obj.voting_started_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voting has not started yet"
        )

    # Check if voting deadline has passed
    if round_obj.voting_deadline:
        now = datetime.now(timezone.utc)
        deadline = round_obj.voting_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Voting deadline has passed"
            )

    # Validate all songs exist and belong to this round
    for song_id in vote_data.ranked_songs:
        song = db.query(Song).join(Submission).filter(
            Song.id == song_id,
            Submission.round_id == vote_data.round_id
        ).first()
        if not song:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Song {song_id} not found in this round"
            )

        # Check if user is trying to vote for their own song
        if song.submission.user_id == user_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot vote for your own song"
            )

    # Delete existing votes for this user in this round
    db.query(Vote).filter(
        Vote.round_id == vote_data.round_id,
        Vote.voter_id == user_id
    ).delete()

    # Create new votes
    votes = []
    for rank, song_id in enumerate(vote_data.ranked_songs, start=1):
        vote = Vote(
            round_id=vote_data.round_id,
            voter_id=user_id,
            song_id=song_id,
            rank=rank
        )
        db.add(vote)
        votes.append(vote)

    db.commit()
    for vote in votes:
        db.refresh(vote)

    return votes


def get_user_votes(db: Session, round_id: int, user_id: int) -> Optional[UserVotesResponse]:
    """Get user's votes for a round"""
    votes = db.query(Vote).filter(
        Vote.round_id == round_id,
        Vote.voter_id == user_id
    ).order_by(Vote.rank.asc()).all()

    if not votes:
        return None

    return UserVotesResponse(
        round_id=round_id,
        ranked_songs=[vote.song_id for vote in votes],
        voted_at=votes[0].voted_at
    )


def update_votes(db: Session, round_id: int, vote_data: VoteUpdate, user_id: int) -> List[Vote]:
    """Update user's votes (replaces all votes)"""
    # Reuse cast_votes logic
    return cast_votes(db, VoteCreate(round_id=round_id, ranked_songs=vote_data.ranked_songs), user_id)


def delete_votes(db: Session, round_id: int, user_id: int) -> None:
    """Delete all user's votes for a round"""
    # Get the round to check deadline
    round_obj = db.query(Round).filter(Round.id == round_id).first()
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Round not found"
        )

    # Check if voting has ended
    if round_obj.status == RoundStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete votes after round is completed"
        )

    if round_obj.voting_deadline:
        now = datetime.now(timezone.utc)
        deadline = round_obj.voting_deadline
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        if now > deadline:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete votes after deadline"
            )

    # Delete votes
    deleted_count = db.query(Vote).filter(
        Vote.round_id == round_id,
        Vote.voter_id == user_id
    ).delete()

    if deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No votes found"
        )

    db.commit()


def check_voting_complete(db: Session, round_id: int) -> bool:
    """Check if all league members have voted"""
    round_obj = db.query(Round).filter(Round.id == round_id).first()
    if not round_obj:
        return False

    # Get all league members
    member_count = db.query(LeagueMember).filter(
        LeagueMember.league_id == round_obj.league_id
    ).count()

    # Get unique voters count
    voter_count = db.query(Vote.voter_id).filter(
        Vote.round_id == round_id
    ).distinct().count()

    return voter_count >= member_count


def get_round_votes(db: Session, round_id: int) -> List[Vote]:
    """Get all votes for a round (admin only, after voting ends)"""
    return db.query(Vote).filter(Vote.round_id == round_id).all()


def calculate_results(db: Session, round_id: int) -> dict:
    """Calculate vote results for a round"""
    from collections import defaultdict

    # Get the round to verify it's completed
    round_obj = db.query(Round).filter(Round.id == round_id).first()
    if not round_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Round not found"
        )

    # Get all votes
    votes = db.query(Vote).filter(Vote.round_id == round_id).all()

    # Calculate points: 1st place = 3 points, 2nd = 2 points, 3rd = 1 point
    points_by_song = defaultdict(int)
    votes_by_song = defaultdict(list)  # Track who voted for what rank

    for vote in votes:
        if vote.rank == 1:
            points_by_song[vote.song_id] += 3
        elif vote.rank == 2:
            points_by_song[vote.song_id] += 2
        elif vote.rank == 3:
            points_by_song[vote.song_id] += 1

        votes_by_song[vote.song_id].append({
            "voter_id": vote.voter_id,
            "voter_name": vote.voter.name,
            "rank": vote.rank
        })

    # Get song details and build results
    results = []
    songs = db.query(Song).join(Submission).filter(Submission.round_id == round_id).all()

    for song in songs:
        results.append({
            "song_id": song.id,
            "song_title": song.song_title,
            "artist_name": song.artist_name,
            "album_name": song.album_name,
            "submitter_id": song.submission.user_id,
            "submitter_name": song.submission.user.name,
            "total_points": points_by_song[song.id],
            "votes_received": votes_by_song[song.id],
            "first_place_votes": sum(1 for v in votes_by_song[song.id] if v["rank"] == 1),
            "second_place_votes": sum(1 for v in votes_by_song[song.id] if v["rank"] == 2),
            "third_place_votes": sum(1 for v in votes_by_song[song.id] if v["rank"] == 3)
        })

    # Sort by total points descending
    results.sort(key=lambda x: x["total_points"], reverse=True)

    return {
        "round_id": round_id,
        "round_theme": round_obj.theme,
        "results": results
    }
