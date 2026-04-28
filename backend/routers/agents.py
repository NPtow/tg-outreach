from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.agent_runtime import serialize_agent_run
from backend.database import get_db
from backend.models import AgentRun

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("/runs")
def list_agent_runs(
    conversation_id: int | None = None,
    run_type: str | None = None,
    project_id: int | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(AgentRun)
    if project_id is not None:
        query = query.filter(AgentRun.project_id == int(project_id))
    if conversation_id is not None:
        query = query.filter(AgentRun.conversation_id == conversation_id)
    if run_type:
        query = query.filter(AgentRun.run_type == run_type)
    runs = query.order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(100).all()
    return [serialize_agent_run(run) for run in runs]
