from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from backend.database import get_db
from backend.models import PromptTemplate
from backend.projects import resolve_project_id

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


class PromptCreate(BaseModel):
    project_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    system_prompt: str


class PromptUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None


@router.get("/")
def list_prompts(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(PromptTemplate)
    if project_id is not None:
        q = q.filter(PromptTemplate.project_id == int(project_id))
    return q.order_by(PromptTemplate.created_at.desc()).all()


@router.post("/")
def create_prompt(data: PromptCreate, db: Session = Depends(get_db)):
    p = PromptTemplate(
        project_id=resolve_project_id(db, data.project_id),
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.put("/{prompt_id}")
def update_prompt(prompt_id: int, data: PromptUpdate, db: Session = Depends(get_db)):
    p = db.query(PromptTemplate).filter(PromptTemplate.id == prompt_id).first()
    if not p:
        raise HTTPException(404, "Prompt not found")
    if data.name is not None:
        p.name = data.name
    if data.description is not None:
        p.description = data.description
    if data.system_prompt is not None:
        p.system_prompt = data.system_prompt
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{prompt_id}")
def delete_prompt(prompt_id: int, db: Session = Depends(get_db)):
    p = db.query(PromptTemplate).filter(PromptTemplate.id == prompt_id).first()
    if not p:
        raise HTTPException(404, "Prompt not found")
    db.delete(p)
    db.commit()
    return {"ok": True}
