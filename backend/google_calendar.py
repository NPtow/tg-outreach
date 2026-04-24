import hmac
import os
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.models import Integration
from backend.security import decrypt_value, encrypt_value
from backend.zoom_meetings import create_zoom_meeting, zoom_configured

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
)
MSK_TZ = ZoneInfo("Europe/Moscow")
DEFAULT_MEETING_DURATION_MIN = 30
DEFAULT_MEETING_BUFFER_MIN = 15
DEFAULT_WINDOW_START_HOUR = 16
DEFAULT_WINDOW_END_HOUR = 22
TEST_MEETING_SUMMARY = "TG Outreach test meeting"
TEST_MEETING_DESCRIPTION = "Тестовая встреча, созданная TG Outreach локально."


def google_redirect_uri() -> str:
    return (os.getenv("GOOGLE_REDIRECT_URI") or "http://127.0.0.1:8010/api/integrations/google/callback").strip()


def _google_client_id() -> str:
    return (os.getenv("GOOGLE_CLIENT_ID") or "").strip()


def _google_client_secret() -> str:
    return (os.getenv("GOOGLE_CLIENT_SECRET") or "").strip()


def google_configured() -> bool:
    return bool(_google_client_id() and _google_client_secret())


def _state_secret() -> str:
    return (os.getenv("GOOGLE_OAUTH_STATE_SECRET") or _google_client_secret() or "local-dev-state").strip()


def make_oauth_state(now: Optional[int] = None) -> str:
    ts = str(now or int(time.time()))
    sig = hmac.new(_state_secret().encode("utf-8"), ts.encode("utf-8"), sha256).hexdigest()
    return f"{ts}.{sig}"


def verify_oauth_state(state: str, max_age_s: int = 900) -> bool:
    try:
        ts, sig = state.split(".", 1)
        expected = hmac.new(_state_secret().encode("utf-8"), ts.encode("utf-8"), sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return False
        return int(time.time()) - int(ts) <= max_age_s
    except Exception:
        return False


def build_google_auth_url() -> str:
    if not google_configured():
        raise HTTPException(400, "Google OAuth credentials are not configured")
    params = {
        "client_id": _google_client_id(),
        "redirect_uri": google_redirect_uri(),
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": make_oauth_state(),
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def _parse_expiry(expires_in: Optional[int]) -> Optional[datetime]:
    if not expires_in:
        return None
    return datetime.utcnow() + timedelta(seconds=max(int(expires_in) - 60, 0))


async def exchange_google_code(db: Session, code: str) -> Integration:
    if not google_configured():
        raise HTTPException(400, "Google OAuth credentials are not configured")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": _google_client_id(),
                "client_secret": _google_client_secret(),
                "redirect_uri": google_redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
    if response.status_code >= 400:
        raise HTTPException(response.status_code, f"Google token exchange failed: {response.text}")
    payload = response.json()
    integration = db.query(Integration).filter(Integration.provider == "google_calendar").first()
    if not integration:
        integration = Integration(provider="google_calendar")
        db.add(integration)
    integration.access_token = encrypt_value(payload.get("access_token") or "")
    if payload.get("refresh_token"):
        integration.refresh_token = encrypt_value(payload.get("refresh_token"))
    integration.token_type = payload.get("token_type") or "Bearer"
    integration.scope = payload.get("scope") or " ".join(GOOGLE_SCOPES)
    integration.expires_at = _parse_expiry(payload.get("expires_in"))
    integration.account_email = os.getenv("GOOGLE_CALENDAR_EMAIL") or os.getenv("NOTIFY_TO") or ""
    integration.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(integration)
    return integration


async def _refresh_access_token(db: Session, integration: Integration) -> str:
    refresh_token = decrypt_value(integration.refresh_token)
    if not refresh_token:
        raise HTTPException(400, "Google Calendar refresh token is missing")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": _google_client_id(),
                "client_secret": _google_client_secret(),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code >= 400:
        raise HTTPException(response.status_code, f"Google token refresh failed: {response.text}")
    payload = response.json()
    integration.access_token = encrypt_value(payload.get("access_token") or "")
    integration.token_type = payload.get("token_type") or "Bearer"
    integration.expires_at = _parse_expiry(payload.get("expires_in"))
    integration.updated_at = datetime.utcnow()
    db.commit()
    return decrypt_value(integration.access_token)


async def get_google_access_token(db: Session) -> str:
    integration = db.query(Integration).filter(Integration.provider == "google_calendar").first()
    if not integration:
        raise HTTPException(400, "Google Calendar is not connected")
    if integration.expires_at and integration.expires_at <= datetime.utcnow() + timedelta(minutes=2):
        return await _refresh_access_token(db, integration)
    token = decrypt_value(integration.access_token)
    if token:
        return token
    return await _refresh_access_token(db, integration)


def _parse_google_dt(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if not parsed.tzinfo:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(MSK_TZ)


def find_first_free_slot(
    busy: list[dict],
    window_start: datetime,
    window_end: datetime,
    duration_min: int = DEFAULT_MEETING_DURATION_MIN,
    buffer_min: int = DEFAULT_MEETING_BUFFER_MIN,
) -> Optional[tuple[datetime, datetime]]:
    duration = timedelta(minutes=duration_min)
    buffer = timedelta(minutes=buffer_min)
    cursor = window_start
    intervals = sorted(
        ((_parse_google_dt(item["start"]), _parse_google_dt(item["end"])) for item in busy),
        key=lambda item: item[0],
    )
    for busy_start, busy_end in intervals:
        if cursor + duration <= busy_start:
            return cursor, cursor + duration
        if cursor < busy_end + buffer:
            cursor = busy_end + buffer
    if cursor + duration <= window_end:
        return cursor, cursor + duration
    return None


def build_calendar_event_description(base_description: str, zoom_meeting: Optional[dict] = None) -> str:
    if not zoom_meeting or not zoom_meeting.get("join_url"):
        return base_description
    lines = [base_description.rstrip(), "", f"Zoom: {zoom_meeting['join_url']}"]
    if zoom_meeting.get("id"):
        lines.append(f"Zoom meeting ID: {zoom_meeting['id']}")
    return "\n".join(lines)


async def get_busy_intervals(db: Session, start: datetime, end: datetime, calendar_id: str = "primary") -> list[dict]:
    token = await get_google_access_token(db)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{GOOGLE_CALENDAR_API}/freeBusy",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "timeZone": "Europe/Moscow",
                "items": [{"id": calendar_id}],
            },
        )
    if response.status_code >= 400:
        raise HTTPException(response.status_code, f"Google freeBusy failed: {response.text}")
    payload = response.json()
    return payload.get("calendars", {}).get(calendar_id, {}).get("busy", [])


async def create_calendar_event(
    db: Session,
    start: datetime,
    end: datetime,
    summary: str,
    description: str,
    calendar_id: str = "primary",
) -> dict:
    token = await get_google_access_token(db)
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{GOOGLE_CALENDAR_API}/calendars/{calendar_id}/events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "summary": summary,
                "description": description,
                "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Moscow"},
                "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Moscow"},
            },
        )
    if response.status_code >= 400:
        raise HTTPException(response.status_code, f"Google event create failed: {response.text}")
    return response.json()


async def create_tomorrow_test_meeting(db: Session) -> dict:
    now_msk = datetime.now(MSK_TZ)
    tomorrow = (now_msk + timedelta(days=1)).date()
    window_start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, DEFAULT_WINDOW_START_HOUR, tzinfo=MSK_TZ)
    window_end = datetime(tomorrow.year, tomorrow.month, tomorrow.day, DEFAULT_WINDOW_END_HOUR, tzinfo=MSK_TZ)
    busy = await get_busy_intervals(db, window_start, window_end)
    slot = find_first_free_slot(busy, window_start, window_end)
    if not slot:
        raise HTTPException(409, "No free 30-minute slot tomorrow between 16:00 and 22:00 MSK")
    start, end = slot
    zoom_meeting = None
    if zoom_configured():
        zoom_meeting = await create_zoom_meeting(
            start=start,
            duration_min=DEFAULT_MEETING_DURATION_MIN,
            topic=TEST_MEETING_SUMMARY,
            agenda=TEST_MEETING_DESCRIPTION,
        )
    event = await create_calendar_event(
        db,
        start=start,
        end=end,
        summary=TEST_MEETING_SUMMARY,
        description=build_calendar_event_description(TEST_MEETING_DESCRIPTION, zoom_meeting),
    )
    return {
        "ok": True,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "event_id": event.get("id"),
        "html_link": event.get("htmlLink"),
        "zoom_join_url": zoom_meeting.get("join_url") if zoom_meeting else None,
        "zoom_meeting_id": zoom_meeting.get("id") if zoom_meeting else None,
        "busy_checked": len(busy),
    }
