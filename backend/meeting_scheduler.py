from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.google_calendar import (
    DEFAULT_MEETING_DURATION_MIN,
    DEFAULT_MEETING_BUFFER_MIN,
    DEFAULT_WINDOW_END_HOUR,
    DEFAULT_WINDOW_START_HOUR,
    TEST_MEETING_DESCRIPTION,
    build_calendar_event_description,
    create_calendar_event,
    get_busy_intervals,
    find_first_free_slot,
)
from backend.models import Conversation, ScheduledMeeting
from backend.zoom_meetings import create_zoom_meeting, zoom_configured

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


def build_meeting_reply_text(
    start: datetime,
    end: datetime,
    zoom_join_url: Optional[str],
    calendar_html_link: Optional[str] = None,
    calendar_add_url: Optional[str] = None,
) -> str:
    start_msk = _as_msk(start)
    end_msk = _as_msk(end)
    slot = f"{start_msk:%d.%m.%Y}, {start_msk:%H:%M}-{end_msk:%H:%M} МСК"
    if calendar_add_url:
        return f"Поставил встречу на {slot}. Ссылка для добавления в календарь: {calendar_add_url}"
    if calendar_html_link:
        return f"Забронировал встречу на {slot}. Ссылка на событие в календаре: {calendar_html_link}"
    if zoom_join_url:
        return f"Забронировал встречу на {slot}. Ссылка Zoom: {zoom_join_url}"
    return f"Забронировал встречу на {slot}."


def _as_msk(value: datetime) -> datetime:
    if value.tzinfo:
        return value.astimezone(MSK_TZ)
    return value.replace(tzinfo=MSK_TZ)


def build_calendar_add_url(
    *,
    start: datetime,
    end: datetime,
    title: str,
    description: str,
    zoom_join_url: Optional[str] = None,
    timezone: str = "Europe/Moscow",
) -> str:
    """Build a lead-facing Google Calendar template URL.

    Google event htmlLink is owner-side evidence. This URL lets a lead add the
    same slot to their own calendar without sharing email.
    """

    start_local = _as_msk(start)
    end_local = _as_msk(end)
    details = (description or "").strip()
    if zoom_join_url:
        details = f"{details}\n\nZoom: {zoom_join_url}".strip()
    params = {
        "action": "TEMPLATE",
        "text": title or "Research interview",
        "dates": f"{start_local:%Y%m%dT%H%M%S}/{end_local:%Y%m%dT%H%M%S}",
        "ctz": timezone or "Europe/Moscow",
        "details": details,
    }
    if zoom_join_url:
        params["location"] = zoom_join_url
    return f"https://calendar.google.com/calendar/render?{urlencode(params)}"


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
    calendar_add_url = build_calendar_add_url(
        start=start,
        end=end,
        title=topic,
        description=TEST_MEETING_DESCRIPTION,
        zoom_join_url=zoom_meeting.get("join_url") if zoom_meeting else None,
    )
    scheduled = ScheduledMeeting(
        project_id=conversation.project_id,
        conversation_id=conversation_id,
        status="scheduled",
        scheduled_start=start,
        scheduled_end=end,
        timezone="Europe/Moscow",
        calendar_event_id=event.get("id"),
        calendar_html_link=event.get("htmlLink"),
        calendar_add_url=calendar_add_url,
        zoom_meeting_id=str(zoom_meeting.get("id") or ""),
        zoom_join_url=zoom_meeting.get("join_url"),
    )
    db.add(scheduled)
    db.commit()
    db.refresh(scheduled)
    return _serialize_scheduled_meeting(scheduled, created=True)


def _parse_booking_datetime(value: str, *, fallback_tz: ZoneInfo = MSK_TZ) -> datetime:
    if not value:
        raise HTTPException(400, "start_at is required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo:
        return parsed.astimezone(fallback_tz)
    return parsed.replace(tzinfo=fallback_tz)


def _busy_overlaps(start: datetime, end: datetime, busy: list[dict]) -> bool:
    for item in busy:
        busy_start = _parse_booking_datetime(item.get("start") or "")
        busy_end = _parse_booking_datetime(item.get("end") or "")
        if start < busy_end and end > busy_start:
            return True
    return False


async def book_meeting_from_agent_payload(
    db: Session,
    *,
    conversation_id: int,
    start_at: str,
    end_at: str = "",
    duration_min: int = DEFAULT_MEETING_DURATION_MIN,
    attendee_email: str = "",
    timezone: str = "Europe/Moscow",
    title: str = "Research interview",
    agenda: str = TEST_MEETING_DESCRIPTION,
    dry_run: bool = False,
) -> dict:
    """Create a concrete calendar/Zoom booking requested by the n8n agent."""

    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(404, "Conversation not found")

    start = _parse_booking_datetime(start_at)
    end = _parse_booking_datetime(end_at) if end_at else start + timedelta(minutes=int(duration_min or DEFAULT_MEETING_DURATION_MIN))
    duration = max(int((end - start).total_seconds() // 60), int(duration_min or DEFAULT_MEETING_DURATION_MIN))
    topic = title or _meeting_topic(conversation)
    description = agenda or TEST_MEETING_DESCRIPTION

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "booking_id": f"dry_run:{conversation_id}:{start.isoformat()}",
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "duration_minutes": duration,
            "attendee_email": attendee_email,
            "calendar_event_id": "",
            "calendar_html_link": "",
            "calendar_add_url": build_calendar_add_url(
                start=start,
                end=end,
                title=topic,
                description=description,
            ),
            "zoom_meeting_id": "",
            "zoom_join_url": "",
        }

    day_start = datetime(start.year, start.month, start.day, DEFAULT_WINDOW_START_HOUR, tzinfo=MSK_TZ)
    day_end = datetime(start.year, start.month, start.day, DEFAULT_WINDOW_END_HOUR, tzinfo=MSK_TZ)
    busy_start = min(day_start, start)
    busy_end = max(day_end, end)
    busy = await get_busy_intervals(db, busy_start, busy_end)
    if _busy_overlaps(start, end, busy):
        alternatives: list[str] = []
        cursor_day = day_start
        for _ in range(3):
            slot = find_first_free_slot(busy, cursor_day, day_end, duration_min=duration)
            if not slot:
                break
            alt_start, alt_end = slot
            alternatives.append(f"{alt_start:%d.%m %H:%M}-{alt_end:%H:%M} МСК")
            cursor_day = alt_end + timedelta(minutes=DEFAULT_MEETING_BUFFER_MIN)
        return {"ok": False, "status": "busy", "alternatives": alternatives}

    zoom_meeting = None
    if zoom_configured():
        zoom_meeting = await create_zoom_meeting(
            start=start,
            duration_min=duration,
            topic=topic,
            agenda=description,
        )
    event = await create_calendar_event(
        db,
        start=start,
        end=end,
        summary=topic,
        description=build_calendar_event_description(description, zoom_meeting),
        attendee_email=attendee_email or None,
    )
    calendar_add_url = build_calendar_add_url(
        start=start,
        end=end,
        title=topic,
        description=description,
        zoom_join_url=zoom_meeting.get("join_url") if zoom_meeting else None,
        timezone=timezone or "Europe/Moscow",
    )
    scheduled = ScheduledMeeting(
        project_id=conversation.project_id,
        conversation_id=conversation_id,
        status="scheduled",
        scheduled_start=start,
        scheduled_end=end,
        timezone=timezone or "Europe/Moscow",
        calendar_event_id=event.get("id"),
        calendar_html_link=event.get("htmlLink"),
        calendar_add_url=calendar_add_url,
        zoom_meeting_id=str(zoom_meeting.get("id") or "") if zoom_meeting else "",
        zoom_join_url=zoom_meeting.get("join_url") if zoom_meeting else "",
    )
    db.add(scheduled)
    db.commit()
    db.refresh(scheduled)
    return {
        "ok": True,
        "booking_id": str(scheduled.id),
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "duration_minutes": duration,
        "attendee_email": attendee_email,
        "calendar_event_id": scheduled.calendar_event_id,
        "calendar_html_link": scheduled.calendar_html_link,
        "calendar_add_url": scheduled.calendar_add_url,
        "zoom_meeting_id": scheduled.zoom_meeting_id,
        "zoom_join_url": scheduled.zoom_join_url,
    }


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
        "calendar_add_url": meeting.calendar_add_url,
        "zoom_meeting_id": meeting.zoom_meeting_id,
        "zoom_join_url": meeting.zoom_join_url,
        "reply_text": build_meeting_reply_text(
            meeting.scheduled_start,
            meeting.scheduled_end,
            meeting.zoom_join_url,
            meeting.calendar_html_link,
            meeting.calendar_add_url,
        ),
    }
