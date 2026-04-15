import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import AccountWarming, WarmingProfile, WarmingAction, WarmingChannelPool, Account
from backend.warming_worker import WarmingWorker, _workers, start_all_warming_tasks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/warming", tags=["warming"])

# ─── Default profile configs ─────────────────────────────────────────────────────

_DEFAULT_PHASE1 = json.dumps({
    "online_sessions_per_day": 4,
    "mutual_messages_per_day": 8,
    "subscriptions_per_day": 0,
    "reactions_per_day": 0,
    "searches_per_day": 3,
    "dialog_reads_per_day": 5,
})
_DEFAULT_PHASE2 = json.dumps({
    "online_sessions_per_day": 5,
    "mutual_messages_per_day": 6,
    "subscriptions_per_day": 2,
    "reactions_per_day": 3,
    "searches_per_day": 4,
    "dialog_reads_per_day": 5,
})
_DEFAULT_PHASE3 = json.dumps({
    "online_sessions_per_day": 6,
    "mutual_messages_per_day": 5,
    "subscriptions_per_day": 1,
    "reactions_per_day": 6,
    "searches_per_day": 4,
    "dialog_reads_per_day": 6,
})
_DEFAULT_MAINTENANCE = json.dumps({
    "online_sessions_per_day": 2,
    "mutual_messages_per_day": 2,
    "subscriptions_per_day": 0,
    "reactions_per_day": 2,
    "searches_per_day": 1,
    "dialog_reads_per_day": 2,
})


# ─── Pydantic schemas ────────────────────────────────────────────────────────────

class ProfileCreate(BaseModel):
    name: str
    description: Optional[str] = None
    phase_1_days: int = 3
    phase_2_days: int = 7
    phase_1_config: dict = {}
    phase_2_config: dict = {}
    phase_3_config: dict = {}
    maintenance_config: dict = {}
    permanent_maintenance: bool = False


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    phase_1_days: Optional[int] = None
    phase_2_days: Optional[int] = None
    phase_1_config: Optional[dict] = None
    phase_2_config: Optional[dict] = None
    phase_3_config: Optional[dict] = None
    maintenance_config: Optional[dict] = None
    permanent_maintenance: Optional[bool] = None


class WarmingStart(BaseModel):
    profile_id: int
    campaign_label: Optional[str] = None
    peer_account_ids: list[int] = []


class ChannelCreate(BaseModel):
    username: str
    title: Optional[str] = None
    niche: Optional[str] = None
    language: str = "ru"
    subscriber_count: Optional[int] = None


class ChannelImport(BaseModel):
    channels: list[ChannelCreate]


# ─── Profiles ────────────────────────────────────────────────────────────────────

@router.get("/profiles")
def list_profiles(db: Session = Depends(get_db)):
    profiles = db.query(WarmingProfile).all()
    return [_profile_dict(p) for p in profiles]


@router.post("/profiles")
def create_profile(data: ProfileCreate, db: Session = Depends(get_db)):
    p = WarmingProfile(
        name=data.name,
        description=data.description,
        phase_1_days=data.phase_1_days,
        phase_2_days=data.phase_2_days,
        phase_1_config=json.dumps(data.phase_1_config) if data.phase_1_config else _DEFAULT_PHASE1,
        phase_2_config=json.dumps(data.phase_2_config) if data.phase_2_config else _DEFAULT_PHASE2,
        phase_3_config=json.dumps(data.phase_3_config) if data.phase_3_config else _DEFAULT_PHASE3,
        maintenance_config=json.dumps(data.maintenance_config) if data.maintenance_config else _DEFAULT_MAINTENANCE,
        permanent_maintenance=data.permanent_maintenance,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _profile_dict(p)


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: int, data: ProfileUpdate, db: Session = Depends(get_db)):
    p = db.query(WarmingProfile).filter(WarmingProfile.id == profile_id).first()
    if not p:
        raise HTTPException(404, "Profile not found")
    if data.name is not None:
        p.name = data.name
    if data.description is not None:
        p.description = data.description
    if data.phase_1_days is not None:
        p.phase_1_days = data.phase_1_days
    if data.phase_2_days is not None:
        p.phase_2_days = data.phase_2_days
    if data.phase_1_config is not None:
        p.phase_1_config = json.dumps(data.phase_1_config)
    if data.phase_2_config is not None:
        p.phase_2_config = json.dumps(data.phase_2_config)
    if data.phase_3_config is not None:
        p.phase_3_config = json.dumps(data.phase_3_config)
    if data.maintenance_config is not None:
        p.maintenance_config = json.dumps(data.maintenance_config)
    if data.permanent_maintenance is not None:
        p.permanent_maintenance = data.permanent_maintenance
    db.commit()
    return _profile_dict(p)


@router.delete("/profiles/{profile_id}")
def delete_profile(profile_id: int, db: Session = Depends(get_db)):
    p = db.query(WarmingProfile).filter(WarmingProfile.id == profile_id).first()
    if not p:
        raise HTTPException(404, "Profile not found")
    db.delete(p)
    db.commit()
    return {"ok": True}


def _profile_dict(p: WarmingProfile) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "phase_1_days": p.phase_1_days,
        "phase_2_days": p.phase_2_days,
        "phase_1_config": json.loads(p.phase_1_config or "{}"),
        "phase_2_config": json.loads(p.phase_2_config or "{}"),
        "phase_3_config": json.loads(p.phase_3_config or "{}"),
        "maintenance_config": json.loads(p.maintenance_config or "{}"),
        "permanent_maintenance": p.permanent_maintenance,
        "created_at": p.created_at,
    }


# ─── Account warming control ─────────────────────────────────────────────────────

@router.get("/accounts")
def list_warmings(db: Session = Depends(get_db)):
    warmings = db.query(AccountWarming).all()
    return [_warming_dict(w) for w in warmings]


@router.post("/accounts/{account_id}/start")
def start_warming(account_id: int, data: WarmingStart, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(404, "Account not found")

    profile = db.query(WarmingProfile).filter(WarmingProfile.id == data.profile_id).first()
    if not profile:
        raise HTTPException(404, "Profile not found")

    existing = db.query(AccountWarming).filter(AccountWarming.account_id == account_id).first()
    if existing:
        if existing.status in ("warming", "maintenance"):
            raise HTTPException(400, "Warming already active for this account")
        # reuse slot
        existing.profile_id = data.profile_id
        existing.status = "warming"
        existing.phase = 1
        existing.campaign_label = data.campaign_label
        existing.started_at = datetime.utcnow()
        existing.phase_started_at = datetime.utcnow()
        existing.health_score = 0
        existing.total_actions = 0
        existing.actions_today = 0
        existing.ban_events = 0
        existing.peer_account_ids = json.dumps(data.peer_account_ids)
        db.commit()
        w = existing
    else:
        w = AccountWarming(
            account_id=account_id,
            profile_id=data.profile_id,
            campaign_label=data.campaign_label,
            peer_account_ids=json.dumps(data.peer_account_ids),
        )
        db.add(w)
        db.commit()
        db.refresh(w)

    worker = WarmingWorker(w.id)
    worker.start()
    return _warming_dict(w)


@router.post("/accounts/{account_id}/pause")
def pause_warming(account_id: int, db: Session = Depends(get_db)):
    w = db.query(AccountWarming).filter(AccountWarming.account_id == account_id).first()
    if not w:
        raise HTTPException(404, "No warming found")
    worker = _workers.get(w.id)
    if worker:
        worker.stop()
    w.status = "paused"
    db.commit()
    return {"ok": True}


@router.post("/accounts/{account_id}/resume")
def resume_warming(account_id: int, db: Session = Depends(get_db)):
    w = db.query(AccountWarming).filter(AccountWarming.account_id == account_id).first()
    if not w or w.status not in ("paused",):
        raise HTTPException(400, "Nothing to resume")
    w.status = "warming"
    db.commit()
    worker = WarmingWorker(w.id)
    worker.start()
    return {"ok": True}


@router.post("/accounts/{account_id}/stop")
def stop_warming(account_id: int, db: Session = Depends(get_db)):
    w = db.query(AccountWarming).filter(AccountWarming.account_id == account_id).first()
    if not w:
        raise HTTPException(404, "No warming found")
    worker = _workers.get(w.id)
    if worker:
        worker.stop()
    w.status = "completed"
    db.commit()
    return {"ok": True}


@router.get("/accounts/{account_id}/status")
def get_warming_status(account_id: int, db: Session = Depends(get_db)):
    w = db.query(AccountWarming).filter(AccountWarming.account_id == account_id).first()
    if not w:
        raise HTTPException(404, "No warming found")
    return _warming_dict(w)


@router.get("/accounts/{account_id}/actions")
def get_warming_actions(account_id: int, limit: int = 50, offset: int = 0,
                        db: Session = Depends(get_db)):
    w = db.query(AccountWarming).filter(AccountWarming.account_id == account_id).first()
    if not w:
        raise HTTPException(404, "No warming found")
    actions = (db.query(WarmingAction)
               .filter(WarmingAction.account_warming_id == w.id)
               .order_by(WarmingAction.executed_at.desc())
               .offset(offset).limit(limit).all())
    total = db.query(WarmingAction).filter(WarmingAction.account_warming_id == w.id).count()
    return {
        "total": total,
        "items": [_action_dict(a) for a in actions],
    }


def _warming_dict(w: AccountWarming) -> dict:
    return {
        "id": w.id,
        "account_id": w.account_id,
        "profile_id": w.profile_id,
        "status": w.status,
        "phase": w.phase,
        "campaign_label": w.campaign_label,
        "health_score": w.health_score,
        "actions_today": w.actions_today,
        "total_actions": w.total_actions,
        "ban_events": w.ban_events,
        "subscribed_channels": json.loads(w.subscribed_channels or "[]"),
        "peer_account_ids": json.loads(w.peer_account_ids or "[]"),
        "started_at": w.started_at,
        "last_action_at": w.last_action_at,
        "is_running": w.id in _workers,
    }


def _action_dict(a: WarmingAction) -> dict:
    return {
        "id": a.id,
        "action_type": a.action_type,
        "target": a.target,
        "result": a.result,
        "flood_wait_seconds": a.flood_wait_seconds,
        "details": json.loads(a.details) if a.details else None,
        "executed_at": a.executed_at,
    }


# ─── Channel pool ────────────────────────────────────────────────────────────────

@router.get("/pool")
def list_pool(db: Session = Depends(get_db)):
    channels = db.query(WarmingChannelPool).order_by(WarmingChannelPool.niche).all()
    return [_channel_dict(c) for c in channels]


@router.post("/pool")
def add_channel(data: ChannelCreate, db: Session = Depends(get_db)):
    username = data.username.lstrip("@")
    existing = db.query(WarmingChannelPool).filter(WarmingChannelPool.username == username).first()
    if existing:
        raise HTTPException(400, "Channel already in pool")
    c = WarmingChannelPool(
        username=username,
        title=data.title,
        niche=data.niche,
        language=data.language,
        subscriber_count=data.subscriber_count,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _channel_dict(c)


@router.post("/pool/import")
def import_channels(data: ChannelImport, db: Session = Depends(get_db)):
    added = 0
    for ch in data.channels:
        username = ch.username.lstrip("@")
        if not db.query(WarmingChannelPool).filter(WarmingChannelPool.username == username).first():
            db.add(WarmingChannelPool(
                username=username,
                title=ch.title,
                niche=ch.niche,
                language=ch.language,
                subscriber_count=ch.subscriber_count,
            ))
            added += 1
    db.commit()
    return {"added": added}


@router.patch("/pool/{channel_id}")
def toggle_channel(channel_id: int, db: Session = Depends(get_db)):
    c = db.query(WarmingChannelPool).filter(WarmingChannelPool.id == channel_id).first()
    if not c:
        raise HTTPException(404, "Channel not found")
    c.is_active = not c.is_active
    db.commit()
    return _channel_dict(c)


@router.delete("/pool/{channel_id}")
def delete_channel(channel_id: int, db: Session = Depends(get_db)):
    c = db.query(WarmingChannelPool).filter(WarmingChannelPool.id == channel_id).first()
    if not c:
        raise HTTPException(404, "Channel not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


def _channel_dict(c: WarmingChannelPool) -> dict:
    return {
        "id": c.id,
        "username": c.username,
        "title": c.title,
        "niche": c.niche,
        "language": c.language,
        "subscriber_count": c.subscriber_count,
        "is_active": c.is_active,
        "added_at": c.added_at,
    }


# ─── A/B stats ───────────────────────────────────────────────────────────────────

@router.get("/ab-stats")
def ab_stats(db: Session = Depends(get_db)):
    warmings = db.query(AccountWarming).all()
    groups: dict[str, list] = {}
    for w in warmings:
        label = w.campaign_label or "unlabeled"
        groups.setdefault(label, []).append(w)

    result = []
    for label, ws in groups.items():
        total = len(ws)
        avg_health = sum(w.health_score for w in ws) / total if total else 0
        ban_rate = sum(1 for w in ws if w.ban_events > 0) / total if total else 0
        ready = sum(1 for w in ws if w.health_score >= 60)
        phase_dist = {1: 0, 2: 0, 3: 0, "maintenance": 0}
        for w in ws:
            if w.status == "maintenance":
                phase_dist["maintenance"] += 1
            else:
                phase_dist[w.phase] = phase_dist.get(w.phase, 0) + 1
        result.append({
            "label": label,
            "accounts_count": total,
            "avg_health_score": round(avg_health, 1),
            "ban_rate": round(ban_rate, 3),
            "campaign_ready_count": ready,
            "phase_distribution": phase_dist,
        })

    return sorted(result, key=lambda x: x["label"])
