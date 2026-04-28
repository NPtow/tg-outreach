from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.meeting_scheduler import book_meeting_from_agent_payload

router = APIRouter(prefix="/api/bookings", tags=["bookings"])


class CreateBookingRequest(BaseModel):
    event_id: Optional[str] = ""
    conversation_id: int
    account_id: Optional[int] = None
    start_at: str
    end_at: Optional[str] = ""
    duration_minutes: int = 30
    attendee_email: Optional[str] = ""
    timezone: str = "Europe/Moscow"
    title: Optional[str] = "Research interview"
    agenda: Optional[str] = ""
    dry_run: bool = False


@router.post("/create")
async def create_booking(data: CreateBookingRequest, db: Session = Depends(get_db)):
    return await book_meeting_from_agent_payload(
        db,
        conversation_id=data.conversation_id,
        start_at=data.start_at,
        end_at=data.end_at or "",
        duration_min=data.duration_minutes,
        attendee_email=data.attendee_email or "",
        timezone=data.timezone,
        title=data.title or "Research interview",
        agenda=data.agenda or "",
        dry_run=data.dry_run,
    )
