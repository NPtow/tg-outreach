from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Settings
from backend.security import decrypt_value, encrypt_value, has_secret

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    provider: str = "openai"       # openai|anthropic|ollama|lmstudio
    openai_key: str = ""
    anthropic_key: str = ""
    clear_openai_key: bool = False
    clear_anthropic_key: bool = False
    base_url: str = ""             # for ollama/lmstudio
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
        "provider": s.provider or "openai",
        "openai_key": "",
        "anthropic_key": "",
        "openai_key_configured": has_secret(s.openai_key),
        "anthropic_key_configured": has_secret(s.anthropic_key),
        "base_url": s.base_url or "",
        "model": s.model or "gpt-4o-mini",
        "system_prompt": s.system_prompt or "",
        "auto_reply_enabled": s.auto_reply_enabled,
        "context_messages": s.context_messages,
    }


@router.put("/")
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    s = db.query(Settings).filter(Settings.id == 1).first()
    if not s:
        s = Settings(id=1)
        db.add(s)
    s.provider = data.provider
    if data.clear_openai_key:
        s.openai_key = ""
    elif data.openai_key:
        s.openai_key = encrypt_value(data.openai_key)
    if data.clear_anthropic_key:
        s.anthropic_key = ""
    elif data.anthropic_key:
        s.anthropic_key = encrypt_value(data.anthropic_key)
    s.base_url = data.base_url
    s.model = data.model
    s.system_prompt = data.system_prompt
    s.auto_reply_enabled = data.auto_reply_enabled
    s.context_messages = data.context_messages
    db.commit()
    return {"ok": True}
