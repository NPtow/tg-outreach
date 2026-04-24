from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.google_calendar import (
    build_google_auth_url,
    create_tomorrow_test_meeting,
    exchange_google_code,
    google_configured,
    verify_oauth_state,
)
from backend.models import Integration
from backend.security import has_secret

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


@router.get("/google/status")
def google_status(db: Session = Depends(get_db)):
    integration = db.query(Integration).filter(Integration.provider == "google_calendar").first()
    return {
        "configured": google_configured(),
        "connected": bool(integration and has_secret(integration.refresh_token)),
        "account_email": integration.account_email if integration else "",
        "expires_at": integration.expires_at if integration else None,
    }


@router.get("/google/connect")
def google_connect():
    return RedirectResponse(build_google_auth_url())


@router.get("/google/callback", response_class=HTMLResponse)
async def google_callback(
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
    db: Session = Depends(get_db),
):
    if error:
        raise HTTPException(400, f"Google OAuth failed: {error}")
    if not code:
        raise HTTPException(400, "Google OAuth code is missing")
    if not verify_oauth_state(state):
        raise HTTPException(400, "Google OAuth state is invalid or expired")
    await exchange_google_code(db, code)
    return """
    <html>
      <body style="font-family: system-ui; padding: 32px;">
        <h2>Google Calendar connected</h2>
        <p>Можно закрыть эту вкладку и вернуться в TG Outreach.</p>
      </body>
    </html>
    """


@router.post("/google/test-meeting")
async def google_test_meeting(db: Session = Depends(get_db)):
    return await create_tomorrow_test_meeting(db)
