from sqlalchemy.orm import Session

from backend.models import (
    AgentPipeline,
    AgentRun,
    Campaign,
    Contact,
    ContactBatch,
    Conversation,
    Project,
    PromptTemplate,
    ScenarioCard,
    ScheduledMeeting,
)

DEFAULT_PROJECT_NAME = "Default Project"


def ensure_default_project(db: Session) -> Project:
    project = db.query(Project).order_by(Project.id.asc()).first()
    if project:
        return project
    project = Project(name=DEFAULT_PROJECT_NAME, description="Auto-created local workspace", status="active")
    db.add(project)
    db.flush()
    return project


def resolve_project_id(db: Session, project_id: int | None = None) -> int:
    if project_id is not None:
        project = db.query(Project).filter(Project.id == int(project_id)).first()
        if project:
            return project.id
    return ensure_default_project(db).id


def assign_existing_rows_to_default_project(db: Session) -> int:
    project_id = ensure_default_project(db).id
    models = [
        AgentPipeline,
        AgentRun,
        Campaign,
        Contact,
        ContactBatch,
        Conversation,
        PromptTemplate,
        ScenarioCard,
        ScheduledMeeting,
    ]
    updated = 0
    for model in models:
        if not hasattr(model, "project_id"):
            continue
        count = db.query(model).filter(model.project_id.is_(None)).update(
            {"project_id": project_id},
            synchronize_session=False,
        )
        updated += count or 0
    return updated
