from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from backend.database import get_db
from backend.models import DoNotContact

router = APIRouter(prefix="/api/dnc", tags=["dnc"])


class DNCAdd(BaseModel):
    username: Optional[str] = None
    tg_user_id: Optional[str] = None
    reason: Optional[str] = None


@router.get("/")
def list_dnc(db: Session = Depends(get_db)):
    return db.query(DoNotContact).order_by(DoNotContact.created_at.desc()).all()


@router.post("/")
def add_dnc(data: DNCAdd, db: Session = Depends(get_db)):
    if not data.username and not data.tg_user_id:
        raise HTTPException(400, "Provide username or tg_user_id")
    username = (data.username or "").lstrip("@") or None
    existing = db.query(DoNotContact).filter(
        (DoNotContact.username == username) if username else (DoNotContact.tg_user_id == data.tg_user_id)
    ).first()
    if existing:
        return existing
    entry = DoNotContact(
        username=username,
        tg_user_id=data.tg_user_id,
        reason=data.reason,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{dnc_id}")
def remove_dnc(dnc_id: int, db: Session = Depends(get_db)):
    entry = db.query(DoNotContact).filter(DoNotContact.id == dnc_id).first()
    if not entry:
        raise HTTPException(404, "Not found")
    db.delete(entry)
    db.commit()
    return {"ok": True}
