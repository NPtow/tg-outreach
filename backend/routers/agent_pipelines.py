import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import AgentPipeline, AgentPipelineVersion, Conversation, Message
from backend.projects import resolve_project_id
from backend.n8n_workspace import (
    N8nWorkspaceError,
    extract_webhook_path,
    n8n_request,
    production_webhook_url,
    workflow_editor_url,
)
from backend.pipeline_runner import replay_pipeline_for_conversation

router = APIRouter(prefix="/api/agent-pipelines", tags=["agent-pipelines"])

VALID_TYPES = {"n8n_webhook", "legacy_prompt", "internal"}
VALID_STATUSES = {"draft", "active", "archived"}


class PipelineCreate(BaseModel):
    project_id: Optional[int] = None
    name: str
    description: Optional[str] = ""
    type: str = "n8n_webhook"
    status: str = "draft"
    config: dict[str, Any] = Field(default_factory=dict)


class PipelineUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    status: Optional[str] = None
    config: Optional[dict[str, Any]] = None


class PipelineReplayRequest(BaseModel):
    conversation_id: int
    dry_run_tools: bool = True


class N8nWorkspaceRequest(BaseModel):
    base_url: str
    api_key: str


class N8nWorkflowImportRequest(N8nWorkspaceRequest):
    workflow: dict[str, Any]


class N8nWorkflowBindRequest(N8nWorkspaceRequest):
    workflow_id: str
    workflow: Optional[dict[str, Any]] = None
    mode: str = "sandbox"
    shared_secret: str = ""


def _validate_type(value: str) -> str:
    value = (value or "").strip() or "n8n_webhook"
    if value not in VALID_TYPES:
        raise HTTPException(400, f"Invalid pipeline type: {value}")
    return value


def _validate_status(value: str) -> str:
    value = (value or "").strip() or "draft"
    if value not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid pipeline status: {value}")
    return value


def _loads_config(raw: str | None) -> dict[str, Any]:
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _clean_config(config: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    cleaned = dict(config or {})
    cleaned.pop("shared_secret_configured", None)
    if cleaned.get("shared_secret") == "" and existing and existing.get("shared_secret"):
        cleaned["shared_secret"] = existing["shared_secret"]
    return cleaned


def serialize_pipeline(pipeline: AgentPipeline) -> dict:
    config = _loads_config(pipeline.config_json)
    safe_config = dict(config)
    if safe_config.get("shared_secret"):
        safe_config["shared_secret"] = ""
        safe_config["shared_secret_configured"] = True
    else:
        safe_config["shared_secret_configured"] = False
    return {
        "id": pipeline.id,
        "project_id": pipeline.project_id,
        "name": pipeline.name,
        "description": pipeline.description or "",
        "type": pipeline.type,
        "status": pipeline.status,
        "config": safe_config,
        "created_at": pipeline.created_at,
        "updated_at": pipeline.updated_at,
    }


def _workspace_safe_error(exc: Exception) -> HTTPException:
    return HTTPException(400, str(exc))


def _write_version(db: Session, pipeline: AgentPipeline, config: dict[str, Any]) -> None:
    latest = (
        db.query(AgentPipelineVersion)
        .filter(AgentPipelineVersion.pipeline_id == pipeline.id)
        .order_by(AgentPipelineVersion.version.desc(), AgentPipelineVersion.id.desc())
        .first()
    )
    next_version = (latest.version + 1) if latest else 1
    if latest:
        latest.is_active = False
    db.add(
        AgentPipelineVersion(
            pipeline_id=pipeline.id,
            version=next_version,
            config_json=json.dumps(config, ensure_ascii=False),
            is_active=True,
            created_by="local-ui",
        )
    )


@router.get("/")
def list_pipelines(project_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(AgentPipeline)
    if project_id is not None:
        q = q.filter(AgentPipeline.project_id == int(project_id))
    pipelines = q.order_by(AgentPipeline.updated_at.desc(), AgentPipeline.id.desc()).all()
    return [serialize_pipeline(pipeline) for pipeline in pipelines]


@router.post("/")
def create_pipeline(data: PipelineCreate, db: Session = Depends(get_db)):
    config = _clean_config(data.config or {})
    pipeline = AgentPipeline(
        project_id=resolve_project_id(db, data.project_id),
        name=data.name.strip(),
        description=data.description or "",
        type=_validate_type(data.type),
        status=_validate_status(data.status),
        config_json=json.dumps(config, ensure_ascii=False),
        updated_at=datetime.utcnow(),
    )
    if not pipeline.name:
        raise HTTPException(400, "Pipeline name is required")
    db.add(pipeline)
    db.flush()
    _write_version(db, pipeline, config)
    db.commit()
    db.refresh(pipeline)
    return serialize_pipeline(pipeline)


@router.put("/{pipeline_id}")
def update_pipeline(pipeline_id: int, data: PipelineUpdate, db: Session = Depends(get_db)):
    pipeline = db.query(AgentPipeline).filter(AgentPipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    if data.name is not None:
        if not data.name.strip():
            raise HTTPException(400, "Pipeline name is required")
        pipeline.name = data.name.strip()
    if data.description is not None:
        pipeline.description = data.description
    if data.type is not None:
        pipeline.type = _validate_type(data.type)
    if data.status is not None:
        pipeline.status = _validate_status(data.status)
    if data.config is not None:
        config = _clean_config(data.config or {}, existing=_loads_config(pipeline.config_json))
        pipeline.config_json = json.dumps(config, ensure_ascii=False)
        _write_version(db, pipeline, config)
    pipeline.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(pipeline)
    return serialize_pipeline(pipeline)


@router.delete("/{pipeline_id}")
def archive_pipeline(pipeline_id: int, db: Session = Depends(get_db)):
    pipeline = db.query(AgentPipeline).filter(AgentPipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    pipeline.status = "archived"
    pipeline.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/{pipeline_id}/replay")
async def replay_pipeline(pipeline_id: int, data: PipelineReplayRequest, db: Session = Depends(get_db)):
    pipeline = db.query(AgentPipeline).filter(AgentPipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    conversation = db.query(Conversation).filter(Conversation.id == data.conversation_id).first()
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )
    return await replay_pipeline_for_conversation(
        db,
        pipeline=pipeline,
        conversation=conversation,
        messages=messages,
        dry_run_tools=data.dry_run_tools,
    )


@router.post("/n8n/workflows")
async def list_n8n_workflows(data: N8nWorkspaceRequest):
    try:
        return await n8n_request(base_url=data.base_url, api_key=data.api_key, method="GET", path="workflows")
    except N8nWorkspaceError as exc:
        raise _workspace_safe_error(exc)


@router.post("/n8n/workflows/get")
async def get_n8n_workflow(data: N8nWorkspaceRequest, workflow_id: str):
    try:
        return await n8n_request(base_url=data.base_url, api_key=data.api_key, method="GET", path=f"workflows/{workflow_id}")
    except N8nWorkspaceError as exc:
        raise _workspace_safe_error(exc)


@router.post("/n8n/workflows/import")
async def import_n8n_workflow(data: N8nWorkflowImportRequest):
    try:
        workflow = dict(data.workflow or {})
        workflow.pop("id", None)
        return await n8n_request(base_url=data.base_url, api_key=data.api_key, method="POST", path="workflows", json_body=workflow)
    except N8nWorkspaceError as exc:
        raise _workspace_safe_error(exc)


@router.post("/{pipeline_id}/bind-n8n-workflow")
async def bind_n8n_workflow(pipeline_id: int, data: N8nWorkflowBindRequest, db: Session = Depends(get_db)):
    pipeline = db.query(AgentPipeline).filter(AgentPipeline.id == pipeline_id).first()
    if not pipeline:
        raise HTTPException(404, "Pipeline not found")
    workflow = data.workflow
    if workflow is None:
        try:
            workflow = await n8n_request(base_url=data.base_url, api_key=data.api_key, method="GET", path=f"workflows/{data.workflow_id}")
        except N8nWorkspaceError as exc:
            raise _workspace_safe_error(exc)
    webhook_path = extract_webhook_path(workflow or {})
    config = _clean_config(
        {
            **_loads_config(pipeline.config_json),
            "n8n_base_url": data.base_url.rstrip("/"),
            "workflow_id": data.workflow_id,
            "workflow_name": (workflow or {}).get("name") or pipeline.name,
            "workflow_editor_url": workflow_editor_url(data.base_url, data.workflow_id),
            "webhook_path": webhook_path,
            "webhook_url": production_webhook_url(data.base_url, webhook_path),
            "mode": data.mode or "sandbox",
            "shared_secret": data.shared_secret,
        },
        existing=_loads_config(pipeline.config_json),
    )
    pipeline.type = "n8n_webhook"
    pipeline.config_json = json.dumps(config, ensure_ascii=False)
    pipeline.updated_at = datetime.utcnow()
    _write_version(db, pipeline, config)
    db.commit()
    db.refresh(pipeline)
    return serialize_pipeline(pipeline)
