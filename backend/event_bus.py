import json
from typing import Any

from backend.database import SessionLocal
from backend.models import RuntimeEvent


def publish_runtime_event(payload: dict[str, Any], event_type: str = "runtime") -> int:
    db = SessionLocal()
    try:
        event = RuntimeEvent(event_type=event_type, payload=json.dumps(payload, default=str))
        db.add(event)
        db.commit()
        db.refresh(event)
        return event.id
    finally:
        db.close()


def get_runtime_events(after_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(RuntimeEvent)
            .filter(RuntimeEvent.id > after_id)
            .order_by(RuntimeEvent.id.asc())
            .limit(limit)
            .all()
        )
        result = []
        for row in rows:
            result.append(
                {
                    "id": row.id,
                    "event_type": row.event_type,
                    "payload": json.loads(row.payload),
                    "created_at": row.created_at,
                }
            )
        return result
    finally:
        db.close()


def get_latest_runtime_event_id() -> int:
    db = SessionLocal()
    try:
        latest = db.query(RuntimeEvent).order_by(RuntimeEvent.id.desc()).first()
        return latest.id if latest else 0
    finally:
        db.close()
