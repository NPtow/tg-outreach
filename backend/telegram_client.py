"""
Telethon client manager + Campaign worker.
"""
import asyncio
import base64
import json
import logging
import os
import random
import re
import shutil
import tempfile
import time
import zipfile
from datetime import datetime, timedelta
from typing import Dict, Optional

import httpx
from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
    UserPrivacyRestrictedError,
    UsernameNotOccupiedError,
    UsernameInvalidError,
    AuthKeyDuplicatedError,
    AuthKeyUnregisteredError,
    UserDeactivatedBanError,
)
from telethon.sessions import StringSession
from telethon.tl.types import User

from backend.database import SessionLocal
from backend.models import (
    Account, Campaign, CampaignTarget, Conversation,
    DoNotContact, Message, ProxyPool, Settings,
)
from backend.proxy_utils import detect_proxy_type, normalize_proxy_type, telethon_proxy_type
from backend.security import decrypt_value, encrypt_value, has_secret

logger = logging.getLogger(__name__)

# account_id -> TelegramClient
_clients: Dict[int, TelegramClient] = {}
# account_id -> asyncio.Task
_tasks: Dict[int, asyncio.Task] = {}
# campaign_id -> asyncio.Task
_campaign_tasks: Dict[int, asyncio.Task] = {}
# conversation_id -> asyncio.Task
_pending_auto_reply_tasks: Dict[int, asyncio.Task] = {}

SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

DEFAULT_API_ID = 2040
DEFAULT_API_HASH = "b18441a1ff607e10a989891a5462e627"
AUTO_REPLY_DELAY_MIN_S = 20.0
AUTO_REPLY_DELAY_MAX_S = 45.0
CAMPAIGN_ENTITY_TIMEOUT_S = 20.0
CAMPAIGN_SEND_TIMEOUT_S = 30.0

_ws_broadcast = None
_MSK_OFFSET = timedelta(hours=3)
_USERNAME_PAGE_CACHE: Dict[str, tuple[float, bool]] = {}
_SUPPORTED_CONNECTION_STATES = {"offline", "online", "connecting", "degraded", "reauth_required"}
_SUPPORTED_ELIGIBILITY_STATES = {"eligible", "blocked_proxy", "blocked_auth", "blocked_runtime"}
_TRANSIENT_LIMIT_ERROR_CODES = {"PEER_FLOOD", "FLOOD_WAIT", "USERNAME_RESOLUTION_RESTRICTED"}


def set_ws_broadcast(fn):
    global _ws_broadcast
    _ws_broadcast = fn


def _session_path(account_id: int) -> str:
    return os.path.join(SESSIONS_DIR, f"account_{account_id}")


def _as_str(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    return str(value)


def _decrypt_or_plain(value) -> str:
    text = _as_str(value)
    if not text:
        return ""
    return decrypt_value(text) or text


def _debug_shape(value) -> str:
    text = _as_str(value)
    return f"{type(value).__name__}/len={len(text)}"


def _debug_proxy_shape(proxy) -> str:
    if not proxy:
        return "none"
    return (
        f"{proxy.get('proxy_type')}@{proxy.get('addr')}:{proxy.get('port')}"
        f" user={'yes' if proxy.get('username') else 'no'}"
        f" pass={'yes' if proxy.get('password') else 'no'}"
        f" rdns={proxy.get('rdns')}"
    )


def _looks_like_api_hash(value: str) -> bool:
    text = _as_str(value).strip()
    return len(text) == 32 and all(ch in "0123456789abcdefABCDEF" for ch in text)


def _build_proxy(account: Account):
    proxy_host = _as_str(getattr(account, "proxy_host", None)).strip()
    proxy_port = getattr(account, "proxy_port", None)
    if not proxy_host or not proxy_port:
        return None
    proxy_user = _as_str(getattr(account, "proxy_user", None)).strip() or None
    proxy_pass = _decrypt_or_plain(getattr(account, "proxy_pass", None)) or None
    return {
        "proxy_type": telethon_proxy_type(getattr(account, "proxy_type", None)),
        "addr": proxy_host,
        "port": int(proxy_port),
        "username": proxy_user,
        "password": proxy_pass,
        "rdns": True,
    }


def _client_api_credentials(account: Account) -> tuple[int, str]:
    try:
        app_id = int(_as_str(getattr(account, "app_id", None), str(DEFAULT_API_ID)))
    except (TypeError, ValueError):
        logger.warning(
            "api_credentials_diag account_id=%s bad_app_id=%s using_default=yes",
            getattr(account, "id", None),
            _debug_shape(getattr(account, "app_id", None)),
        )
        app_id = DEFAULT_API_ID

    raw_app_hash = getattr(account, "app_hash", None)
    app_hash = _as_str(_decrypt_or_plain(raw_app_hash)).strip()
    if not _looks_like_api_hash(app_hash):
        logger.warning(
            "api_credentials_diag account_id=%s bad_app_hash=%s raw_app_hash=%s using_default=yes",
            getattr(account, "id", None),
            _debug_shape(app_hash),
            _debug_shape(raw_app_hash),
        )
        app_hash = DEFAULT_API_HASH
    return app_id, app_hash


def _client_device_kwargs(account: Account) -> dict:
    return {
        "device_model": _as_str(getattr(account, "device_model", None), "Desktop") or "Desktop",
        "system_version": _as_str(getattr(account, "system_version", None), "Windows 10") or "Windows 10",
        "app_version": _as_str(getattr(account, "app_version", None), "6.7.5 x64") or "6.7.5 x64",
        "lang_code": _as_str(getattr(account, "lang_code", None), "ru") or "ru",
        "system_lang_code": "ru-RU",
    }


def _make_telegram_client(account: Account, session) -> TelegramClient:
    app_id, app_hash = _client_api_credentials(account)
    client = TelegramClient(
        session,
        app_id,
        app_hash,
        proxy=_build_proxy(account),
        **_client_device_kwargs(account),
    )
    if getattr(client, "api_hash", None) != app_hash:
        logger.warning(
            "api_hash_coerce_diag account_id=%s client_api_hash=%s expected_api_hash=%s",
            getattr(account, "id", None),
            _debug_shape(getattr(client, "api_hash", None)),
            _debug_shape(app_hash),
        )
        client.api_hash = app_hash
    return client


def _make_client(account: Account) -> TelegramClient:
    session_string = _decrypt_or_plain(getattr(account, "session_string", None))
    if session_string:
        session = StringSession(session_string)
    else:
        session = _session_path(account.id)
    return _make_telegram_client(account, session)


def _utcnow() -> datetime:
    return datetime.utcnow()


def _derive_session_state(account: Account) -> str:
    if decrypt_value(account.session_string):
        return "valid"
    if decrypt_value(account.tdata_blob):
        return "expired"
    return "missing"


def _runtime_connection_state(account: Account) -> str:
    """Prefer local runtime, but fall back to persisted state in split/multi-instance deployments."""
    if account.id in _clients:
        return "online"
    stored_state = account.connection_state or "offline"
    if stored_state in _SUPPORTED_CONNECTION_STATES:
        return stored_state
    return "offline"


def _compute_eligibility(account: Account) -> str:
    if (account.proxy_state or "unknown") in {"failed", "timeout", "auth_failed"}:
        return "blocked_proxy"
    if getattr(account, "needs_reauth", False) or (account.session_state or "missing") in {
        "missing",
        "expired",
        "recovery_failed",
    }:
        return "blocked_auth"
    if _runtime_connection_state(account) == "online":
        return "eligible"
    return "blocked_runtime"


def _account_updated_at(account: Account) -> Optional[datetime]:
    timestamps = [
        account.last_error_at,
        account.last_connect_at,
        account.last_seen_online_at,
        account.last_proxy_check_at,
    ]
    timestamps = [ts for ts in timestamps if ts]
    return max(timestamps) if timestamps else None


def _clear_legacy_account_limit_state(account: Account) -> bool:
    dirty = False
    if (account.connection_state or "offline") not in _SUPPORTED_CONNECTION_STATES:
        account.connection_state = "offline"
        dirty = True
    if account.eligibility_state and account.eligibility_state not in _SUPPORTED_ELIGIBILITY_STATES:
        account.eligibility_state = _compute_eligibility(account)
        dirty = True
    if (account.last_error_code or "") in _TRANSIENT_LIMIT_ERROR_CODES:
        account.last_error_code = None
        account.last_error_message = None
        account.last_error_at = None
        dirty = True
    return dirty


def _public_error_fields(account: Account) -> tuple[Optional[str], Optional[str], Optional[datetime]]:
    if (account.last_error_code or "") in _TRANSIENT_LIMIT_ERROR_CODES:
        return None, None, None
    return account.last_error_code, account.last_error_message, account.last_error_at


def build_account_status(account: Account) -> dict:
    connection_state = _runtime_connection_state(account)
    proxy_state = account.proxy_state or "unknown"
    session_state = account.session_state or _derive_session_state(account)
    public_error_code, public_error_message, public_error_at = _public_error_fields(account)
    reason_error_code = public_error_code or ""
    needs_reauth = bool(getattr(account, "needs_reauth", False))

    proxy_ok = proxy_state not in {"failed", "timeout", "auth_failed"}
    session_ok = not needs_reauth and session_state not in {"missing", "expired", "recovery_failed"}
    is_online = connection_state == "online"
    can_receive = bool(is_online and proxy_ok and session_ok)
    can_auto_reply = bool(can_receive and getattr(account, "auto_reply", False))
    can_start_outreach = bool(can_receive)
    status = "working" if can_receive else "not_working"

    if status == "working":
        reason = "Аккаунт онлайн и принимает сообщения"
    elif reason_error_code == "UserDeactivatedBanError":
        reason = "Telegram деактивировал аккаунт"
    elif reason_error_code in {"AuthKeyDuplicatedError", "AuthKeyUnregisteredError"}:
        reason = "Сессия Telegram отозвана, нужна повторная авторизация"
    elif needs_reauth or session_state in {"missing", "expired", "recovery_failed"}:
        reason = "Нужна повторная авторизация"
    elif proxy_state == "auth_failed":
        reason = "Прокси не принял логин или пароль"
    elif proxy_state == "timeout":
        reason = "Прокси не отвечает вовремя"
    elif proxy_state == "failed":
        reason = "Прокси не работает"
    elif connection_state == "connecting":
        reason = "Аккаунт подключается к Telegram"
    elif connection_state == "degraded" or reason_error_code == "CONNECT_FAILED":
        reason = "Не удалось подключить Telegram-клиент"
    else:
        reason = "Telegram-клиент не подключён"

    return {
        "status": status,
        "reason": reason,
        "updated_at": _account_updated_at(account),
        "is_online": is_online,
        "can_receive": can_receive,
        "can_auto_reply": can_auto_reply,
        "can_start_outreach": can_start_outreach,
    }


def serialize_public_account(account: Account) -> dict:
    status = build_account_status(account)
    eligibility_state = _compute_eligibility(account)
    return {
        "id": account.id,
        "name": account.name,
        "phone": account.phone,
        "app_id": account.app_id,
        "is_active": status["is_online"],
        "status": status["status"],
        "reason": status["reason"],
        "is_online": status["is_online"],
        "can_receive": status["can_receive"],
        "can_auto_reply": status["can_auto_reply"],
        "can_start_outreach": status["can_start_outreach"],
        "updated_at": status["updated_at"],
        "auto_reply": account.auto_reply,
        "tdata_stored": has_secret(account.tdata_blob),
        "prompt_template_id": account.prompt_template_id,
        "created_at": account.created_at,
        "proxy_host": account.proxy_host or "",
        "proxy_port": account.proxy_port,
        "proxy_type": account.proxy_type or "SOCKS5",
        "proxy_user": account.proxy_user or "",
        # compat fields for frontend
        "needs_reauth": bool(getattr(account, "needs_reauth", False)),
        "connection_state": _runtime_connection_state(account),
        "session_state": account.session_state or _derive_session_state(account),
        "proxy_state": account.proxy_state or "unknown",
        "eligibility_state": eligibility_state,
        "session_source": account.session_source or "",
        "last_error_code": account.last_error_code,
        "last_error_message": account.last_error_message,
        "last_connect_at": account.last_connect_at,
        "last_proxy_check_at": account.last_proxy_check_at,
        "last_seen_online_at": account.last_seen_online_at,
        "proxy_last_rtt_ms": account.proxy_last_rtt_ms,
    }


def get_public_account(account_id: int) -> dict:
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        return serialize_public_account(acc) if acc else {}
    finally:
        db.close()


def _serialize_runtime_state(account: Account) -> dict:
    last_error_code, last_error_message, last_error_at = _public_error_fields(account)
    return {
        "account_id": account.id,
        "connection_state": _runtime_connection_state(account),
        "proxy_state": account.proxy_state or "unknown",
        "session_state": account.session_state or "missing",
        "eligibility_state": _compute_eligibility(account),
        "last_error_code": last_error_code,
        "last_error_message": last_error_message,
        "last_error_at": last_error_at,
        "last_proxy_check_at": account.last_proxy_check_at,
        "last_connect_at": account.last_connect_at,
        "last_seen_online_at": account.last_seen_online_at,
        "session_source": account.session_source or "",
        "proxy_last_rtt_ms": account.proxy_last_rtt_ms,
    }


def _persist_account_runtime_state(account_id: int, **updates) -> dict:
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if not acc:
            return {}
        for key, value in updates.items():
            setattr(acc, key, value)
        if "session_state" not in updates:
            acc.session_state = _derive_session_state(acc)
        acc.eligibility_state = _compute_eligibility(acc)
        db.commit()
        db.refresh(acc)
        return _serialize_runtime_state(acc)
    finally:
        db.close()


def _mark_error(account_id: int, code: str, message: str, **extra) -> dict:
    return _persist_account_runtime_state(
        account_id,
        last_error_code=code,
        last_error_message=message,
        last_error_at=_utcnow(),
        **extra,
    )


def _clear_error(account_id: int, **extra) -> dict:
    return _persist_account_runtime_state(
        account_id,
        last_error_code=None,
        last_error_message=None,
        last_error_at=None,
        **extra,
    )


async def _public_username_exists(username: Optional[str]) -> Optional[bool]:
    normalized = (username or "").strip().lstrip("@")
    if not normalized:
        return False

    now = time.time()
    cached = _USERNAME_PAGE_CACHE.get(normalized.lower())
    if cached and now - cached[0] < 600:
        return cached[1]

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.get(f"https://t.me/{normalized}")
        html = response.text
        exists = "tgme_action_button_new" in html and "Telegram – a new era of messaging" not in html
        _USERNAME_PAGE_CACHE[normalized.lower()] = (now, exists)
        return exists
    except Exception as exc:
        logger.warning("Public username check failed for %s: %s", normalized, exc)
        return None


def _persist_detected_proxy_type(account_id: int, proxy_type: str) -> None:
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if not acc:
            return
        detected_type = normalize_proxy_type(proxy_type)
        changed = False
        if (acc.proxy_type or "").upper() != detected_type:
            acc.proxy_type = detected_type
            changed = True

        if acc.proxy_host and acc.proxy_port:
            proxy_query = db.query(ProxyPool).filter(
                ProxyPool.host == acc.proxy_host,
                ProxyPool.port == int(acc.proxy_port),
            )
            if acc.proxy_user:
                proxy_query = proxy_query.filter(ProxyPool.username == acc.proxy_user)
            for proxy in proxy_query.all():
                if (proxy.proxy_type or "").upper() != detected_type:
                    proxy.proxy_type = detected_type
                    changed = True

        if changed:
            db.commit()
            logger.info("proxy_type_autodetect account_id=%s detected_type=%s", account_id, detected_type)
    finally:
        db.close()


async def _proxy_connectivity_check(account: Account) -> dict:
    started = time.perf_counter()
    target_host = "149.154.167.50"
    target_port = 443
    try:
        proxy_host = _as_str(getattr(account, "proxy_host", None)).strip()
        proxy_port = getattr(account, "proxy_port", None)
        if proxy_host and proxy_port:
            detected = await detect_proxy_type(
                host=proxy_host,
                port=int(proxy_port),
                username=_as_str(getattr(account, "proxy_user", None)).strip() or None,
                password=_decrypt_or_plain(getattr(account, "proxy_pass", None)) or None,
                preferred_type=_as_str(getattr(account, "proxy_type", None), "SOCKS5"),
            )
            if not detected.get("ok"):
                attempts = detected.get("attempts", [])
                timed_out = any(attempt.get("error_type") == "TimeoutError" for attempt in attempts)
                message = ", ".join(
                    f"{attempt.get('proxy_type')}={attempt.get('error_type') or 'failed'}"
                    for attempt in attempts
                ) or "Proxy connection failed"
                state = _mark_error(
                    account.id,
                    "PROXY_TIMEOUT" if timed_out else "PROXY_FAILED",
                    message,
                    proxy_state="timeout" if timed_out else "failed",
                    last_proxy_check_at=_utcnow(),
                )
                return {
                    "ok": False,
                    "proxy_state": "timeout" if timed_out else "failed",
                    "error": message,
                    "state": state,
                }
            if detected.get("proxy_type"):
                account.proxy_type = detected["proxy_type"]
                _persist_detected_proxy_type(account.id, detected["proxy_type"])
            rtt_ms = int(detected.get("rtt_ms") or (time.perf_counter() - started) * 1000)
        else:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(target_host, target_port), timeout=10)
            writer.close()
            await writer.wait_closed()
            rtt_ms = int((time.perf_counter() - started) * 1000)
        state = _clear_error(
            account.id,
            proxy_state="ok",
            last_proxy_check_at=_utcnow(),
            proxy_last_rtt_ms=rtt_ms,
        )
        return {
            "ok": True,
            "proxy_state": "ok",
            "rtt_ms": rtt_ms,
            "state": state,
            "detected_proxy_type": getattr(account, "proxy_type", None),
        }
    except asyncio.TimeoutError:
        state = _mark_error(
            account.id,
            "PROXY_TIMEOUT",
            "Proxy connection timed out",
            proxy_state="timeout",
            last_proxy_check_at=_utcnow(),
        )
        return {"ok": False, "proxy_state": "timeout", "error": "Proxy connection timed out", "state": state}
    except Exception as exc:
        state = _mark_error(
            account.id,
            "PROXY_FAILED",
            str(exc),
            proxy_state="failed",
            last_proxy_check_at=_utcnow(),
        )
        return {"ok": False, "proxy_state": "failed", "error": str(exc), "state": state}


async def _save_session_string(account_id: int, client: TelegramClient):
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if acc:
            acc.session_string = encrypt_value(client.session.save())
            acc.session_state = "valid"
            acc.session_source = acc.session_source or "session_string"
            db.commit()
    finally:
        db.close()


async def save_session_now(account_id: int) -> bool:
    """Explicitly flush the current in-memory session to DB. Called from /save-session endpoint."""
    client = _clients.get(account_id)
    if not client:
        return False
    await _save_session_string(account_id, client)
    logger.info(f"Session saved for account {account_id}")
    return True


async def proxy_test_account(account_id: int) -> dict:
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if not acc:
            return {"ok": False, "error": "Account not found"}
    finally:
        db.close()
    result = await _proxy_connectivity_check(acc)
    if _ws_broadcast:
        await _ws_broadcast({"event": "account_status", "account_id": account_id, "state": result.get("state", {})})
    return {
        "ok": result.get("ok", False),
        "proxy_state": result.get("proxy_state", "unknown"),
        "rtt_ms": result.get("rtt_ms"),
        "error": result.get("error"),
        "detected_proxy_type": result.get("detected_proxy_type"),
        "account": get_public_account(account_id),
    }


def _resolve_prompt(settings: Settings, account: Account, campaign: Optional[Campaign]) -> str:
    """
    Resolve the active system prompt with priority:
    campaign.prompt_template > account.prompt_template > settings.system_prompt
    """
    if campaign and campaign.prompt_template_id and campaign.prompt_template:
        return campaign.prompt_template.system_prompt
    if account and account.prompt_template_id and account.prompt_template:
        return account.prompt_template.system_prompt
    return settings.system_prompt if settings else ""


def _is_in_dnc(db, username: Optional[str], tg_user_id: Optional[str]) -> bool:
    q = db.query(DoNotContact)
    if username:
        entry = q.filter(DoNotContact.username == username).first()
        if entry:
            return True
    if tg_user_id:
        entry = q.filter(DoNotContact.tg_user_id == tg_user_id).first()
        if entry:
            return True
    return False


def _add_to_dnc(db, username: Optional[str], tg_user_id: Optional[str], reason: str):
    if not username and not tg_user_id:
        return
    existing = _is_in_dnc(db, username, tg_user_id)
    if not existing:
        db.add(DoNotContact(username=username, tg_user_id=tg_user_id, reason=reason))
        db.commit()


def _find_source_campaign(db, account_id: int, username: Optional[str]) -> Optional[int]:
    """Find campaign that sent a message to this username from this account."""
    if not username:
        return None
    normalized = username.strip().lstrip("@")
    target = db.query(CampaignTarget).filter(
        CampaignTarget.account_id == account_id,
        CampaignTarget.username == normalized,
        CampaignTarget.status == "sent",
    ).order_by(CampaignTarget.sent_at.desc()).first()
    return target.campaign_id if target else None


async def _emit_runtime_note(event: str, **payload):
    logger.info("%s: %s", event, payload)
    if _ws_broadcast:
        await _ws_broadcast({"event": event, **payload})


async def _broadcast_conversation_message(conv: Conversation, text: str, *, paused_for_review: bool = False):
    if not _ws_broadcast:
        return
    payload = {
        "event": "new_message",
        "conversation_id": conv.id,
        "account_id": conv.account_id,
        "text": text,
        "unread_count": conv.unread_count or 0,
        "is_hot": bool(conv.is_hot),
    }
    if paused_for_review:
        payload["paused_for_review"] = True
    await _ws_broadcast(payload)


def _ensure_outreach_conversation(
    db,
    *,
    account_id: int,
    tg_user_id: str,
    tg_username: Optional[str] = None,
    tg_first_name: Optional[str] = None,
    tg_last_name: Optional[str] = None,
    source_campaign_id: Optional[int] = None,
) -> Conversation:
    conv = db.query(Conversation).filter(
        Conversation.account_id == account_id,
        Conversation.tg_user_id == tg_user_id,
    ).first()
    if not conv:
        conv = Conversation(
            account_id=account_id,
            tg_user_id=tg_user_id,
            tg_username=tg_username or "",
            tg_first_name=tg_first_name or "",
            tg_last_name=tg_last_name or "",
            source_campaign_id=source_campaign_id,
            unread_count=0,
        )
        db.add(conv)
        db.flush()
        return conv

    if tg_username and not conv.tg_username:
        conv.tg_username = tg_username
    if tg_first_name and not conv.tg_first_name:
        conv.tg_first_name = tg_first_name
    if tg_last_name and not conv.tg_last_name:
        conv.tg_last_name = tg_last_name
    if source_campaign_id and not conv.source_campaign_id:
        conv.source_campaign_id = source_campaign_id
    return conv


def _record_outreach_message(
    db,
    *,
    conversation: Conversation,
    role: str,
    text: str,
    increment_unread: bool = False,
) -> Message:
    if increment_unread:
        conversation.unread_count = (conversation.unread_count or 0) + 1
    message = Message(conversation_id=conversation.id, role=role, text=text)
    db.add(message)
    db.flush()
    conversation.last_message = text
    conversation.last_message_at = _utcnow()
    return message


def _auto_reply_delay_seconds() -> float:
    return random.uniform(AUTO_REPLY_DELAY_MIN_S, AUTO_REPLY_DELAY_MAX_S)


def _log_auto_reply_event(event: str, **fields):
    parts = []
    for key, value in fields.items():
        if isinstance(value, float):
            rendered = f"{value:.2f}"
        elif isinstance(value, datetime):
            rendered = value.isoformat()
        else:
            rendered = _as_str(value)
        parts.append(f"{key}={rendered}")
    logger.info("auto_reply_%s %s", event, " ".join(parts))


def _latest_user_message_id(db, conversation_id: int) -> Optional[int]:
    row = (
        db.query(Message.id)
        .filter(Message.conversation_id == conversation_id, Message.role == "user")
        .order_by(Message.id.desc())
        .first()
    )
    return row[0] if row else None


def _load_auto_reply_context(db, account_id: int, conversation_id: int, trigger_message_id: int) -> Optional[dict]:
    settings = db.query(Settings).filter(Settings.id == 1).first()
    account = db.query(Account).filter(Account.id == account_id).first()
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id,
        Conversation.account_id == account_id,
    ).first()

    if not settings or not account or not conv:
        return None
    if conv.status != "active":
        return None
    if not account.auto_reply or not settings.auto_reply_enabled:
        return None
    if _latest_user_message_id(db, conversation_id) != trigger_message_id:
        return None

    provider = getattr(settings, "provider", "openai") or "openai"
    openai_key = decrypt_value(settings.openai_key) if settings else ""
    anthropic_key = decrypt_value(getattr(settings, "anthropic_key", "")) if settings else ""
    if provider in ("openai", "openrouter") and not openai_key:
        return None
    if provider == "anthropic" and not anthropic_key:
        return None

    source_campaign = None
    if conv.source_campaign_id:
        source_campaign = db.query(Campaign).filter(Campaign.id == conv.source_campaign_id).first()
        if source_campaign and source_campaign.max_messages:
            assistant_count = db.query(Message).filter(
                Message.conversation_id == conv.id,
                Message.role == "assistant",
            ).count()
            if assistant_count >= source_campaign.max_messages:
                return None
        if source_campaign and source_campaign.prompt_template_id:
            from backend.models import PromptTemplate
            source_campaign.prompt_template = db.query(PromptTemplate).filter(
                PromptTemplate.id == source_campaign.prompt_template_id
            ).first()

    if account.prompt_template_id:
        from backend.models import PromptTemplate
        account.prompt_template = db.query(PromptTemplate).filter(
            PromptTemplate.id == account.prompt_template_id
        ).first()

    history = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(settings.context_messages)
        .all()
    )
    history = list(reversed(history))

    return {
        "settings": settings,
        "account": account,
        "conversation": conv,
        "provider": provider,
        "openai_key": openai_key or "",
        "anthropic_key": anthropic_key or "",
        "source_campaign": source_campaign,
        "history": history,
    }


def _schedule_auto_reply(account_id: int, conversation_id: int, tg_user_id: str, trigger_message_id: int) -> float:
    pending = _pending_auto_reply_tasks.get(conversation_id)
    if pending and not pending.done():
        pending.cancel()
        _log_auto_reply_event(
            "cancelled",
            account_id=account_id,
            conversation_id=conversation_id,
            trigger_message_id=getattr(pending, "trigger_message_id", ""),
            replacement_trigger_message_id=trigger_message_id,
            cancelled_at=_utcnow(),
        )

    scheduled_at = _utcnow()
    delay_s = _auto_reply_delay_seconds()
    send_after_at = scheduled_at + timedelta(seconds=delay_s)
    task = asyncio.create_task(
        _run_scheduled_auto_reply(
            account_id=account_id,
            conversation_id=conversation_id,
            tg_user_id=tg_user_id,
            trigger_message_id=trigger_message_id,
            delay_s=delay_s,
            scheduled_at=scheduled_at,
        )
    )
    task.trigger_message_id = trigger_message_id
    _pending_auto_reply_tasks[conversation_id] = task

    def _cleanup(done_task):
        if _pending_auto_reply_tasks.get(conversation_id) is done_task:
            _pending_auto_reply_tasks.pop(conversation_id, None)

    task.add_done_callback(_cleanup)
    _log_auto_reply_event(
        "scheduled",
        account_id=account_id,
        conversation_id=conversation_id,
        trigger_message_id=trigger_message_id,
        delay_s=delay_s,
        scheduled_at=scheduled_at,
        send_after_at=send_after_at,
    )
    return delay_s


async def _run_scheduled_auto_reply(
    account_id: int,
    conversation_id: int,
    tg_user_id: str,
    trigger_message_id: int,
    delay_s: float,
    scheduled_at: datetime,
):
    try:
        await asyncio.sleep(delay_s)

        db = SessionLocal()
        try:
            context = _load_auto_reply_context(db, account_id, conversation_id, trigger_message_id)
        finally:
            db.close()
        if not context:
            _log_auto_reply_event(
                "skipped",
                account_id=account_id,
                conversation_id=conversation_id,
                trigger_message_id=trigger_message_id,
                reason="context_invalid_after_delay",
                scheduled_at=scheduled_at,
                skipped_at=_utcnow(),
            )
            return

        system_prompt = _resolve_prompt(
            context["settings"],
            context["account"],
            context["source_campaign"],
        )

        from backend.gpt_handler import generate_reply

        reply = await generate_reply(
            provider=context["provider"],
            openai_key=context["openai_key"],
            anthropic_key=context["anthropic_key"],
            base_url=getattr(context["settings"], "base_url", "") or "",
            model=context["settings"].model,
            system_prompt=system_prompt,
            history=context["history"],
        )
        if not reply:
            _log_auto_reply_event(
                "skipped",
                account_id=account_id,
                conversation_id=conversation_id,
                trigger_message_id=trigger_message_id,
                reason="empty_reply",
                scheduled_at=scheduled_at,
                skipped_at=_utcnow(),
            )
            await _emit_runtime_note(
                "auto_reply_skipped",
                account_id=account_id,
                conversation_id=conversation_id,
                reason="AI не вернул ответ",
            )
            return

        db = SessionLocal()
        try:
            if not _load_auto_reply_context(db, account_id, conversation_id, trigger_message_id):
                _log_auto_reply_event(
                    "skipped",
                    account_id=account_id,
                    conversation_id=conversation_id,
                    trigger_message_id=trigger_message_id,
                    reason="stale_or_disabled_before_send",
                    scheduled_at=scheduled_at,
                    skipped_at=_utcnow(),
                )
                return
        finally:
            db.close()

        sending_at = _utcnow()
        _log_auto_reply_event(
            "sending",
            account_id=account_id,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            delay_s=delay_s,
            scheduled_at=scheduled_at,
            sending_at=sending_at,
        )
        send_result = await send_manual_message(account_id, tg_user_id, conversation_id, reply)
        if not send_result.get("ok"):
            _log_auto_reply_event(
                "skipped",
                account_id=account_id,
                conversation_id=conversation_id,
                trigger_message_id=trigger_message_id,
                reason=send_result.get("error") or "send_failed",
                scheduled_at=scheduled_at,
                skipped_at=_utcnow(),
            )
            await _emit_runtime_note(
                "auto_reply_skipped",
                account_id=account_id,
                conversation_id=conversation_id,
                reason=send_result.get("error") or "Не удалось отправить AI-ответ",
            )
            return

        _log_auto_reply_event(
            "sent",
            account_id=account_id,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            delay_s=delay_s,
            scheduled_at=scheduled_at,
            sending_at=sending_at,
            sent_at=_utcnow(),
            waited_s=(sending_at - scheduled_at).total_seconds(),
        )
    except asyncio.CancelledError:
        _log_auto_reply_event(
            "cancelled",
            account_id=account_id,
            conversation_id=conversation_id,
            trigger_message_id=trigger_message_id,
            scheduled_at=scheduled_at,
            cancelled_at=_utcnow(),
        )
        raise
    except Exception as exc:
        logger.error("Scheduled auto-reply failed for conversation %s: %s", conversation_id, exc, exc_info=True)


async def _handle_message(account_id: int, event):
    if getattr(event, "is_out", None) or getattr(getattr(event, "message", None), "out", False):
        return
    sender: User = await event.get_sender()
    if not sender or sender.bot:
        return

    db = SessionLocal()
    try:
        settings = db.query(Settings).filter(Settings.id == 1).first()
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return

        tg_user_id = str(sender.id)
        username = sender.username or None
        text = event.message.text or ""

        # ── DNC check ──
        if _is_in_dnc(db, username, tg_user_id):
            logger.info(f"Ignoring message from DNC contact {username or tg_user_id}")
            return

        # ── Get or create conversation ──
        conv = db.query(Conversation).filter(
            Conversation.account_id == account_id,
            Conversation.tg_user_id == tg_user_id
        ).first()

        source_campaign_id = conv.source_campaign_id if conv else None
        if not source_campaign_id and username:
            source_campaign_id = _find_source_campaign(db, account_id, username)

        # Inbox stores outreach conversations only.
        if conv is None and not source_campaign_id:
            logger.info("Ignoring non-outreach incoming chat for account %s from %s", account_id, tg_user_id)
            return

        conv = _ensure_outreach_conversation(
            db,
            account_id=account_id,
            tg_user_id=tg_user_id,
            tg_username=username,
            tg_first_name=sender.first_name or "",
            tg_last_name=sender.last_name or "",
            source_campaign_id=source_campaign_id,
        )

        # Load source campaign for stop conditions
        source_campaign = None
        if conv.source_campaign_id:
            source_campaign = db.query(Campaign).filter(
                Campaign.id == conv.source_campaign_id
            ).first()

        # ── Save incoming message ──
        incoming_message = _record_outreach_message(db, conversation=conv, role="user", text=text, increment_unread=True)

        # ── Check stop keywords ──
        if source_campaign and source_campaign.stop_keywords:
            kws = [k.strip().lower() for k in source_campaign.stop_keywords.split(",") if k.strip()]
            if any(kw in text.lower() for kw in kws):
                conv.status = "done"
                _add_to_dnc(db, username, tg_user_id, f"stop keyword in campaign {source_campaign.id}")
                db.commit()
                await _broadcast_conversation_message(conv, text)
                return

        # ── Check hot keywords ──
        if source_campaign and source_campaign.hot_keywords:
            kws = [k.strip().lower() for k in source_campaign.hot_keywords.split(",") if k.strip()]
            if any(kw in text.lower() for kw in kws):
                conv.is_hot = True
                if _ws_broadcast:
                    await _ws_broadcast({
                        "event": "hot_lead",
                        "conversation_id": conv.id,
                        "account_id": account_id,
                        "text": text,
                    })

        # ── Stop on reply (hand off to inbox) ──
        if source_campaign and source_campaign.stop_on_reply and conv.status == "active":
            conv.status = "paused"
            db.commit()
            await _broadcast_conversation_message(conv, text, paused_for_review=True)
            return

        # ── Conversation paused → record but don't reply ──
        if conv.status == "paused":
            db.commit()
            await _broadcast_conversation_message(conv, text)
            return

        # ── Max messages check ──
        if source_campaign and source_campaign.max_messages:
            assistant_count = db.query(Message).filter(
                Message.conversation_id == conv.id,
                Message.role == "assistant",
            ).count()
            if assistant_count >= source_campaign.max_messages:
                conv.status = "paused"
                db.commit()
                await _broadcast_conversation_message(conv, text)
                return

        db.commit()
        await _broadcast_conversation_message(conv, text)

        provider = getattr(settings, "provider", "openai") or "openai" if settings else "openai"
        openai_key = decrypt_value(settings.openai_key) if settings else ""
        anthropic_key = decrypt_value(getattr(settings, "anthropic_key", "")) if settings else ""

        if not account.auto_reply:
            await _emit_runtime_note("auto_reply_skipped", account_id=account_id, conversation_id=conv.id, reason="AI отключен для аккаунта")
            return
        if not settings or not settings.auto_reply_enabled:
            await _emit_runtime_note("auto_reply_skipped", account_id=account_id, conversation_id=conv.id, reason="AI отключен в настройках")
            return
        if provider in ("openai", "openrouter") and not openai_key:
            await _emit_runtime_note("auto_reply_skipped", account_id=account_id, conversation_id=conv.id, reason="OpenAI key не настроен")
            return
        if provider == "anthropic" and not anthropic_key:
            await _emit_runtime_note("auto_reply_skipped", account_id=account_id, conversation_id=conv.id, reason="Anthropic key не настроен")
            return

        _schedule_auto_reply(
            account_id=account_id,
            conversation_id=conv.id,
            tg_user_id=tg_user_id,
            trigger_message_id=incoming_message.id,
        )
    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
    finally:
        db.close()


async def convert_tdata_to_session(
    tdata_path: str,
    proxy_host: Optional[str] = None,
    proxy_port: Optional[int] = None,
    proxy_type: str = "SOCKS5",
    proxy_user: Optional[str] = None,
    proxy_pass: Optional[str] = None,
) -> Optional[str]:
    proxy = None
    if proxy_host and proxy_port:
        type_map = {"HTTP": "http", "SOCKS5": "socks5", "SOCKS4": "socks4"}
        proxy = {
            "proxy_type": type_map.get(_as_str(proxy_type, "SOCKS5").upper(), "socks5"),
            "addr": _as_str(proxy_host),
            "port": int(proxy_port),
            "username": _as_str(proxy_user).strip() or None,
            "password": _as_str(proxy_pass).strip() or None,
            "rdns": True,
        }

    from opentele.td import TDesktop
    from opentele.api import CreateNewSession

    tdesk = TDesktop(tdata_path)
    client = await tdesk.ToTelethon(session=StringSession(), flag=CreateNewSession, proxy=proxy)
    await client.connect()
    try:
        if await client.is_user_authorized():
            return client.session.save()
        return None
    finally:
        await client.disconnect()


async def _try_recover_from_tdata(account_id: int) -> Optional[str]:
    """Re-derive a fresh session_string from stored tdata using CreateNewSession.
    tdata's original auth key (KEY_A) stays intact; service gets a new independent key (KEY_C).
    Returns new session_string on success, None if recovery impossible."""
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if not acc or not getattr(acc, "tdata_blob", None):
            logger.info(f"Account {account_id}: no tdata_blob stored, cannot auto-recover")
            return None

        zip_bytes = base64.b64decode(decrypt_value(acc.tdata_blob))
        tmp_dir = tempfile.mkdtemp()
        try:
            zip_path = os.path.join(tmp_dir, "tdata.zip")
            with open(zip_path, "wb") as f:
                f.write(zip_bytes)
            with zipfile.ZipFile(zip_path) as z:
                z.extractall(tmp_dir)

            tdata_path = None
            for root, _dirs, files in os.walk(tmp_dir):
                if "key_datas" in files:
                    tdata_path = root
                    break
            if not tdata_path:
                logger.error(f"Account {account_id}: tdata recovery — key_datas not found in zip")
                return None

            session_str = await convert_tdata_to_session(
                tdata_path=tdata_path,
                proxy_host=acc.proxy_host,
                proxy_port=acc.proxy_port,
                proxy_type=acc.proxy_type or "SOCKS5",
                proxy_user=acc.proxy_user,
                proxy_pass=decrypt_value(acc.proxy_pass) or None,
            )

            if session_str:
                acc.session_string = encrypt_value(session_str)
                acc.session_state = "valid"
                db.commit()
                logger.info(f"Account {account_id}: session successfully recovered from tdata")
                return session_str
            logger.warning(f"Account {account_id}: tdata recovery — not authorized after conversion")
            return None
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        logger.error(f"Account {account_id}: tdata recovery failed: {e}", exc_info=True)
        return None
    finally:
        db.close()


async def _set_needs_reauth(account_id: int, value: bool):
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if acc:
            acc.needs_reauth = value
            if value:
                acc.connection_state = "reauth_required"
                acc.session_state = "expired"
            db.commit()
    finally:
        db.close()


def get_account_state(account_id: int) -> dict:
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        return _serialize_runtime_state(acc) if acc else {}
    finally:
        db.close()


async def reset_account_runtime(account_id: int, requested_by: str = "reset") -> dict:
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if not acc:
            return {"ok": False, "error": "Account not found", "requested_by": requested_by}
        _clear_legacy_account_limit_state(acc)
        acc.is_active = True
        acc.connection_state = "offline"
        acc.last_error_code = None
        acc.last_error_message = None
        acc.last_error_at = None
        db.commit()
    finally:
        db.close()
    return await reconnect_account_runtime(account_id, requested_by=requested_by)


async def reconnect_account_runtime(account_id: int, requested_by: str = "system") -> dict:
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if not acc:
            return {"ok": False, "error": "Account not found", "requested_by": requested_by}
        if _clear_legacy_account_limit_state(acc):
            db.commit()
        _persist_account_runtime_state(
            account_id,
            connection_state="connecting",
            session_state=_derive_session_state(acc),
        )
    finally:
        db.close()

    proxy_result = await proxy_test_account(account_id)
    if not proxy_result.get("ok"):
        return {
            "ok": False,
            "requested_by": requested_by,
            "reason": "blocked_proxy",
            "steps": {"proxy": proxy_result},
            "account": get_public_account(account_id),
        }

    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        ok = await start_client(acc)
        state = get_account_state(account_id)
        account_payload = get_public_account(account_id)
        result = {
            "ok": ok,
            "requested_by": requested_by,
            "steps": {
                "proxy": proxy_result,
                "session": {"state": state.get("session_state")},
                "telegram": {"ok": ok, "state": state.get("connection_state")},
            },
            "account": account_payload,
        }
        if not ok:
            result["reason"] = account_payload.get("reason") or state.get("eligibility_state")
            result["error"] = state.get("last_error_message") or "Failed to connect"
        if _ws_broadcast:
            await _ws_broadcast({"event": "account_status", "account_id": account_id, "state": state})
        return result
    finally:
        db.close()


async def start_client(account: Account, _tdata_retried: bool = False) -> bool:
    if not account:
        return False
    if account.id in _clients:
        _clear_error(
            account.id,
            connection_state="online",
            session_state="valid",
            proxy_state="ok",
            last_seen_online_at=_utcnow(),
        )
        return True

    _persist_account_runtime_state(account.id, connection_state="connecting", session_state=_derive_session_state(account))
    try:
        client = _make_client(account)
    except (ValueError, Exception) as e:
        logger.error(f"Account {account.id}: invalid session / config — {e}")
        _mark_error(account.id, "INVALID_SESSION", str(e), session_state="expired", connection_state="offline")
        return False
    try:
        try:
            await asyncio.wait_for(client.connect(), timeout=30)
        except asyncio.TimeoutError:
            logger.error(f"Account {account.id}: connect() timed out after 30s")
            await client.disconnect()
            _mark_error(account.id, "CONNECT_TIMEOUT", "Connection timed out", connection_state="degraded")
            return False
        if not await client.is_user_authorized():
            logger.warning(f"Account {account.id} session expired — needs re-auth")
            await client.disconnect()
            _mark_error(account.id, "SESSION_EXPIRED", "Session expired", session_state="expired")
            if not _tdata_retried and getattr(account, "tdata_blob", None):
                _persist_account_runtime_state(account.id, session_state="recovering")
                recovered = await _try_recover_from_tdata(account.id)
                if recovered:
                    account.session_string = encrypt_value(recovered)
                    return await start_client(account, _tdata_retried=True)
                _persist_account_runtime_state(account.id, session_state="recovery_failed")
            await _set_needs_reauth(account.id, True)
            return False

        _persist_account_runtime_state(
            account.id,
            connection_state="online",
            proxy_state="ok",
            session_state="valid",
            eligibility_state="eligible",
            last_connect_at=_utcnow(),
            last_seen_online_at=_utcnow(),
        )
        await _set_needs_reauth(account.id, False)
        await _save_session_string(account.id, client)

        acc_id = int(account.id)  # capture as plain int — account object may be detached later

        @client.on(events.NewMessage())
        async def handler(event):
            await _handle_message(acc_id, event)

        _clients[acc_id] = client
        task = asyncio.create_task(_run_client(client, acc_id))
        _tasks[acc_id] = task

        logger.info(f"Started client for account {acc_id} ({account.phone})")
        return True
    except (AuthKeyDuplicatedError, AuthKeyUnregisteredError, UserDeactivatedBanError) as e:
        logger.error(f"Auth key invalid for account {account.id}: {e}")
        await client.disconnect()
        _mark_error(account.id, type(e).__name__, str(e), session_state="expired")
        if not _tdata_retried and getattr(account, "tdata_blob", None):
            _persist_account_runtime_state(account.id, session_state="recovering")
            recovered = await _try_recover_from_tdata(account.id)
            if recovered:
                account.session_string = encrypt_value(recovered)
                return await start_client(account, _tdata_retried=True)
            _persist_account_runtime_state(account.id, session_state="recovery_failed")
        await _set_needs_reauth(account.id, True)
        return False
    except Exception as e:
        logger.error(f"Failed to start client {account.id}: {e}")
        await client.disconnect()
        _mark_error(account.id, "CONNECT_FAILED", str(e), connection_state="degraded")
        return False


async def _run_client(client: TelegramClient, account_id: int):
    try:
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"Client {account_id} disconnected: {e}")
    finally:
        _clients.pop(account_id, None)
        _tasks.pop(account_id, None)
        db = SessionLocal()
        try:
            acc = db.query(Account).filter(Account.id == account_id).first()
            if acc:
                acc.is_active = False
                acc.connection_state = "reauth_required" if acc.needs_reauth else "offline"
                db.commit()
        finally:
            db.close()
    # Network blip — try to reconnect once after 15s (supervisor will handle the rest)
    logger.info(f"Client {account_id} dropped, scheduling reconnect in 15s")
    await asyncio.sleep(15)
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if acc and not getattr(acc, "needs_reauth", False) and account_id not in _clients:
            logger.info(f"Auto-reconnecting account {account_id}")
            ok = await start_client(acc)
            if ok:
                acc.is_active = True
                db.commit()
    except Exception as e:
        logger.error(f"Auto-reconnect failed for {account_id}: {e}")
    finally:
        db.close()


_last_keepalive: Dict[int, float] = {}
_KEEPALIVE_INTERVAL = 3 * 3600  # 3 hours


async def _supervise_accounts():
    """Background supervisor: restarts dropped clients every 60s, keep-alive every 3h."""
    while True:
        await asyncio.sleep(60)
        db = SessionLocal()
        try:
            accounts = db.query(Account).all()
            now = asyncio.get_event_loop().time()
            for acc in accounts:
                dirty = _clear_legacy_account_limit_state(acc)
                if dirty:
                    db.commit()

                if not acc.last_proxy_check_at or (_utcnow() - acc.last_proxy_check_at).total_seconds() > 300:
                    await _proxy_connectivity_check(acc)

                needs_reauth = getattr(acc, "needs_reauth", False)
                has_session = decrypt_value(acc.session_string) or os.path.exists(_session_path(acc.id) + ".session")
                if has_session and not needs_reauth and acc.id not in _clients:
                    logger.info(f"Supervisor: reconnecting account {acc.id} ({acc.phone})")
                    ok = await start_client(acc)
                    if ok:
                        acc.is_active = True
                        db.commit()
                elif acc.id in _clients:
                    # Keep-alive: ping Telegram so session never goes idle
                    last = _last_keepalive.get(acc.id, 0)
                    if now - last > _KEEPALIVE_INTERVAL:
                        try:
                            client = _clients[acc.id]
                            await client.get_me()
                            _last_keepalive[acc.id] = now
                            logger.debug(f"Keep-alive OK for account {acc.id}")
                        except Exception as e:
                            logger.warning(f"Keep-alive failed for account {acc.id}: {e}")
        except Exception as e:
            logger.error(f"Supervisor error: {e}")
        finally:
            db.close()


async def stop_client(account_id: int):
    client = _clients.pop(account_id, None)
    task = _tasks.pop(account_id, None)
    if client:
        await client.disconnect()
    if task:
        task.cancel()


def is_running(account_id: int) -> bool:
    return account_id in _clients


async def login_new_account(account: Account, phone_code: str, code: str, password: str = "", partial_session: Optional[str] = None) -> dict:
    try:
        if partial_session:
            # Use the session from send_code_request — same auth key, Telegram accepts the code
            client = _make_telegram_client(account, StringSession(_as_str(partial_session)))
        else:
            client = _make_fresh_client(account)
    except (ValueError, Exception) as e:
        return {"ok": False, "error": f"Failed to create client: {e}"}
    try:
        await client.connect()
        await client.sign_in(_as_str(account.phone), _as_str(code), phone_code_hash=_as_str(phone_code))
        session_str = client.session.save()
        await client.disconnect()
        db = SessionLocal()
        try:
            acc = db.query(Account).filter(Account.id == account.id).first()
            if acc:
                acc.session_string = encrypt_value(session_str)
                acc.session_state = "valid"
                acc.session_source = acc.session_source or "phone_code"
                db.commit()
        finally:
            db.close()
        return {"ok": True}
    except Exception as e:
        if "SessionPasswordNeededError" in type(e).__name__ and password:
            try:
                await client.sign_in(password=_as_str(password))
                session_str = client.session.save()
                await client.disconnect()
                db = SessionLocal()
                try:
                    acc = db.query(Account).filter(Account.id == account.id).first()
                    if acc:
                        acc.session_string = encrypt_value(session_str)
                        acc.session_state = "valid"
                        acc.session_source = acc.session_source or "phone_code"
                        db.commit()
                finally:
                    db.close()
                return {"ok": True}
            except Exception as e2:
                await client.disconnect()
                return {"ok": False, "error": str(e2)}
        await client.disconnect()
        return {"ok": False, "error": str(e)}


def _make_fresh_client(account: Account) -> TelegramClient:
    """Create a client with a blank session — used for re-auth flows where the old session may be dead."""
    return _make_telegram_client(account, StringSession())


async def send_code_request(account: Account) -> dict:
    # Always use a fresh session for send-code — the existing session may be dead/duplicated
    proxy_result = await _proxy_connectivity_check(account)
    if not proxy_result.get("ok"):
        return {"ok": False, "error": proxy_result.get("error") or "Proxy connection failed", "proxy": proxy_result}

    client = _make_fresh_client(account)
    logger.info(
        "send_code_diag account_id=%s proxy=%s account_app_id=%s account_app_hash=%s client_api_id=%s client_api_hash=%s",
        getattr(account, "id", None),
        _debug_proxy_shape(_build_proxy(account)),
        _debug_shape(getattr(account, "app_id", None)),
        _debug_shape(getattr(account, "app_hash", None)),
        _debug_shape(getattr(client, "api_id", None)),
        _debug_shape(getattr(client, "api_hash", None)),
    )
    try:
        await client.connect()
        result = await client.send_code_request(_as_str(account.phone))
        # Telethon can store server_address as int (IPv4 integer) after connect —
        # StringSession.save() requires str/bytes, so we coerce it here.
        sess = client.session
        if (hasattr(sess, "_server_address")
                and sess._server_address is not None
                and not isinstance(sess._server_address, (str, bytes, bytearray))):
            sess._server_address = str(sess._server_address)
        partial_session = sess.save()
        await client.disconnect()
        return {"ok": True, "phone_code_hash": result.phone_code_hash, "partial_session": partial_session}
    except Exception as e:
        logger.exception("send_code_request failed for account %s", getattr(account, "id", None))
        await client.disconnect()
        return {"ok": False, "error": str(e)}


async def start_all_accounts():
    db = SessionLocal()
    try:
        accounts = db.query(Account).all()
        for acc in accounts:
            try:
                if _clear_legacy_account_limit_state(acc):
                    db.commit()
                has_session = acc.session_string or os.path.exists(_session_path(acc.id) + ".session")
                if has_session:
                    ok = await start_client(acc)
                    if ok:
                        acc.is_active = True
                        db.commit()
            except Exception as e:
                logger.error(f"Account {acc.id} ({acc.phone}): startup error skipped — {e}")
        await resume_running_campaigns(db)
    finally:
        db.close()
    # Start background supervisor for 24/7 uptime
    asyncio.create_task(_supervise_accounts())


async def resume_running_campaigns(db=None):
    close_db = db is None
    if close_db:
        db = SessionLocal()
    try:
        running = db.query(Campaign).filter(Campaign.status == "running").all()
        for c in running:
            if c.id not in _campaign_tasks:
                logger.info(f"Resuming campaign {c.id} ({c.name}) after restart")
                task = asyncio.create_task(_campaign_worker(c.id))
                _campaign_tasks[c.id] = task
    finally:
        if close_db:
            db.close()


def _entity_profile(entity, fallback_username: Optional[str] = None, fallback_first_name: Optional[str] = None) -> dict:
    return {
        "tg_user_id": str(getattr(entity, "id", "") or ""),
        "tg_username": getattr(entity, "username", None) or fallback_username or "",
        "tg_first_name": getattr(entity, "first_name", None) or fallback_first_name or "",
        "tg_last_name": getattr(entity, "last_name", None) or "",
    }


def _persist_outgoing_outreach_message(
    *,
    account_id: int,
    text: str,
    conversation_id: Optional[int] = None,
    source_campaign_id: Optional[int] = None,
    tg_user_id: Optional[str] = None,
    tg_username: Optional[str] = None,
    tg_first_name: Optional[str] = None,
    tg_last_name: Optional[str] = None,
) -> Optional[Conversation]:
    db = SessionLocal()
    try:
        conv = None
        if conversation_id is not None:
            conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
        if conv is None:
            if not tg_user_id:
                logger.warning("Skipping conversation persistence for account %s: tg_user_id is missing", account_id)
                return None
            conv = _ensure_outreach_conversation(
                db,
                account_id=account_id,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                tg_first_name=tg_first_name,
                tg_last_name=tg_last_name,
                source_campaign_id=source_campaign_id,
            )
        _record_outreach_message(db, conversation=conv, role="assistant", text=text)
        db.commit()
        db.refresh(conv)
        return conv
    finally:
        db.close()


async def send_manual_message(account_id: int, tg_user_id: str, conversation_id: int, text: str) -> dict:
    client = _clients.get(account_id)
    if not client:
        reconnect = await reconnect_account_runtime(account_id, requested_by="manual-send")
        if not reconnect.get("ok"):
            return reconnect
        client = _clients.get(account_id)
    if not client:
        return {"ok": False, "error": "Account is not connected"}
    await client.send_message(int(tg_user_id), text)
    _clear_error(account_id, connection_state="online", last_seen_online_at=_utcnow())
    conv = _persist_outgoing_outreach_message(
        account_id=account_id,
        conversation_id=conversation_id,
        tg_user_id=tg_user_id,
        text=text,
    )
    if _ws_broadcast:
        if conv:
            await _broadcast_conversation_message(conv, text)
        await _ws_broadcast(
            {
                "event": "manual_message_sent",
                "conversation_id": conversation_id,
                "account_id": account_id,
                "text": text,
            }
        )
    return {"ok": True, "conversation_id": conv.id if conv else conversation_id}


# ── Campaign worker ──────────────────────────────────────────────

async def start_campaign(campaign_id: int):
    if campaign_is_running(campaign_id):
        return
    _campaign_tasks.pop(campaign_id, None)
    task = asyncio.create_task(_campaign_worker(campaign_id))
    _campaign_tasks[campaign_id] = task


async def stop_campaign(campaign_id: int):
    task = _campaign_tasks.pop(campaign_id, None)
    if task:
        task.cancel()
    db = SessionLocal()
    try:
        c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if c and c.status == "running":
            c.status = "paused"
            db.commit()
    finally:
        db.close()


def campaign_is_running(campaign_id: int) -> bool:
    task = _campaign_tasks.get(campaign_id)
    return bool(task and not task.done())


async def _await_campaign_call(campaign_id: int, target_username: str, stage: str, coro, timeout_s: float):
    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(
            f"{stage} timeout after {timeout_s:.0f}s for @{target_username} in campaign {campaign_id}"
        ) from exc


def _pause_campaign_after_worker_error(campaign_id: int, error: str):
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if campaign and campaign.status == "running":
            campaign.status = "paused"
            db.commit()
    finally:
        db.close()


async def preflight_and_start_campaign(campaign_id: int) -> dict:
    db = SessionLocal()
    try:
        campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
        if not campaign:
            return {"ok": False, "error": "Campaign not found"}
        acc_ids = json.loads(campaign.account_ids) if campaign.account_ids else [campaign.account_id]
        eligible_accounts = []
        blocked_accounts = []
        for aid in acc_ids:
            acc = db.query(Account).filter(Account.id == aid).first()
            if not acc:
                blocked_accounts.append({"account_id": aid, "reason": "not_found", "error": "Account not found"})
                continue
            if aid not in _clients:
                await reconnect_account_runtime(aid, requested_by=f"campaign:{campaign_id}")
            snapshot = get_account_state(aid)
            if snapshot.get("eligibility_state") == "eligible" and aid in _clients:
                eligible_accounts.append(
                    {"account_id": aid, "name": acc.name, "state": snapshot}
                )
            else:
                blocked_accounts.append(
                    {
                        "account_id": aid,
                        "name": acc.name,
                        "reason": snapshot.get("eligibility_state") or "blocked_auth",
                        "error": snapshot.get("last_error_message"),
                        "state": snapshot,
                    }
                )
        if not eligible_accounts:
            return {
                "ok": False,
                "reason": "NO_ELIGIBLE_ACCOUNTS",
                "eligible_accounts": [],
                "blocked_accounts": blocked_accounts,
            }
        campaign.status = "running"
        db.commit()
    finally:
        db.close()

    await start_campaign(campaign_id)
    return {
        "ok": True,
        "eligible_accounts": eligible_accounts,
        "blocked_accounts": blocked_accounts,
    }


def _seconds_until_window_open(hour_from: int, hour_to: int) -> int:
    """Return seconds until send window opens (0 = currently inside window).
    Supports wrap-around: hour_from=22, hour_to=6 means 22:00-06:00 (night shift).
    """
    now_msk = datetime.utcnow() + _MSK_OFFSET
    h = now_msk.hour

    if hour_from == hour_to:
        return 0  # no restriction effectively

    if hour_from < hour_to:
        # Normal range, e.g. 9-21
        in_window = hour_from <= h < hour_to
    else:
        # Wrap-around range, e.g. 22-06 (night): in window if h >= 22 or h < 6
        in_window = h >= hour_from or h < hour_to

    if in_window:
        return 0

    # Calculate seconds until hour_from (today or tomorrow)
    target = now_msk.replace(hour=hour_from, minute=0, second=0, microsecond=0)
    if target <= now_msk:
        target += timedelta(days=1)
    return max(0, int((target - now_msk).total_seconds()))


def _apply_personalization(text: str, target: CampaignTarget) -> str:
    """Substitute all {variable} placeholders from target fields."""
    first_name = (target.display_name or "").strip()
    if not first_name:
        text = re.sub(r"\s*,\s*\{first_name\}", "", text)
        text = re.sub(r"\s+\{first_name\}\s*,?", " ", text)
    replacements = {
        "{first_name}": first_name,
        "{company}": target.company or "",
        "{role}": target.role or "",
        "{note}": target.custom_note or "",
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    text = re.sub(r"\s+([!?,.;:])", r"\1", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


async def _campaign_worker(campaign_id: int):
    logger.info(f"Campaign {campaign_id} worker started")
    try:
        while True:
            db = SessionLocal()
            try:
                campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if not campaign or campaign.status != "running":
                    break

                # ── Time window check (MSK) ──
                if campaign.send_window_enabled:
                    wait_secs = _seconds_until_window_open(
                        campaign.send_hour_from, campaign.send_hour_to
                    )
                    if wait_secs > 0:
                        logger.info(f"Campaign {campaign_id}: outside send window, sleeping {wait_secs}s")
                        db.close()
                        await asyncio.sleep(wait_secs)
                        continue

                # ── Daily limit check ──
                today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                sent_today = db.query(CampaignTarget).filter(
                    CampaignTarget.campaign_id == campaign_id,
                    CampaignTarget.status == "sent",
                    CampaignTarget.sent_at >= today_start,
                ).count()

                if sent_today >= campaign.daily_limit:
                    logger.info(f"Campaign {campaign_id}: daily limit reached, sleeping 1h")
                    db.close()
                    await asyncio.sleep(3600)
                    continue

                # ── Next pending target ──
                target = db.query(CampaignTarget).filter(
                    CampaignTarget.campaign_id == campaign_id,
                    CampaignTarget.status == "pending",
                ).first()

                if not target:
                    campaign.status = "done"
                    db.commit()
                    logger.info(f"Campaign {campaign_id}: all targets done")
                    break

                # ── DNC check ──
                if _is_in_dnc(db, target.username, None):
                    target.status = "skipped"
                    db.commit()
                    logger.info(f"Campaign {campaign_id}: skipped {target.username} (DNC)")
                    continue

                # ── Resolve account list for this campaign ──
                if campaign.account_ids:
                    acc_ids = json.loads(campaign.account_ids)
                else:
                    acc_ids = [campaign.account_id]

                # ── Deduplication: skip if already sent from any account in this campaign ──
                from sqlalchemy import or_ as _or
                already_sent = db.query(CampaignTarget).join(
                    Campaign, CampaignTarget.campaign_id == Campaign.id
                ).filter(
                    CampaignTarget.username == target.username,
                    _or(*[Campaign.account_id == aid for aid in acc_ids]),
                    CampaignTarget.status == "sent",
                    CampaignTarget.campaign_id != campaign_id,
                ).first()

                if already_sent:
                    target.status = "skipped"
                    db.commit()
                    logger.info(f"Campaign {campaign_id}: skipped {target.username} (already sent from account)")
                    continue

                # ── Pick a connected client (random among available) ──
                available = []
                for aid in acc_ids:
                    if aid not in _clients:
                        continue
                    acc = db.query(Account).filter(Account.id == aid).first()
                    if not acc:
                        continue
                    if _compute_eligibility(acc) != "eligible":
                        continue
                    sent_by_account_today = db.query(CampaignTarget).filter(
                        CampaignTarget.account_id == aid,
                        CampaignTarget.status == "sent",
                        CampaignTarget.sent_at >= today_start,
                    ).count()
                    account_cap = campaign.daily_limit
                    if sent_by_account_today >= account_cap:
                        continue
                    available.append((aid, _clients[aid], acc))
                if not available:
                    logger.warning(f"Campaign {campaign_id}: no accounts connected, retrying in 60s")
                    db.close()
                    await asyncio.sleep(60)
                    continue
                _account_id, client, _account = random.choice(available)

                messages = json.loads(campaign.messages)
                text = random.choice(messages)
                text = _apply_personalization(text, target)

                try:
                    entity = await _await_campaign_call(
                        campaign_id,
                        target.username,
                        "resolve",
                        client.get_entity(target.username),
                        CAMPAIGN_ENTITY_TIMEOUT_S,
                    )
                    sent_message = await _await_campaign_call(
                        campaign_id,
                        target.username,
                        "send",
                        client.send_message(entity, text),
                        CAMPAIGN_SEND_TIMEOUT_S,
                    )
                    target.status = "sent"
                    target.account_id = _account_id
                    target.sent_at = datetime.utcnow()
                    _clear_error(_account_id, connection_state="online", last_seen_online_at=_utcnow())
                    profile = _entity_profile(
                        entity,
                        fallback_username=target.username,
                        fallback_first_name=target.display_name,
                    )
                    if not profile["tg_user_id"]:
                        peer_id = getattr(sent_message, "peer_id", None)
                        profile["tg_user_id"] = str(getattr(peer_id, "user_id", "") or "")
                    conv = _persist_outgoing_outreach_message(
                        account_id=_account_id,
                        source_campaign_id=campaign_id,
                        tg_user_id=profile["tg_user_id"],
                        tg_username=profile["tg_username"] or target.username,
                        tg_first_name=profile["tg_first_name"] or target.display_name,
                        tg_last_name=profile["tg_last_name"],
                        text=text,
                    )
                    if conv:
                        await _broadcast_conversation_message(conv, text)
                    logger.info(f"Campaign {campaign_id}: sent to {target.username}")
                except FloodWaitError as e:
                    wait_secs = e.seconds + 30
                    _clear_error(_account_id, connection_state="online", last_seen_online_at=_utcnow())
                    logger.warning(f"Campaign {campaign_id}: FloodWait {e.seconds}s on account {_account_id}, sleeping {wait_secs}s")
                    db.commit()
                    await asyncio.sleep(wait_secs)
                    continue
                except PeerFloodError:
                    wait_secs = 3600
                    _clear_error(_account_id, connection_state="online", last_seen_online_at=_utcnow())
                    logger.error(f"Campaign {campaign_id}: PeerFloodError on account {_account_id}, sleeping 1h")
                    db.commit()
                    await asyncio.sleep(wait_secs)
                    continue
                except (UserPrivacyRestrictedError, UsernameNotOccupiedError, UsernameInvalidError) as e:
                    public_exists = None
                    if isinstance(e, (UsernameNotOccupiedError, UsernameInvalidError)):
                        public_exists = await _public_username_exists(target.username)

                    # public_exists=True → confirmed target resolution issue; public_exists=None → check failed.
                    # Either way this is a target failure, not an account restriction.
                    if public_exists or (public_exists is None and isinstance(e, (UsernameNotOccupiedError, UsernameInvalidError))):
                        _clear_error(_account_id, connection_state="online", last_seen_online_at=_utcnow())
                        target.status = "failed"
                        target.error = f"@{target.username} не резолвится через Telegram API"
                        logger.warning(
                            "Campaign %s: account %s cannot resolve @%s — marking target failed",
                            campaign_id, _account_id, target.username,
                        )
                        db.commit()
                        continue

                    target.status = "failed"
                    target.error = str(e)
                    logger.warning(f"Campaign {campaign_id}: permanent error for {target.username}: {e}")
                except Exception as e:
                    target.status = "failed"
                    target.error = str(e)
                    logger.warning(f"Campaign {campaign_id}: failed {target.username}: {e}")

                db.commit()

                if _ws_broadcast:
                    sent_count = db.query(CampaignTarget).filter(
                        CampaignTarget.campaign_id == campaign_id,
                        CampaignTarget.status == "sent",
                    ).count()
                    total = db.query(CampaignTarget).filter(
                        CampaignTarget.campaign_id == campaign_id
                    ).count()
                    await _ws_broadcast({
                        "event": "campaign_progress",
                        "campaign_id": campaign_id,
                        "sent": sent_count,
                        "total": total,
                        "last_target": target.username,
                        "last_status": target.status,
                    })

            finally:
                db.close()

            # ── Inter-message delay ──
            db2 = SessionLocal()
            try:
                c = db2.query(Campaign).filter(Campaign.id == campaign_id).first()
                delay = random.randint(c.delay_min, c.delay_max) if c else 30
            finally:
                db2.close()

            logger.info(f"Campaign {campaign_id}: sleeping {delay}s")
            await asyncio.sleep(delay)

    except asyncio.CancelledError:
        logger.info(f"Campaign {campaign_id} worker cancelled")
    except Exception as e:
        _pause_campaign_after_worker_error(campaign_id, str(e))
        logger.error(f"Campaign {campaign_id} worker error: {e}", exc_info=True)
    finally:
        _campaign_tasks.pop(campaign_id, None)
