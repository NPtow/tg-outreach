import io
import csv
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Contact

router = APIRouter(prefix="/api/contacts", tags=["contacts"])


class ContactCreate(BaseModel):
    username: str
    display_name: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    custom_note: Optional[str] = None
    tags: Optional[str] = None


class ContactImport(BaseModel):
    csv_text: str  # raw CSV text: username[,name[,company[,role[,note[,tags]]]]]


class BulkDelete(BaseModel):
    ids: List[int]


def _serialize(c: Contact) -> dict:
    return {
        "id": c.id,
        "username": c.username,
        "display_name": c.display_name,
        "company": c.company,
        "role": c.role,
        "custom_note": c.custom_note,
        "tags": c.tags,
        "created_at": c.created_at,
    }


@router.get("/")
def list_contacts(search: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(Contact).order_by(Contact.created_at.desc())
    if search:
        s = f"%{search.lower()}%"
        from sqlalchemy import or_, func
        q = q.filter(
            or_(
                func.lower(Contact.username).like(s),
                func.lower(Contact.display_name).like(s),
                func.lower(Contact.company).like(s),
                func.lower(Contact.role).like(s),
            )
        )
    return [_serialize(c) for c in q.all()]


@router.post("/")
def create_contact(data: ContactCreate, db: Session = Depends(get_db)):
    username = data.username.strip().lstrip("@")
    if not username:
        raise HTTPException(400, "Username required")
    c = Contact(
        username=username,
        display_name=data.display_name or None,
        company=data.company or None,
        role=data.role or None,
        custom_note=data.custom_note or None,
        tags=data.tags or None,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _serialize(c)


@router.post("/import")
def import_contacts(data: ContactImport, db: Session = Depends(get_db)):
    """
    Import contacts from CSV text.
    Format: username[,display_name[,company[,role[,custom_note[,tags]]]]]
    One contact per line. Lines starting with # are ignored.
    """
    added = 0
    skipped = 0
    reader = csv.reader(io.StringIO(data.csv_text.strip()))
    for row in reader:
        if not row:
            continue
        parts = [p.strip() for p in row]
        username = parts[0].lstrip("@")
        if not username or username.startswith("#"):
            continue
        c = Contact(
            username=username,
            display_name=parts[1] if len(parts) > 1 and parts[1] else None,
            company=parts[2] if len(parts) > 2 and parts[2] else None,
            role=parts[3] if len(parts) > 3 and parts[3] else None,
            custom_note=parts[4] if len(parts) > 4 and parts[4] else None,
            tags=parts[5] if len(parts) > 5 and parts[5] else None,
        )
        db.add(c)
        added += 1
    db.commit()
    return {"added": added, "skipped": skipped}


@router.delete("/bulk")
def bulk_delete(data: BulkDelete, db: Session = Depends(get_db)):
    db.query(Contact).filter(Contact.id.in_(data.ids)).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "deleted": len(data.ids)}


@router.delete("/{contact_id}")
def delete_contact(contact_id: int, db: Session = Depends(get_db)):
    c = db.query(Contact).filter(Contact.id == contact_id).first()
    if not c:
        raise HTTPException(404, "Contact not found")
    db.delete(c)
    db.commit()
    return {"ok": True}
