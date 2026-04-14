import logging
import os
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from backend.runtime_config import app_auth_token

logger = logging.getLogger(__name__)

_ENC_PREFIX = "enc:v1:"


@lru_cache(maxsize=1)
def _get_fernet() -> Optional[Fernet]:
    key = (os.getenv("DATA_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode("utf-8"))
    except Exception as exc:
        logger.error("Invalid DATA_ENCRYPTION_KEY: %s", exc)
        return None


def encrypt_value(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    if value.startswith(_ENC_PREFIX):
        return value
    fernet = _get_fernet()
    if not fernet:
        return value
    token = fernet.encrypt(value.encode("utf-8")).decode("utf-8")
    return f"{_ENC_PREFIX}{token}"


def decrypt_value(value: Optional[str]) -> str:
    if not value:
        return ""
    if not value.startswith(_ENC_PREFIX):
        return value
    fernet = _get_fernet()
    if not fernet:
        logger.warning("Encrypted value present but DATA_ENCRYPTION_KEY is missing")
        return ""
    token = value[len(_ENC_PREFIX):]
    try:
        return fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt value with the provided DATA_ENCRYPTION_KEY")
        return ""


def has_secret(value: Optional[str]) -> bool:
    return bool(decrypt_value(value))


def require_http_auth(token: Optional[str]) -> bool:
    expected = app_auth_token()
    if not expected:
        return True
    return token == expected


def require_ws_auth(token: Optional[str]) -> bool:
    return require_http_auth(token)
