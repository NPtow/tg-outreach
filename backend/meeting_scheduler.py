from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.google_calendar import (
    DEFAULT_MEETING_DURATION_MIN,
    DEFAULT_WINDOW_END_HOUR,
    DEFAULT_WINDOW_START_HOUR,
    TEST_MEETING_DESCRIPTION,
    build_calendar_event_description,
    create_calendar_event,
    get_busy_intervals,
    find_first_free_slot,
)
from backend.models import Conversation, ScheduledMeeting
from backend.zoom_meetings import create_zoom_meeting

BOOK_MEETING_MARKER = "[[BOOK_MEETING]]"
MSK_TZ = ZoneInfo("Europe/Moscow")


def append_meeting_booking_instructions(system_prompt: str) -> str:
    base = (system_prompt or "").strip()
    instruction = f"""

Meeting booking tool:
- If the lead clearly agrees to a call/interview/meeting or asks to book a time, add a final separate line exactly: {BOOK_MEETING_MARKER}
- Do not show or explain this marker to the user.
- If the lead is only asking questions or has not clearly agreed to meet, do not add the marker.
""".strip()
    return f"{base}\n\n{instruction}" if base else instruction


def extract_meeting_booking_intent(reply: str) -> tuple[str, bool]:
    text = reply or ""
    wants_booking = BOOK_MEETING_MARKER in text
    text = text.replace(BOOK_MEETING_MARKER, "")
    text = text.replace("\\n", "\n")
    clean_lines = [line.rstrip() for line in text.splitlines()]
    clean = "\n".join(clean_lines).strip()
    return clean, wants_booking


def get_existing_scheduled_meeting(db: Session, conversation_id: int) -> Optional[ScheduledMeeting]:
    return (
        db.query(ScheduledMeeting)
        .filter(
            ScheduledMeeting.conversation_id == conversation_id,
            ScheduledMeeting.status == "scheduled",
        )
        .order_by(ScheduledMeeting.created_at.desc(), ScheduledMeeting.id.desc())
        .first()
    )


def build_meeting_reply_text(start: datetime, end: datetime, zoom_join_url: Optional[str]) -> str:
    start_msk = _as_msk(start)
    end_msk = _as_msk(end)
    slot = f"{start_msk:%d.%m.%Y}, {start_msk:%H:%M}-{end_msk:%H:%M} МСК"
    if zoom_join_url:
        return f"Забронировал встречу на {slot}. Ссылка Zoom: {zoom_join_url}"
    return f"Забронировал встречу на {slot}."


def _as_msk(value: datetime) -> datetime:
    if value.tzinfo:
        return value.astimezone(MSK_TZ)
    return value.replace(tzinfo=MSK_TZ)


def next_booking_search_start(now: Optional[datetime] = None) -> datetime:
    current = (now or datetime.now(MSK_TZ)).astimezone(MSK_TZ)
    tomorrow = (current + timedelta(days=1)).date()
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, 16, tzinfo=MSK_TZ)


async def find_next_available_slot(
    db: Session,
    *,
    start_from: Optional[datetime] = None,
    search_days: int = 14,
    duration_min: int = DEFAULT_MEETING_DURATION_MIN,
) -> tuple[datetime, datetime]:
    first_day = (start_from or next_booking_search_start()).astimezone(MSK_TZ).date()
    for offset in range(search_days):
        day = first_day + timedelta(days=offset)
        window_start = datetime(day.year, day.month, day.day, DEFAULT_WINDOW_START_HOUR, tzinfo=MSK_TZ)
        window_end = datetime(day.year, day.month, day.day, DEFAULT_WINDOW_END_HOUR, tzinfo=MSK_TZ)
        busy = await get_busy_intervals(db, window_start, window_end)
        slot = find_first_free_slot(busy, window_start, window_end, duration_min=duration_min)
        if slot:
            return slot
    raise HTTPException(409, f"No free {duration_min}-minute slot in the next {search_days} days")


async def book_meeting_for_conversation(
    db: Session,
    conversation_id: int,
    *,
    duration_min: int = DEFAULT_MEETING_DURATION_MIN,
    search_days: int = 14,
) -> dict:
    existing = get_existing_scheduled_meeting(db, conversation_id)
    if existing:
        return _serialize_scheduled_meeting(existing, created=False)

    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(404, "Conversation not found")

    start, end = await find_next_available_slot(db, search_days=search_days, duration_min=duration_min)
    topic = _meeting_topic(conversation)
    zoom_meeting = await create_zoom_meeting(
        start=start,
        duration_min=duration_min,
        topic=topic,
        agenda=TEST_MEETING_DESCRIPTION,
    )
    event = await create_calendar_event(
        db,
        start=start,
        end=end,
        summary=topic,
        description=build_calendar_event_description(TEST_MEETING_DESCRIPTION, zoom_meeting),
    )
    scheduled = ScheduledMeeting(
        conversation_id=conversation_id,
        status="scheduled",
        scheduled_start=start,
        scheduled_end=end,
        timezone="Europe/Moscow",
        calendar_event_id=event.get("id"),
        calendar_html_link=event.get("htmlLink"),
        zoom_meeting_id=str(zoom_meeting.get("id") or ""),
        zoom_join_url=zoom_meeting.get("join_url"),
    )
    db.add(scheduled)
    db.commit()
    db.refresh(scheduled)
    return _serialize_scheduled_meeting(scheduled, created=True)


async def maybe_book_meeting_from_reply(db: Session, conversation_id: int, reply: str) -> tuple[str, Optional[dict]]:
    clean_reply, wants_booking = extract_meeting_booking_intent(reply)
    if not wants_booking:
        return clean_reply, None
    meeting = await book_meeting_for_conversation(db, conversation_id)
    reply_text = meeting.get("reply_text") or ""
    if clean_reply and reply_text:
        return f"{clean_reply}\n\n{reply_text}", meeting
    return clean_reply or reply_text, meeting


def _meeting_topic(conversation: Conversation) -> str:
    lead_name = " ".join(
        part for part in [conversation.tg_first_name, conversation.tg_last_name] if part
    ).strip()
    lead = lead_name or (f"@{conversation.tg_username}" if conversation.tg_username else conversation.tg_user_id)
    return f"TG Outreach interview: {lead}"


def _serialize_scheduled_meeting(meeting: ScheduledMeeting, *, created: bool) -> dict:
    return {
        "ok": True,
        "created": created,
        "meeting_id": meeting.id,
        "start": _as_msk(meeting.scheduled_start).isoformat(),
        "end": _as_msk(meeting.scheduled_end).isoformat(),
        "calendar_event_id": meeting.calendar_event_id,
        "calendar_html_link": meeting.calendar_html_link,
        "zoom_meeting_id": meeting.zoom_meeting_id,
        "zoom_join_url": meeting.zoom_join_url,
        "reply_text": build_meeting_reply_text(meeting.scheduled_start, meeting.scheduled_end, meeting.zoom_join_url),
    }
