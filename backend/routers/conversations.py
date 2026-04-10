from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from backend.database import get_db
from backend.models import Conversation, Message, Account
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
    convs = q.order_by(Conversation.last_message_at.desc()).all()
    result = []
    for c in convs:
        acc = db.query(Account).filter(Account.id == c.account_id).first()
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
        },
        "messages": [
            {"id": m.id, "role": m.role, "text": m.text, "created_at": m.created_at}
            for m in messages
        ],
    }


@router.post("/{conv_id}/send")
async def send_message(conv_id: int, data: SendMessageRequest, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation not found")

    client = tg._clients.get(conv.account_id)
    if not client:
        raise HTTPException(400, "Account is not connected")

    await client.send_message(int(conv.tg_user_id), data.text)

    msg = Message(conversation_id=conv.id, role="assistant", text=data.text)
    db.add(msg)
    from datetime import datetime
    conv.last_message = data.text
    conv.last_message_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


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
