import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.agent_pipeline_installer import PipelineInstallError, install_n8n_pipeline, resolve_n8n_runtime_connection
from backend.models import AgentPipeline, AgentPipelineVersion, Conversation, Message
from backend.n8n_agent import N8nAgentRequest, call_n8n_agent
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


class N8nWorkflowInstallRequest(BaseModel):
    workflow: dict[str, Any]
    project_id: Optional[int] = None
    pipeline_id: Optional[int] = None
    name: str = ""
    description: str = ""
    mode: str = "live"
    status: str = "active"
    assign_account_ids: list[int] = Field(default_factory=list)
    registry_environment: str = ""
    registry_project_key: str = ""
    n8n_base_url: str = ""
    n8n_api_key: str = ""
    sync_settings: bool = True
    activate_workflow: bool = True
    shared_secret: str = ""
    timeout_s: float = 20.0


class N8nWorkflowRegistryRequest(BaseModel):
    registry_environment: str = ""
    registry_project_key: str = ""
    n8n_base_url: str = ""
    n8n_api_key: str = ""


class N8nWorkflowConnectRequest(N8nWorkflowRegistryRequest):
    workflow_id: str
    project_id: Optional[int] = None
    pipeline_id: Optional[int] = None
    name: str = ""
    description: str = ""
    mode: str = "sandbox"
    status: str = "active"
    shared_secret: str = ""
    timeout_s: float = 20.0
    smoke_test_text: str = "Что за продукт?"


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


def _n8n_response_data(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _workflow_summary(workflow: dict[str, Any], *, base_url: str) -> dict[str, Any]:
    workflow_id = str(workflow.get("id") or "")
    webhook_path = extract_webhook_path(workflow)
    return {
        "id": workflow_id,
        "name": workflow.get("name") or "",
        "active": bool(workflow.get("active")),
        "webhook_path": webhook_path,
        "webhook_url": production_webhook_url(base_url, webhook_path),
        "editor_url": workflow_editor_url(base_url, workflow_id),
    }


def _smoke_test_request(*, project_id: Optional[int], workflow_id: str, smoke_text: str) -> N8nAgentRequest:
    return N8nAgentRequest(
        event_id=f"smoke-test:n8n-workflow:{workflow_id}",
        mode="sandbox",
        conversation={
            "id": 0,
            "project_id": project_id,
            "account_id": 0,
            "tg_user_id": "0",
            "tg_username": "test_user",
            "tg_first_name": "Test",
            "tg_last_name": "",
            "status": "sandbox",
            "source_campaign_id": None,
            "is_hot": False,
        },
        messages=[
            {
                "id": 0,
                "role": "user",
                "text": smoke_text.strip() or "Что за продукт?",
                "created_at": None,
            }
        ],
        settings={
            "timezone": "Europe/Moscow",
            "meeting_window": "16:00-22:00",
            "duration_minutes": 30,
            "dry_run_tools": True,
            "smoke_test": True,
        },
        constraints={
            "do_not_send_links": True,
            "do_not_claim_booking_without_record": True,
            "do_not_promise_reminder_without_task": True,
        },
    )


def _validate_smoke_result(call_result) -> dict[str, Any]:
    if not call_result.ok or not call_result.decision:
        raise HTTPException(400, f"n8n smoke-test failed: {call_result.error or 'empty response'}")
    decision = call_result.decision
    if not decision.approved:
        raise HTTPException(400, f"n8n smoke-test failed: approved=false; reason={decision.reason or 'no reason'}")
    if not decision.reply_text.strip():
        raise HTTPException(400, "n8n smoke-test failed: empty reply_text")
    return {
        "status": "passed",
        "duration_ms": call_result.duration_ms,
        "stage": decision.stage,
        "intent": decision.intent,
        "ops_action": decision.ops_action,
        "reply_preview": decision.reply_text.strip()[:240],
    }


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


@router.post("/n8n/workflows/from-registry")
async def list_n8n_workflows_from_registry(data: N8nWorkflowRegistryRequest, db: Session = Depends(get_db)):
    try:
        connection = resolve_n8n_runtime_connection(
            db,
            registry_environment=data.registry_environment,
            registry_project_key=data.registry_project_key,
            n8n_base_url=data.n8n_base_url,
            n8n_api_key=data.n8n_api_key,
        )
        payload = await n8n_request(
            base_url=connection.base_url,
            api_key=connection.api_key,
            method="GET",
            path="workflows",
        )
    except PipelineInstallError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    except N8nWorkspaceError as exc:
        raise _workspace_safe_error(exc)
    workflows = _n8n_response_data(payload)
    if not isinstance(workflows, list):
        workflows = []
    return {
        "ok": True,
        "n8n": {
            "base_url": connection.base_url,
            "environment": connection.environment,
            "project_key": connection.project_key,
            "base_url_source": connection.base_url_source,
            "api_key_configured": True,
            "api_key_source": connection.api_key_source,
        },
        "workflows": [_workflow_summary(workflow, base_url=connection.base_url) for workflow in workflows if isinstance(workflow, dict)],
    }


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


@router.post("/n8n/install")
async def install_n8n_workflow(data: N8nWorkflowInstallRequest, db: Session = Depends(get_db)):
    try:
        result = await install_n8n_pipeline(
            db,
            workflow=data.workflow,
            project_id=data.project_id,
            pipeline_id=data.pipeline_id,
            name=data.name,
            description=data.description,
            mode=data.mode,
            status=data.status,
            assign_account_ids=data.assign_account_ids,
            registry_environment=data.registry_environment,
            registry_project_key=data.registry_project_key,
            n8n_base_url=data.n8n_base_url,
            n8n_api_key=data.n8n_api_key,
            sync_settings=data.sync_settings,
            activate_workflow=data.activate_workflow,
            shared_secret=data.shared_secret,
            timeout_s=data.timeout_s,
        )
    except PipelineInstallError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    return {
        "ok": True,
        "pipeline": serialize_pipeline(result.pipeline),
        "workflow": result.workflow,
        "settings_sync": result.settings_sync,
        "assigned_account_ids": result.assigned_account_ids,
        "warnings": result.warnings,
    }


@router.post("/n8n/workflows/connect")
async def connect_existing_n8n_workflow(data: N8nWorkflowConnectRequest, db: Session = Depends(get_db)):
    try:
        connection = resolve_n8n_runtime_connection(
            db,
            registry_environment=data.registry_environment,
            registry_project_key=data.registry_project_key,
            n8n_base_url=data.n8n_base_url,
            n8n_api_key=data.n8n_api_key,
        )
        workflow = await n8n_request(
            base_url=connection.base_url,
            api_key=connection.api_key,
            method="GET",
            path=f"workflows/{data.workflow_id}",
        )
    except PipelineInstallError as exc:
        raise HTTPException(exc.status_code, exc.detail)
    except N8nWorkspaceError as exc:
        raise _workspace_safe_error(exc)

    workflow = _n8n_response_data(workflow)
    if not isinstance(workflow, dict):
        raise HTTPException(400, "n8n workflow response is invalid")
    if workflow.get("active") is not True:
        raise HTTPException(400, "n8n workflow must be active before connecting it")
    webhook_path = extract_webhook_path(workflow)
    if not webhook_path:
        raise HTTPException(400, "n8n workflow must contain a Webhook node with a path")
    mode = (data.mode or "sandbox").strip()
    if mode not in {"sandbox", "shadow", "live"}:
        raise HTTPException(400, f"Invalid pipeline mode: {mode}")
    status = _validate_status(data.status or "active")
    webhook_url = production_webhook_url(connection.base_url, webhook_path)
    smoke = await call_n8n_agent(
        _smoke_test_request(project_id=data.project_id, workflow_id=data.workflow_id, smoke_text=data.smoke_test_text),
        webhook_url=webhook_url,
        shared_secret=data.shared_secret,
        timeout_s=float(data.timeout_s or 20.0),
    )
    smoke_payload = _validate_smoke_result(smoke)

    existing_config: dict[str, Any] = {}
    pipeline: Optional[AgentPipeline] = None
    if data.pipeline_id is not None:
        pipeline = db.query(AgentPipeline).filter(AgentPipeline.id == int(data.pipeline_id)).first()
        if not pipeline:
            raise HTTPException(404, "Pipeline not found")
        existing_config = _loads_config(pipeline.config_json)
    if pipeline is None:
        pipeline = AgentPipeline(
            project_id=resolve_project_id(db, data.project_id),
            name=(data.name.strip() or workflow.get("name") or "n8n workflow"),
            type="n8n_webhook",
            status=status,
            config_json="{}",
        )
        db.add(pipeline)
        db.flush()
    resolved_project_id = pipeline.project_id if data.project_id is None and pipeline.project_id else resolve_project_id(db, data.project_id)
    pipeline.project_id = resolved_project_id
    pipeline.name = data.name.strip() or workflow.get("name") or pipeline.name
    pipeline.description = data.description if data.description is not None else (pipeline.description or "")
    pipeline.type = "n8n_webhook"
    pipeline.status = status
    config = _clean_config(
        {
            **existing_config,
            "n8n_base_url": connection.base_url,
            "workflow_id": str(workflow.get("id") or data.workflow_id),
            "workflow_name": workflow.get("name") or pipeline.name,
            "workflow_editor_url": workflow_editor_url(connection.base_url, str(workflow.get("id") or data.workflow_id)),
            "webhook_path": webhook_path,
            "webhook_url": webhook_url,
            "mode": mode,
            "timeout_s": float(data.timeout_s or 20.0),
            "shared_secret": data.shared_secret or existing_config.get("shared_secret", ""),
            "runtime_config_source": "agent_runtime_config_registry",
            "runtime_registry_environment": connection.environment,
            "runtime_registry_project_key": connection.project_key,
            "n8n_base_url_source": connection.base_url_source,
            "n8n_api_key_source": connection.api_key_source,
            "last_smoke_test_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "last_smoke_test_status": "passed",
            "last_smoke_test": smoke_payload,
        },
        existing=existing_config,
    )
    pipeline.config_json = json.dumps(config, ensure_ascii=False)
    pipeline.updated_at = datetime.utcnow()
    _write_version(db, pipeline, config)
    db.commit()
    db.refresh(pipeline)
    return {
        "ok": True,
        "pipeline": serialize_pipeline(pipeline),
        "workflow": _workflow_summary(workflow, base_url=connection.base_url),
        "smoke_test": smoke_payload,
    }


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
