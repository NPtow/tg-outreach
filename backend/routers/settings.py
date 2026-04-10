from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    openai_key: str = ""
    model: str = "gpt-4o-mini"
    system_prompt: str = ""
    auto_reply_enabled: bool = True
    context_messages: int = 10


@router.get("/")
def get_settings(db: Session = Depends(get_db)):
    s = db.query(Settings).filter(Settings.id == 1).first()
    if not s:
        s = Settings(id=1)
        db.add(s)
        db.commit()
        db.refresh(s)
    return {
        "openai_key": s.openai_key,
        "model": s.model,
        "system_prompt": s.system_prompt,
        "auto_reply_enabled": s.auto_reply_enabled,
        "context_messages": s.context_messages,
    }


@router.put("/")
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    s = db.query(Settings).filter(Settings.id == 1).first()
    if not s:
        s = Settings(id=1)
        db.add(s)
    s.openai_key = data.openai_key
    s.model = data.model
    s.system_prompt = data.system_prompt
    s.auto_reply_enabled = data.auto_reply_enabled
    s.context_messages = data.context_messages
    db.commit()
    return {"ok": True}
