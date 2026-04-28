import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.models import AgentRun, Conversation

SECRET_KEYS = {"api_key", "openai_key", "anthropic_key", "client_secret", "refresh_token", "access_token", "password"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("[redacted]" if key.lower() in SECRET_KEYS else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and (value.startswith("sk-") or value.startswith("GOCSPX-")):
        return "[redacted]"
    return value


def _json_dumps(payload: Any) -> str:
    return json.dumps(_redact(payload), ensure_ascii=False, default=str)


def record_agent_run(
    db: Session,
    *,
    conversation_id: Optional[int],
    run_type: str,
    model: Optional[str],
    input_payload: dict,
    output_payload: Optional[dict] = None,
    status: str = "succeeded",
    error: Optional[str] = None,
) -> AgentRun:
    project_id = None
    if conversation_id is not None:
        project_id = db.query(Conversation.project_id).filter(Conversation.id == conversation_id).scalar()
    run = AgentRun(
        project_id=project_id,
        conversation_id=conversation_id,
        run_type=run_type,
        model=model,
        input_json=_json_dumps(input_payload),
        output_json=_json_dumps(output_payload or {}),
        status=status,
        error=error,
        completed_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def serialize_agent_run(run: AgentRun) -> dict:
    return {
        "id": run.id,
        "project_id": run.project_id,
        "conversation_id": run.conversation_id,
        "run_type": run.run_type,
        "model": run.model,
        "input": json.loads(run.input_json or "{}"),
        "output": json.loads(run.output_json or "{}"),
        "status": run.status,
        "error": run.error,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }
