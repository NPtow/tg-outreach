import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Campaign, CampaignTarget
import backend.telegram_client as tg

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    account_id: int
    messages: List[str]       # list of message variants
    targets: List[str]        # list of "username" or "username,name" lines
    delay_min: int = 30
    delay_max: int = 90
    daily_limit: int = 20
    send_hour_from: int = 9   # MSK hour (inclusive)
    send_hour_to: int = 21    # MSK hour (exclusive)


@router.get("/")
def list_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    result = []
    for c in campaigns:
        total = db.query(CampaignTarget).filter(CampaignTarget.campaign_id == c.id).count()
        sent = db.query(CampaignTarget).filter(
            CampaignTarget.campaign_id == c.id, CampaignTarget.status == "sent"
        ).count()
        failed = db.query(CampaignTarget).filter(
            CampaignTarget.campaign_id == c.id, CampaignTarget.status == "failed"
        ).count()
        skipped = db.query(CampaignTarget).filter(
            CampaignTarget.campaign_id == c.id, CampaignTarget.status == "skipped"
        ).count()
        result.append({
            "id": c.id,
            "name": c.name,
            "account_id": c.account_id,
            "status": c.status,
            "is_running": tg.campaign_is_running(c.id),
            "delay_min": c.delay_min,
            "delay_max": c.delay_max,
            "daily_limit": c.daily_limit,
            "send_hour_from": c.send_hour_from,
            "send_hour_to": c.send_hour_to,
            "total": total,
            "sent": sent,
            "failed": failed,
            "skipped": skipped,
            "created_at": c.created_at,
        })
    return result


@router.post("/")
def create_campaign(data: CampaignCreate, db: Session = Depends(get_db)):
    if not data.messages:
        raise HTTPException(400, "Need at least one message variant")
    if not data.targets:
        raise HTTPException(400, "Need at least one target")

    c = Campaign(
        name=data.name,
        account_id=data.account_id,
        messages=json.dumps(data.messages),
        delay_min=data.delay_min,
        delay_max=data.delay_max,
        daily_limit=data.daily_limit,
        send_hour_from=data.send_hour_from,
        send_hour_to=data.send_hour_to,
        status="draft",
    )
    db.add(c)
    db.flush()

    for raw in data.targets:
        raw = raw.strip()
        if not raw:
            continue
        # Support "username,Name" format for personalization
        if "," in raw:
            parts = raw.split(",", 1)
            username = parts[0].strip().lstrip("@")
            display_name = parts[1].strip() or None
        else:
            username = raw.lstrip("@")
            display_name = None
        if username:
            db.add(CampaignTarget(campaign_id=c.id, username=username, display_name=display_name))

    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name}


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, "Campaign not found")
    if not tg.is_running(c.account_id):
        raise HTTPException(400, "Account is not connected")
    c.status = "running"
    db.commit()
    await tg.start_campaign(campaign_id)
    return {"ok": True}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, "Campaign not found")
    await tg.stop_campaign(campaign_id)
    return {"ok": True}


@router.post("/{campaign_id}/retry-failed")
def retry_failed(campaign_id: int, db: Session = Depends(get_db)):
    """Reset all failed targets back to pending so they get retried."""
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, "Campaign not found")
    updated = db.query(CampaignTarget).filter(
        CampaignTarget.campaign_id == campaign_id,
        CampaignTarget.status == "failed",
    ).update({"status": "pending", "error": None})
    # If campaign was done, move back to paused so user can restart
    if c.status == "done" and updated > 0:
        c.status = "paused"
    db.commit()
    return {"ok": True, "retried": updated}


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, "Campaign not found")
    await tg.stop_campaign(campaign_id)
    db.query(CampaignTarget).filter(CampaignTarget.campaign_id == campaign_id).delete()
    db.delete(c)
    db.commit()
    return {"ok": True}
