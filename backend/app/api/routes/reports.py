"""Report endpoint (MysteryMixClub-4vii.13).

``POST /api/v1/reports`` lets a member flag another member's user-generated
content for review -- App Store Guideline 1.2's minimum bar for a UGC app.
v1 covers only ``content_type: "note"`` (the one freeform, attributed
surface a member sees from other members) and is deliberately just
persistence: there's no admin console yet, so review happens by querying
the ``reports`` table directly.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.clubs import _load_club_as_member
from app.api.wire import WireModel
from app.auth.deps import get_current_user
from app.db.session import get_db
from app.models.mix import Mix
from app.models.note import Note
from app.models.report import Report
from app.models.user import User

router = APIRouter(tags=["reports"])

ReportReason = Literal["inappropriate_content", "harassment", "spam", "other"]
ReportDetail = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class ReportCreate(WireModel):
    content_type: Literal["note"]
    content_id: uuid.UUID
    reason: ReportReason
    detail: Optional[ReportDetail] = None


class ReportResponse(WireModel):
    id: str
    status: str
    created_at: datetime


@router.post("/reports", status_code=201, response_model=ReportResponse)
async def create_report(
    payload: ReportCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    note = await db.scalar(select(Note).where(Note.id == payload.content_id))
    if note is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content not found")

    mix_ = await db.scalar(select(Mix).where(Mix.id == note.mix_id))
    if mix_ is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="content not found")

    # Membership check doubles as authorization: only someone who could see
    # this note's club at all can report something in it.
    await _load_club_as_member(mix_.club_id, current_user, db)

    if note.author_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="you can't report your own content",
        )

    report = Report(
        reporter_id=current_user.id,
        reported_user_id=note.author_id,
        club_id=mix_.club_id,
        content_type=payload.content_type,
        content_id=payload.content_id,
        reason=payload.reason,
        detail=payload.detail,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return ReportResponse(id=str(report.id), status=report.status, created_at=report.created_at)
