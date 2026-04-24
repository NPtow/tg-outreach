from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from backend.database import get_db
from backend.meeting_scheduler import book_meeting_for_conversation
from backend.models import Campaign, Conversation, Message, Account
from backend.runtime_config import owns_telegram_runtime
from backend.worker_client import forward_to_worker
import backend.telegram_client as tg

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class SendMessageRequest(BaseModel):
    text: str


class UpdateStatusRequest(BaseModel):
    status: str  # active | paused | done


@router.get("/")
def list_conversations(
    account_id: Optional[int] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    campaign_id: Optional[int] = None,
    unread_only: Optional[bool] = None,
    is_hot: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    q = db.query(Conversation)
    if account_id:
        q = q.filter(Conversation.account_id == account_id)
    if status:
        q = q.filter(Conversation.status == status)
    if search:
        q = q.filter(
            Conversation.tg_username.ilike(f"%{search}%")
            | Conversation.tg_first_name.ilike(f"%{search}%")
        )
    if campaign_id:
        q = q.filter(Conversation.source_campaign_id == campaign_id)
    if unread_only:
        q = q.filter(Conversation.unread_count > 0)
    if is_hot:
        q = q.filter(Conversation.is_hot == True)  # noqa: E712

    convs = q.order_by(Conversation.last_message_at.desc()).all()
    result = []
    for c in convs:
        acc = db.query(Account).filter(Account.id == c.account_id).first()
        campaign_name = None
        if c.source_campaign_id:
            camp = db.query(Campaign).filter(Campaign.id == c.source_campaign_id).first()
            campaign_name = camp.name if camp else None
        result.append({
            "id": c.id,
            "account_id": c.account_id,
            "account_name": acc.name if acc else "",
            "tg_user_id": c.tg_user_id,
            "tg_username": c.tg_username,
            "tg_first_name": c.tg_first_name,
            "tg_last_name": c.tg_last_name,
            "status": c.status,
            "last_message": c.last_message,
            "last_message_at": c.last_message_at,
            "created_at": c.created_at,
            "source_campaign_id": c.source_campaign_id,
            "source_campaign_name": campaign_name,
            "unread_count": c.unread_count or 0,
            "is_hot": bool(c.is_hot),
        })
    return result


@router.get("/{conv_id}/messages")
def get_messages(conv_id: int, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    messages = db.query(Message).filter(
        Message.conversation_id == conv_id
    ).order_by(Message.created_at.asc()).all()
    return {
        "conversation": {
            "id": conv.id,
            "tg_username": conv.tg_username,
            "tg_first_name": conv.tg_first_name,
            "tg_last_name": conv.tg_last_name,
            "status": conv.status,
            "account_id": conv.account_id,
            "tg_user_id": conv.tg_user_id,
            "source_campaign_id": conv.source_campaign_id,
            "is_hot": bool(conv.is_hot),
        },
        "messages": [
            {"id": m.id, "role": m.role, "text": m.text, "created_at": m.created_at}
            for m in messages
        ],
    }


@router.post("/{conv_id}/mark-read")
def mark_read(conv_id: int, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    conv.unread_count = 0
    db.commit()
    return {"ok": True}


@router.post("/{conv_id}/send")
async def send_message(conv_id: int, data: SendMessageRequest, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    if owns_telegram_runtime():
        result = await tg.send_manual_message(conv.account_id, conv.tg_user_id, conv.id, data.text)
    else:
        result = await forward_to_worker(
            "POST",
            f"/internal/runtime/conversations/{conv_id}/send",
            json_body={"text": data.text},
        )
    if not result.get("ok"):
        raise HTTPException(400, result)
    return {"ok": True}


@router.post("/{conv_id}/schedule-meeting")
async def schedule_meeting(conv_id: int, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return await book_meeting_for_conversation(db, conv_id)


@router.patch("/{conv_id}/status")
def update_status(conv_id: int, data: UpdateStatusRequest, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    if data.status not in ("active", "paused", "done"):
        raise HTTPException(400, "Invalid status")
    conv.status = data.status
    db.commit()
    return {"ok": True, "status": conv.status}


@router.patch("/{conv_id}/hot")
def toggle_hot(conv_id: int, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")
    conv.is_hot = not bool(conv.is_hot)
    db.commit()
    return {"ok": True, "is_hot": bool(conv.is_hot)}
