import base64
import os
from datetime import datetime

import httpx
from fastapi import HTTPException

ZOOM_TOKEN_URL = "https://zoom.us/oauth/token"
ZOOM_API = "https://api.zoom.us/v2"
ZOOM_PROVIDER = "zoom"


def _zoom_account_id() -> str:
    return (os.getenv("ZOOM_ACCOUNT_ID") or "").strip()


def _zoom_client_id() -> str:
    return (os.getenv("ZOOM_CLIENT_ID") or "").strip()


def _zoom_client_secret() -> str:
    return (os.getenv("ZOOM_CLIENT_SECRET") or "").strip()


def zoom_host_user() -> str:
    return (os.getenv("ZOOM_HOST_EMAIL") or "me").strip()


def zoom_configured() -> bool:
    return bool(_zoom_account_id() and _zoom_client_id() and _zoom_client_secret())


def build_zoom_meeting_payload(
    *,
    start: datetime,
    duration_min: int,
    topic: str,
    agenda: str,
) -> dict:
    return {
        "topic": topic,
        "type": 2,
        "start_time": start.isoformat(),
        "duration": int(duration_min),
        "timezone": "Europe/Moscow",
        "agenda": agenda,
        "settings": {
            "join_before_host": False,
            "waiting_room": True,
            "mute_upon_entry": True,
            "participant_video": False,
            "host_video": True,
        },
    }


async def get_zoom_access_token() -> str:
    if not zoom_configured():
        raise HTTPException(400, "Zoom credentials are not configured")
    basic = base64.b64encode(f"{_zoom_client_id()}:{_zoom_client_secret()}".encode("utf-8")).decode("ascii")
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            ZOOM_TOKEN_URL,
            params={"grant_type": "account_credentials", "account_id": _zoom_account_id()},
            headers={"Authorization": f"Basic {basic}"},
        )
    if response.status_code >= 400:
        raise HTTPException(response.status_code, f"Zoom token request failed: {response.text}")
    token = response.json().get("access_token")
    if not token:
        raise HTTPException(502, "Zoom token response did not include access_token")
    return token


async def create_zoom_meeting(
    *,
    start: datetime,
    duration_min: int,
    topic: str,
    agenda: str,
    host_user: str | None = None,
) -> dict:
    token = await get_zoom_access_token()
    payload = build_zoom_meeting_payload(start=start, duration_min=duration_min, topic=topic, agenda=agenda)
    user = (host_user or zoom_host_user()).strip() or "me"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{ZOOM_API}/users/{user}/meetings",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 400:
        raise HTTPException(response.status_code, f"Zoom meeting create failed: {response.text}")
    return response.json()
