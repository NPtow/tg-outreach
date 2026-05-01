from __future__ import annotations

import logging
import os
from typing import Optional

from backend.database import SessionLocal
from backend.models import Settings
from backend.security import decrypt_value

logger = logging.getLogger(__name__)


def settings_value(column: str, env_name: str, default: str = "") -> str:
    value = _read_settings_column(column, decrypt=False)
    if value:
        return value
    return (os.getenv(env_name) or default).strip()


def settings_secret(column: str, env_name: str, default: str = "") -> str:
    value = _read_settings_column(column, decrypt=True)
    if value:
        return value
    return (os.getenv(env_name) or default).strip()


def _read_settings_column(column: str, *, decrypt: bool) -> str:
    db = SessionLocal()
    try:
        settings = db.query(Settings).filter(Settings.id == 1).first()
        raw: Optional[str] = getattr(settings, column, "") if settings else ""
        if not raw:
            return ""
        return decrypt_value(raw).strip() if decrypt else str(raw).strip()
    except Exception as exc:
        logger.debug("Failed to read settings column %s: %s", column, exc)
        return ""
    finally:
        db.close()
