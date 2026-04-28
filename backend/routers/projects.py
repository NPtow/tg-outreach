from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Account, Project, ProjectAccount, ProjectProxy, ProxyPool
from backend.projects import ensure_default_project
from backend.routers.proxy_pool import _serialize as serialize_proxy
from backend.telegram_client import serialize_public_account

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    default_timezone: str = "Europe/Moscow"
    default_calendar_email: Optional[str] = None
    dify_dataset_id: Optional[str] = None


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    default_timezone: Optional[str] = None
    default_calendar_email: Optional[str] = None
    dify_dataset_id: Optional[str] = None


def serialize_project(project: Project) -> dict:
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description or "",
        "status": project.status or "active",
        "default_timezone": project.default_timezone or "Europe/Moscow",
        "default_calendar_email": project.default_calendar_email,
        "dify_dataset_id": project.dify_dataset_id,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _require_project(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.get("/")
def list_projects(db: Session = Depends(get_db)):
    ensure_default_project(db)
    db.commit()
    projects = db.query(Project).order_by(Project.created_at.asc(), Project.id.asc()).all()
    return [serialize_project(project) for project in projects]


@router.post("/")
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Project name is required")
    project = Project(
        name=name,
        description=data.description or "",
        default_timezone=data.default_timezone or "Europe/Moscow",
        default_calendar_email=data.default_calendar_email,
        dify_dataset_id=data.dify_dataset_id,
        status="active",
        updated_at=datetime.utcnow(),
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return serialize_project(project)


@router.patch("/{project_id}")
def update_project(project_id: int, data: ProjectUpdate, db: Session = Depends(get_db)):
    project = _require_project(db, project_id)
    if data.name is not None:
        if not data.name.strip():
            raise HTTPException(400, "Project name is required")
        project.name = data.name.strip()
    if data.description is not None:
        project.description = data.description
    if data.status is not None:
        project.status = data.status
    if data.default_timezone is not None:
        project.default_timezone = data.default_timezone or "Europe/Moscow"
    if data.default_calendar_email is not None:
        project.default_calendar_email = data.default_calendar_email or None
    if data.dify_dataset_id is not None:
        project.dify_dataset_id = data.dify_dataset_id or None
    project.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(project)
    return serialize_project(project)


@router.post("/{project_id}/accounts/{account_id}/attach")
def attach_account(project_id: int, account_id: int, db: Session = Depends(get_db)):
    _require_project(db, project_id)
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(404, "Account not found")
    link = (
        db.query(ProjectAccount)
        .filter(ProjectAccount.project_id == project_id, ProjectAccount.account_id == account_id)
        .first()
    )
    if not link:
        link = ProjectAccount(project_id=project_id, account_id=account_id)
        db.add(link)
        db.commit()
        db.refresh(link)
    return {"ok": True, "project_id": project_id, "account_id": account_id}


@router.post("/{project_id}/proxies/{proxy_id}/attach")
def attach_proxy(project_id: int, proxy_id: int, db: Session = Depends(get_db)):
    _require_project(db, project_id)
    proxy = db.query(ProxyPool).filter(ProxyPool.id == proxy_id).first()
    if not proxy:
        raise HTTPException(404, "Proxy not found")
    link = (
        db.query(ProjectProxy)
        .filter(ProjectProxy.project_id == project_id, ProjectProxy.proxy_id == proxy_id)
        .first()
    )
    if not link:
        link = ProjectProxy(project_id=project_id, proxy_id=proxy_id)
        db.add(link)
        db.commit()
        db.refresh(link)
    return {"ok": True, "project_id": project_id, "proxy_id": proxy_id}


@router.get("/{project_id}/resources")
def get_project_resources(project_id: int, db: Session = Depends(get_db)):
    _require_project(db, project_id)
    account_links = (
        db.query(ProjectAccount)
        .filter(ProjectAccount.project_id == project_id)
        .order_by(ProjectAccount.id.asc())
        .all()
    )
    proxy_links = (
        db.query(ProjectProxy)
        .filter(ProjectProxy.project_id == project_id)
        .order_by(ProjectProxy.id.asc())
        .all()
    )
    return {
        "project_id": project_id,
        "accounts": [serialize_public_account(link.account) for link in account_links if link.account],
        "proxies": [serialize_proxy(link.proxy) for link in proxy_links if link.proxy],
    }
