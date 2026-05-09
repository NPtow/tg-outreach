import json
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import AgentPipeline, Campaign, CampaignTarget, Conversation
from backend.projects import resolve_project_id
from backend.runtime_config import owns_telegram_runtime
from backend.worker_client import forward_to_worker
import backend.telegram_client as tg

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    project_id: Optional[int] = None
    account_ids: List[int]           # one or more accounts
    messages: List[str]
    targets: List[str]               # "username" or "username,name,company,role,note"
    delay_min: int = 30
    delay_max: int = 90
    daily_limit: int = 20
    send_hour_from: int = 9
    send_hour_to: int = 21
    send_window_enabled: bool = False
    prompt_template_id: Optional[int] = None
    agent_pipeline_id: Optional[int] = None
    stop_on_reply: bool = False
    stop_keywords: Optional[str] = None   # comma-separated
    hot_keywords: Optional[str] = None    # comma-separated
    max_messages: Optional[int] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    delay_min: Optional[int] = None
    delay_max: Optional[int] = None
    daily_limit: Optional[int] = None
    send_hour_from: Optional[int] = None
    send_hour_to: Optional[int] = None
    send_window_enabled: Optional[bool] = None
    stop_on_reply: Optional[bool] = None
    stop_keywords: Optional[str] = None
    hot_keywords: Optional[str] = None
    max_messages: Optional[int] = None


def _pipeline_config(pipeline: AgentPipeline) -> dict[str, Any]:
    try:
        return json.loads(pipeline.config_json or "{}")
    except Exception:
        return {}


def _ensure_campaign_pipeline_live(db: Session, agent_pipeline_id: Optional[int]) -> None:
    if not agent_pipeline_id:
        return
    pipeline = db.query(AgentPipeline).filter(AgentPipeline.id == int(agent_pipeline_id)).first()
    if not pipeline:
        raise HTTPException(400, "Agent pipeline not found")
    if pipeline.status != "active":
        raise HTTPException(400, f"Agent pipeline '{pipeline.name}' must be active before using it for campaign auto-reply")
    if pipeline.type == "n8n_webhook":
        mode = str(_pipeline_config(pipeline).get("mode") or "sandbox").strip().lower()
        if mode != "live":
            raise HTTPException(400, f"Agent pipeline '{pipeline.name}' must be live before using it for campaign auto-reply")


@router.get("/")
def list_campaigns(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    try:
        q = db.query(Campaign)
        if project_id is not None:
            q = q.filter(Campaign.project_id == int(project_id))
        campaigns = q.order_by(Campaign.created_at.desc()).all()
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
            acc_ids = json.loads(c.account_ids) if c.account_ids else [c.account_id]
            is_running = tg.campaign_is_running(c.id) if owns_telegram_runtime() else c.status == "running"
            result.append({
                "id": c.id,
                "project_id": c.project_id,
                "name": c.name,
                "account_id": c.account_id,
                "account_ids": acc_ids,
                "status": c.status,
                "is_running": is_running,
                "delay_min": c.delay_min,
                "delay_max": c.delay_max,
                "daily_limit": c.daily_limit,
                "send_hour_from": c.send_hour_from,
                "send_hour_to": c.send_hour_to,
                "send_window_enabled": bool(c.send_window_enabled),
                "prompt_template_id": c.prompt_template_id,
                "agent_pipeline_id": c.agent_pipeline_id,
                "agent_pipeline_name": (
                    db.query(AgentPipeline.name).filter(AgentPipeline.id == c.agent_pipeline_id).scalar()
                    if c.agent_pipeline_id else None
                ),
                "stop_on_reply": bool(c.stop_on_reply),
                "stop_keywords": c.stop_keywords or "",
                "hot_keywords": c.hot_keywords or "",
                "max_messages": c.max_messages,
                "total": total,
                "sent": sent,
                "failed": failed,
                "skipped": skipped,
                "created_at": c.created_at,
            })
        return result
    except Exception as e:
        logger.error(f"list_campaigns failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/")
def create_campaign(data: CampaignCreate, db: Session = Depends(get_db)):
    if not data.messages:
        raise HTTPException(400, "Need at least one message variant")
    if not data.targets:
        raise HTTPException(400, "Need at least one target")
    if not data.account_ids:
        raise HTTPException(400, "Need at least one account")
    _ensure_campaign_pipeline_live(db, data.agent_pipeline_id)

    c = Campaign(
        project_id=resolve_project_id(db, data.project_id),
        name=data.name,
        account_id=data.account_ids[0],          # primary account (for compat)
        account_ids=json.dumps(data.account_ids),
        messages=json.dumps(data.messages),
        delay_min=data.delay_min,
        delay_max=data.delay_max,
        daily_limit=data.daily_limit,
        send_hour_from=data.send_hour_from,
        send_hour_to=data.send_hour_to,
        send_window_enabled=data.send_window_enabled,
        prompt_template_id=data.prompt_template_id,
        agent_pipeline_id=data.agent_pipeline_id,
        stop_on_reply=data.stop_on_reply,
        stop_keywords=data.stop_keywords,
        hot_keywords=data.hot_keywords,
        max_messages=data.max_messages,
        status="draft",
    )
    db.add(c)
    db.flush()

    for raw in data.targets:
        raw = raw.strip()
        if not raw:
            continue
        # CSV format: username[,name[,company[,role[,note]]]]
        parts = [p.strip() for p in raw.split(",")]
        username = parts[0].lstrip("@")
        if not username:
            continue
        db.add(CampaignTarget(
            campaign_id=c.id,
            username=username,
            display_name=parts[1] if len(parts) > 1 and parts[1] else None,
            company=parts[2] if len(parts) > 2 and parts[2] else None,
            role=parts[3] if len(parts) > 3 and parts[3] else None,
            custom_note=parts[4] if len(parts) > 4 and parts[4] else None,
        ))

    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name}


@router.patch("/{campaign_id}")
async def update_campaign(campaign_id: int, data: CampaignUpdate, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, "Campaign not found")

    payload = data.model_dump(exclude_unset=True)
    int_fields = ("delay_min", "delay_max", "daily_limit", "send_hour_from", "send_hour_to", "max_messages")
    for field in int_fields:
        if field in payload and payload[field] is not None:
            payload[field] = int(payload[field])

    if "daily_limit" in payload and payload["daily_limit"] is not None and payload["daily_limit"] < 1:
        raise HTTPException(400, "daily_limit must be greater than 0")
    if "delay_min" in payload and payload["delay_min"] is not None and payload["delay_min"] < 0:
        raise HTTPException(400, "delay_min must be greater than or equal to 0")
    if "delay_max" in payload and payload["delay_max"] is not None and payload["delay_max"] < 0:
        raise HTTPException(400, "delay_max must be greater than or equal to 0")
    next_delay_min = payload.get("delay_min", c.delay_min)
    next_delay_max = payload.get("delay_max", c.delay_max)
    if next_delay_min is not None and next_delay_max is not None and int(next_delay_min) > int(next_delay_max):
        raise HTTPException(400, "delay_min cannot be greater than delay_max")
    for field in ("send_hour_from", "send_hour_to"):
        if field in payload and payload[field] is not None and not (0 <= payload[field] <= 23):
            raise HTTPException(400, f"{field} must be between 0 and 23")

    for field, value in payload.items():
        if field == "name" and value is not None:
            value = value.strip()
            if not value:
                raise HTTPException(400, "Campaign name cannot be empty")
        setattr(c, field, value)

    was_running = c.status == "running"
    db.commit()
    db.refresh(c)

    runtime = {"ok": True, "restarted": False}
    if was_running:
        if owns_telegram_runtime():
            runtime = await tg.refresh_campaign_runtime(campaign_id)
        else:
            runtime = await forward_to_worker("POST", f"/internal/runtime/campaigns/{campaign_id}/refresh")

    return {
        "ok": True,
        "id": c.id,
        "daily_limit": c.daily_limit,
        "status": c.status,
        "runtime": runtime,
    }


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: int, db: Session = Depends(get_db)):
    try:
        c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not c:
            raise HTTPException(404, "Campaign not found")
        _ensure_campaign_pipeline_live(db, c.agent_pipeline_id)
        if owns_telegram_runtime():
            result = await tg.preflight_and_start_campaign(campaign_id)
        else:
            result = await forward_to_worker("POST", f"/internal/runtime/campaigns/{campaign_id}/start")
        if not result.get("ok"):
            raise HTTPException(400, result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"start_campaign {campaign_id} failed: {e}", exc_info=True)
        raise HTTPException(500, str(e))


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, "Campaign not found")
    if owns_telegram_runtime():
        await tg.stop_campaign(campaign_id)
        return {"ok": True}
    return await forward_to_worker("POST", f"/internal/runtime/campaigns/{campaign_id}/pause")


@router.post("/{campaign_id}/retry-failed")
def retry_failed(campaign_id: int, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, "Campaign not found")
    updated = db.query(CampaignTarget).filter(
        CampaignTarget.campaign_id == campaign_id,
        CampaignTarget.status == "failed",
    ).update({"status": "pending", "error": None})
    if c.status == "done" and updated > 0:
        c.status = "paused"
    db.commit()
    return {"ok": True, "retried": updated}


@router.get("/{campaign_id}/targets")
def get_targets(campaign_id: int, status: Optional[str] = None, db: Session = Depends(get_db)):
    """Get targets of a campaign — used for importing into new campaigns."""
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, "Campaign not found")
    q = db.query(CampaignTarget).filter(CampaignTarget.campaign_id == campaign_id)
    if status:
        q = q.filter(CampaignTarget.status == status)
    targets = q.all()
    return [
        {
            "username": t.username,
            "display_name": t.display_name,
            "company": t.company,
            "role": t.role,
            "custom_note": t.custom_note,
            "status": t.status,
            "error": t.error,
            "sent_at": t.sent_at,
            "account_id": t.account_id,
        }
        for t in targets
    ]


@router.delete("/{campaign_id}")
async def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(404, "Campaign not found")
    await tg.stop_campaign(campaign_id)
    db.query(Conversation).filter(Conversation.source_campaign_id == campaign_id).update(
        {"source_campaign_id": None},
        synchronize_session=False,
    )
    db.query(CampaignTarget).filter(CampaignTarget.campaign_id == campaign_id).delete()
    db.delete(c)
    db.commit()
    return {"ok": True}
