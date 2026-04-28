from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.sandbox import replay_conversation_n8n_sandbox, replay_conversation_sandbox

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


class SandboxReplayRequest(BaseModel):
    conversation_id: int
    candidate_prompt: str = ""
    model: str = "local-heuristic-agent"
    dry_run_tools: bool = True
    engine: str = "local"


@router.post("/replay")
async def replay(data: SandboxReplayRequest, db: Session = Depends(get_db)):
    if data.engine == "n8n":
        return await replay_conversation_n8n_sandbox(
            db,
            conversation_id=data.conversation_id,
            candidate_prompt=data.candidate_prompt,
            model=data.model or "n8n-agent",
            dry_run_tools=data.dry_run_tools,
        )
    return replay_conversation_sandbox(
        db,
        conversation_id=data.conversation_id,
        candidate_prompt=data.candidate_prompt,
        model=data.model,
        dry_run_tools=data.dry_run_tools,
    )
