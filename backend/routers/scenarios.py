from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.dify_knowledge import DifyKnowledgeConfig, DifyKnowledgeError, sync_scenarios_to_dify
from backend.models import ScenarioCard
from backend.projects import resolve_project_id
from backend.scenarios import (
    analyze_conversations_for_suggestions,
    group_scenarios,
    list_scenarios,
    mark_founder_research_pack_legacy,
    mine_scenario_from_conversation,
    seed_founder_research_pack,
    serialize_scenario,
)

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


class ScenarioCreate(BaseModel):
    project_id: int | None = None
    title: str
    intent: str
    trigger_summary: str
    recommended_reply: str
    avoid_reply: str = ""
    tags: str = ""
    status: str = "draft"


class ScenarioUpdate(BaseModel):
    title: str | None = None
    intent: str | None = None
    trigger_summary: str | None = None
    recommended_reply: str | None = None
    avoid_reply: str | None = None
    tags: str | None = None
    status: str | None = None


@router.get("/")
def scenarios(status: str | None = None, project_id: int | None = None, db: Session = Depends(get_db)):
    return [serialize_scenario(card) for card in list_scenarios(db, status=status, project_id=project_id)]


@router.get("/grouped")
def grouped_scenarios(status: str | None = None, project_id: int | None = None, db: Session = Depends(get_db)):
    return group_scenarios(list_scenarios(db, status=status, project_id=project_id))


@router.post("/seed-founder-research-pack")
def seed_founder_research_scenarios(project_id: int | None = None, db: Session = Depends(get_db)):
    return seed_founder_research_pack(db, project_id=resolve_project_id(db, project_id))


@router.post("/legacy/founder-research-pack")
def legacy_founder_research_scenarios(project_id: int | None = None, db: Session = Depends(get_db)):
    return mark_founder_research_pack_legacy(db, project_id=project_id)


@router.post("/analyze-conversations")
def analyze_conversations(limit: int = 50, project_id: int | None = None, db: Session = Depends(get_db)):
    return analyze_conversations_for_suggestions(db, limit=limit, project_id=project_id)


@router.get("/dify/status")
def dify_sync_status():
    config = DifyKnowledgeConfig.from_env()
    return {
        "configured": config.is_configured,
        "api_base_url": config.api_base_url,
        "dataset_id": config.dataset_id,
        "has_api_key": bool(config.api_key),
    }


@router.post("/dify/sync")
def sync_dify_knowledge(status: str = "active", limit: int | None = None, db: Session = Depends(get_db)):
    try:
        return sync_scenarios_to_dify(db, status=status, limit=limit)
    except DifyKnowledgeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/")
def create_scenario(data: ScenarioCreate, db: Session = Depends(get_db)):
    payload = data.model_dump()
    payload["project_id"] = resolve_project_id(db, data.project_id)
    card = ScenarioCard(**payload)
    db.add(card)
    db.commit()
    db.refresh(card)
    return serialize_scenario(card)


@router.patch("/{scenario_id}")
def update_scenario(scenario_id: int, data: ScenarioUpdate, db: Session = Depends(get_db)):
    card = db.query(ScenarioCard).filter(ScenarioCard.id == scenario_id).first()
    if not card:
        raise HTTPException(404, "Scenario not found")
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(card, key, value)
    db.commit()
    db.refresh(card)
    return serialize_scenario(card)


@router.post("/{scenario_id}/activate")
def activate_scenario(scenario_id: int, db: Session = Depends(get_db)):
    card = db.query(ScenarioCard).filter(ScenarioCard.id == scenario_id).first()
    if not card:
        raise HTTPException(404, "Scenario not found")
    card.status = "active"
    db.commit()
    db.refresh(card)
    return serialize_scenario(card)


@router.post("/mine")
def mine_scenario(conversation_id: int, db: Session = Depends(get_db)):
    return serialize_scenario(mine_scenario_from_conversation(db, conversation_id))
