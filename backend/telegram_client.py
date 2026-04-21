"""
Telethon client manager + Campaign worker.
"""
import asyncio
import base64
import json
import logging
import os
import random
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
    DoNotContact, Message, Settings,
)
from backend.security import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)

# account_id -> TelegramClient
_clients: Dict[int, TelegramClient] = {}
# account_id -> asyncio.Task
_tasks: Dict[int, asyncio.Task] = {}
# campaign_id -> asyncio.Task
_campaign_tasks: Dict[int, asyncio.Task] = {}

SESSIONS_DIR = "sessions"
os.makedirs(SESSIONS_DIR, exist_ok=True)

_ws_broadcast = None
_MSK_OFFSET = timedelta(hours=3)
_USERNAME_PAGE_CACHE: Dict[str, tuple[float, bool]] = {}


def set_ws_broadcast(fn):
    global _ws_broadcast
    _ws_broadcast = fn


def _session_path(account_id: int) -> str:
    return os.path.join(SESSIONS_DIR, f"account_{account_id}")


def _build_proxy(account: Account):
    if not account.proxy_host or not account.proxy_port:
        return None
    type_map = {"HTTP": "http", "SOCKS5": "socks5", "SOCKS4": "socks4"}
    return {
        "proxy_type": type_map.get((account.proxy_type or "SOCKS5").upper(), "socks5"),
        "addr": account.proxy_host,
        "port": int(account.proxy_port),
        "username": account.proxy_user or None,
        "password": decrypt_value(account.proxy_pass) or None,
        "rdns": True,
    }


def _make_client(account: Account) -> TelegramClient:
    proxy = _build_proxy(account)
    session_string = decrypt_value(account.session_string)
    app_hash = decrypt_value(account.app_hash) or account.app_hash
    if session_string:
        session = StringSession(session_string)
    else:
        session = _session_path(account.id)
    return TelegramClient(
        session, int(account.app_id), app_hash, proxy=proxy,
        device_model=getattr(account, "device_model", None) or "Desktop",
        system_version=getattr(account, "system_version", None) or "Windows 10",
        app_version=getattr(account, "app_version", None) or "6.7.5 x64",
        lang_code=getattr(account, "lang_code", None) or "ru",
        system_lang_code="ru-RU",
    )


def _utcnow() -> datetime:
    return datetime.utcnow()


def _derive_session_state(account: Account) -> str:
    if decrypt_value(account.session_string):
        return "valid"
    if decrypt_value(account.tdata_blob):
        return "expired"
    return "missing"


def _compute_eligibility(account: Account) -> str:
    if (account.proxy_state or "unknown") in {"failed", "timeout", "auth_failed"}:
        return "blocked_proxy"
    if getattr(account, "needs_reauth", False) or (account.session_state or "missing") in {
        "missing",
        "expired",
        "recovery_failed",
    }:
        return "blocked_auth"
    if (account.last_error_code or "") == "USERNAME_RESOLUTION_RESTRICTED":
        return "blocked_resolution"
    if (account.connection_state or "offline") == "online":
        return "eligible"
    return "blocked_auth"


def _serialize_health(account: Account) -> dict:
    return {
        "account_id": account.id,
        "connection_state": account.connection_state or "offline",
        "proxy_state": account.proxy_state or "unknown",
        "session_state": account.session_state or "missing",
        "eligibility_state": _compute_eligibility(account),
        "last_error_code": account.last_error_code,
        "last_error_message": account.last_error_message,
        "last_error_at": account.last_error_at,
        "last_proxy_check_at": account.last_proxy_check_at,
        "last_connect_at": account.last_connect_at,
        "last_seen_online_at": account.last_seen_online_at,
        "warmup_level": account.warmup_level or 0,
        "session_source": account.session_source or "",
        "proxy_last_rtt_ms": account.proxy_last_rtt_ms,
    }


def _persist_account_health(account_id: int, **updates) -> dict:
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
        return _serialize_health(acc)
    finally:
        db.close()


def _mark_error(account_id: int, code: str, message: str, **extra) -> dict:
    return _persist_account_health(
        account_id,
        last_error_code=code,
        last_error_message=message,
        last_error_at=_utcnow(),
        **extra,
    )


def _clear_error(account_id: int, **extra) -> dict:
    return _persist_account_health(
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


def _mark_username_resolution_restricted(account_id: int, username: str) -> dict:
    health = _mark_error(
        account_id,
        "USERNAME_RESOLUTION_RESTRICTED",
        f"Public username @{username.lstrip('@')} exists, but this account cannot resolve it via Telegram API",
        connection_state="online",
    )
    if _ws_broadcast:
        asyncio.create_task(_ws_broadcast({"event": "account_health", "account_id": account_id, "health": health}))
    return health


def _warmup_daily_cap(account: Account) -> int:
    warmup_caps = [10, 20, 35, 50]
    level = max(0, min(account.warmup_level or 0, len(warmup_caps) - 1))
    return warmup_caps[level]



async def _proxy_connectivity_check(account: Account) -> dict:
    started = time.perf_counter()
    target_host = "149.154.167.50"
    target_port = 443
    try:
        if account.proxy_host and account.proxy_port:
            from python_socks import ProxyType
            from python_socks.async_.asyncio import Proxy

            type_map = {
                "SOCKS5": ProxyType.SOCKS5,
                "SOCKS4": ProxyType.SOCKS4,
                "HTTP": ProxyType.HTTP,
            }
            proxy = Proxy.create(
                proxy_type=type_map.get((account.proxy_type or "SOCKS5").upper(), ProxyType.SOCKS5),
                host=account.proxy_host,
                port=int(account.proxy_port),
                username=account.proxy_user or None,
                password=decrypt_value(account.proxy_pass) or None,
            )
            sock = await asyncio.wait_for(proxy.connect(dest_host=target_host, dest_port=target_port), timeout=10)
            sock.close()
        else:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(target_host, target_port), timeout=10)
            writer.close()
            await writer.wait_closed()
        rtt_ms = int((time.perf_counter() - started) * 1000)
        health = _clear_error(
            account.id,
            proxy_state="ok",
            last_proxy_check_at=_utcnow(),
            proxy_last_rtt_ms=rtt_ms,
        )
        return {"ok": True, "proxy_state": "ok", "rtt_ms": rtt_ms, "health": health}
    except asyncio.TimeoutError:
        health = _mark_error(
            account.id,
            "PROXY_TIMEOUT",
            "Proxy connection timed out",
            proxy_state="timeout",
            last_proxy_check_at=_utcnow(),
        )
        return {"ok": False, "proxy_state": "timeout", "error": "Proxy connection timed out", "health": health}
    except Exception as exc:
        health = _mark_error(
            account.id,
            "PROXY_FAILED",
            str(exc),
            proxy_state="failed",
            last_proxy_check_at=_utcnow(),
        )
        return {"ok": False, "proxy_state": "failed", "error": str(exc), "health": health}


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
        await _ws_broadcast({"event": "account_health", "account_id": account_id, "health": result.get("health", {})})
    return result


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
    target = db.query(CampaignTarget).join(
        Campaign, CampaignTarget.campaign_id == Campaign.id
    ).filter(
        Campaign.account_id == account_id,
        CampaignTarget.username == username,
        CampaignTarget.status == "sent",
    ).order_by(CampaignTarget.sent_at.desc()).first()
    return target.campaign_id if target else None


async def _handle_message(account_id: int, event):
    if event.is_out:
        return
    sender: User = await event.get_sender()
    if not sender or sender.bot:
        return

    db = SessionLocal()
    try:
        settings = db.query(Settings).filter(Settings.id == 1).first()
        account = db.query(Account).filter(Account.id == account_id).first()

        if not account or not account.auto_reply:
            return
        if not settings or not settings.auto_reply_enabled:
            return
        provider = getattr(settings, "provider", "openai") or "openai"
        openai_key = decrypt_value(settings.openai_key)
        anthropic_key = decrypt_value(getattr(settings, "anthropic_key", ""))
        if provider in ("openai", "openrouter") and not openai_key:
            return
        if provider == "anthropic" and not anthropic_key:
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

        is_new_conv = conv is None
        if is_new_conv:
            conv = Conversation(
                account_id=account_id,
                tg_user_id=tg_user_id,
                tg_username=username or "",
                tg_first_name=sender.first_name or "",
                tg_last_name=sender.last_name or "",
                unread_count=0,
            )
            db.add(conv)
            db.flush()

        # ── Link to source campaign (first time we see this person) ──
        if not conv.source_campaign_id and username:
            campaign_id = _find_source_campaign(db, account_id, username)
            if campaign_id:
                conv.source_campaign_id = campaign_id

        # Load source campaign for stop conditions
        source_campaign = None
        if conv.source_campaign_id:
            source_campaign = db.query(Campaign).filter(
                Campaign.id == conv.source_campaign_id
            ).first()

        # ── Increment unread ──
        conv.unread_count = (conv.unread_count or 0) + 1

        # ── Save incoming message ──
        msg = Message(conversation_id=conv.id, role="user", text=text)
        db.add(msg)
        db.flush()

        # ── Check stop keywords ──
        if source_campaign and source_campaign.stop_keywords:
            kws = [k.strip().lower() for k in source_campaign.stop_keywords.split(",") if k.strip()]
            if any(kw in text.lower() for kw in kws):
                conv.status = "done"
                _add_to_dnc(db, username, tg_user_id, f"stop keyword in campaign {source_campaign.id}")
                conv.last_message = text
                conv.last_message_at = datetime.utcnow()
                db.commit()
                if _ws_broadcast:
                    await _ws_broadcast({
                        "event": "new_message",
                        "conversation_id": conv.id,
                        "account_id": account_id,
                        "text": text,
                        "unread_count": conv.unread_count,
                    })
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
            conv.last_message = text
            conv.last_message_at = datetime.utcnow()
            db.commit()
            if _ws_broadcast:
                await _ws_broadcast({
                    "event": "new_message",
                    "conversation_id": conv.id,
                    "account_id": account_id,
                    "text": text,
                    "unread_count": conv.unread_count,
                    "is_hot": bool(conv.is_hot),
                    "paused_for_review": True,
                })
            return

        # ── Conversation paused → record but don't reply ──
        if conv.status == "paused":
            conv.last_message = text
            conv.last_message_at = datetime.utcnow()
            db.commit()
            if _ws_broadcast:
                await _ws_broadcast({
                    "event": "new_message",
                    "conversation_id": conv.id,
                    "account_id": account_id,
                    "text": text,
                    "unread_count": conv.unread_count,
                })
            return

        # ── Max messages check ──
        if source_campaign and source_campaign.max_messages:
            assistant_count = db.query(Message).filter(
                Message.conversation_id == conv.id,
                Message.role == "assistant",
            ).count()
            if assistant_count >= source_campaign.max_messages:
                conv.status = "paused"
                conv.last_message = text
                conv.last_message_at = datetime.utcnow()
                db.commit()
                if _ws_broadcast:
                    await _ws_broadcast({
                        "event": "new_message",
                        "conversation_id": conv.id,
                        "account_id": account_id,
                        "text": text,
                        "unread_count": conv.unread_count,
                    })
                return

        # ── Load history and resolve prompt ──
        history = db.query(Message).filter(
            Message.conversation_id == conv.id
        ).order_by(Message.created_at.desc()).limit(settings.context_messages).all()
        history = list(reversed(history))

        # Eagerly load prompt templates for resolution
        db.expire_all()
        account = db.query(Account).filter(Account.id == account_id).first()
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

        system_prompt = _resolve_prompt(settings, account, source_campaign)

        db.commit()

        from backend.gpt_handler import generate_reply
        reply = await generate_reply(
            provider=getattr(settings, "provider", "openai") or "openai",
            openai_key=openai_key or "",
            anthropic_key=anthropic_key or "",
            base_url=getattr(settings, "base_url", "") or "",
            model=settings.model,
            system_prompt=system_prompt,
            history=history,
        )

        if reply:
            client = _clients.get(account_id)
            if client:
                await client.send_message(sender.id, reply)
            db.refresh(conv)
            reply_msg = Message(conversation_id=conv.id, role="assistant", text=reply)
            db.add(reply_msg)
            conv.last_message = reply
            conv.last_message_at = datetime.utcnow()
            db.commit()

            if _ws_broadcast:
                await _ws_broadcast({
                    "event": "new_message",
                    "conversation_id": conv.id,
                    "account_id": account_id,
                    "text": reply,
                    "unread_count": conv.unread_count,
                    "is_hot": bool(conv.is_hot),
                })
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
            "proxy_type": type_map.get((proxy_type or "SOCKS5").upper(), "socks5"),
            "addr": proxy_host,
            "port": int(proxy_port),
            "username": proxy_user or None,
            "password": proxy_pass or None,
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


def get_account_health(account_id: int) -> dict:
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        return _serialize_health(acc) if acc else {}
    finally:
        db.close()


async def clear_quarantine(account_id: int) -> dict:
    """Manually clear quarantine and reconnect the account."""
    health = _persist_account_health(
        account_id,
        quarantine_until=None,
        connection_state="offline",
        last_error_code=None,
        last_error_message=None,
    )
    if _ws_broadcast:
        asyncio.create_task(_ws_broadcast({"event": "account_health", "account_id": account_id, "health": health}))
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if acc:
            acc.is_active = True
            db.commit()
            ok = await start_client(acc)
            health = get_account_health(account_id)
            return {"ok": ok, "health": health}
    finally:
        db.close()
    return {"ok": False, "error": "Account not found"}


async def reconnect_account_runtime(account_id: int, requested_by: str = "system") -> dict:
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if not acc:
            return {"ok": False, "error": "Account not found", "requested_by": requested_by}
        if acc.quarantine_until:
            acc.quarantine_until = None
            db.commit()
        _persist_account_health(
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
            "health": get_account_health(account_id),
        }

    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        ok = await start_client(acc)
        health = get_account_health(account_id)
        result = {
            "ok": ok,
            "requested_by": requested_by,
            "steps": {
                "proxy": proxy_result,
                "session": {"state": health.get("session_state")},
                "telegram": {"ok": ok, "state": health.get("connection_state")},
            },
            "health": health,
        }
        if not ok:
            result["reason"] = health.get("eligibility_state")
            result["error"] = health.get("last_error_message") or "Failed to connect"
        if _ws_broadcast:
            await _ws_broadcast({"event": "account_health", "account_id": account_id, "health": health})
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

    _persist_account_health(account.id, connection_state="connecting", session_state=_derive_session_state(account))
    client = _make_client(account)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning(f"Account {account.id} session expired — needs re-auth")
            await client.disconnect()
            _mark_error(account.id, "SESSION_EXPIRED", "Session expired", session_state="expired")
            if not _tdata_retried and getattr(account, "tdata_blob", None):
                _persist_account_health(account.id, session_state="recovering")
                recovered = await _try_recover_from_tdata(account.id)
                if recovered:
                    account.session_string = encrypt_value(recovered)
                    return await start_client(account, _tdata_retried=True)
                _persist_account_health(account.id, session_state="recovery_failed")
            await _set_needs_reauth(account.id, True)
            return False

        _persist_account_health(
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
            _persist_account_health(account.id, session_state="recovering")
            recovered = await _try_recover_from_tdata(account.id)
            if recovered:
                account.session_string = encrypt_value(recovered)
                return await start_client(account, _tdata_retried=True)
            _persist_account_health(account.id, session_state="recovery_failed")
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


async def _supervise_accounts():
    """Background supervisor: restarts dropped clients every 60s."""
    while True:
        await asyncio.sleep(60)
        db = SessionLocal()
        try:
            accounts = db.query(Account).all()
            for acc in accounts:
                if acc.quarantine_until:
                    acc.quarantine_until = None
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


async def login_new_account(account: Account, phone_code: str, code: str, password: str = "") -> dict:
    client = _make_client(account)
    try:
        await client.connect()
        await client.sign_in(account.phone, code, phone_code_hash=phone_code)
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
                await client.sign_in(password=password)
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


async def send_code_request(account: Account) -> dict:
    client = _make_client(account)
    try:
        await client.connect()
        result = await client.send_code_request(account.phone)
        await client.disconnect()
        return {"ok": True, "phone_code_hash": result.phone_code_hash}
    except Exception as e:
        await client.disconnect()
        return {"ok": False, "error": str(e)}


async def start_all_accounts():
    db = SessionLocal()
    try:
        accounts = db.query(Account).all()
        for acc in accounts:
            has_session = acc.session_string or os.path.exists(_session_path(acc.id) + ".session")
            if has_session:
                ok = await start_client(acc)
                if ok:
                    acc.is_active = True
                    db.commit()
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
    if _ws_broadcast:
        await _ws_broadcast(
            {
                "event": "manual_message_sent",
                "conversation_id": conversation_id,
                "account_id": account_id,
                "text": text,
            }
        )
    return {"ok": True}


# ── Campaign worker ──────────────────────────────────────────────

async def start_campaign(campaign_id: int):
    if campaign_id in _campaign_tasks:
        return
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
    return campaign_id in _campaign_tasks


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
            snapshot = get_account_health(aid)
            if snapshot.get("eligibility_state") == "eligible" and aid in _clients:
                eligible_accounts.append(
                    {"account_id": aid, "name": acc.name, "health": snapshot}
                )
            else:
                blocked_accounts.append(
                    {
                        "account_id": aid,
                        "name": acc.name,
                        "reason": snapshot.get("eligibility_state") or "blocked_auth",
                        "error": snapshot.get("last_error_message"),
                        "health": snapshot,
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
    replacements = {
        "{first_name}": target.display_name or "",
        "{company}": target.company or "",
        "{role}": target.role or "",
        "{note}": target.custom_note or "",
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    # Clean up double spaces from empty substitutions
    while "  " in text:
        text = text.replace("  ", " ")
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
                    account_cap = min(campaign.daily_limit, _warmup_daily_cap(acc))
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
                    await client.send_message(target.username, text)
                    target.status = "sent"
                    target.account_id = _account_id
                    target.sent_at = datetime.utcnow()
                    _clear_error(_account_id, connection_state="online", last_seen_online_at=_utcnow())
                    logger.info(f"Campaign {campaign_id}: sent to {target.username}")
                except FloodWaitError as e:
                    wait_secs = e.seconds + 30
                    _mark_error(_account_id, "FLOOD_WAIT", f"FloodWait {e.seconds}s")
                    logger.warning(f"Campaign {campaign_id}: FloodWait {e.seconds}s on account {_account_id}, sleeping {wait_secs}s")
                    db.commit()
                    await asyncio.sleep(wait_secs)
                    continue
                except PeerFloodError:
                    wait_secs = 3600
                    _mark_error(_account_id, "PEER_FLOOD", "PeerFloodError — sleeping 1h")
                    logger.error(f"Campaign {campaign_id}: PeerFloodError on account {_account_id}, sleeping 1h")
                    db.commit()
                    await asyncio.sleep(wait_secs)
                    continue
                except (UserPrivacyRestrictedError, UsernameNotOccupiedError, UsernameInvalidError) as e:
                    public_exists = None
                    if isinstance(e, (UsernameNotOccupiedError, UsernameInvalidError)):
                        public_exists = await _public_username_exists(target.username)

                    # public_exists=True → confirmed resolution issue; public_exists=None → check failed,
                    # treat conservatively (don't permanently fail — try another account or pause)
                    if public_exists or (public_exists is None and isinstance(e, (UsernameNotOccupiedError, UsernameInvalidError))):
                        _mark_username_resolution_restricted(_account_id, target.username)

                        # Check if any other account in campaign can still resolve
                        still_eligible = False
                        db.expire_all()
                        for aid in acc_ids:
                            if aid not in _clients:
                                continue
                            candidate = db.query(Account).filter(Account.id == aid).first()
                            if candidate and _compute_eligibility(candidate) == "eligible":
                                still_eligible = True
                                break

                        if still_eligible:
                            # Another account may be able to send — retry on next iteration
                            logger.warning(
                                "Campaign %s: account %s cannot resolve @%s, will retry with another account",
                                campaign_id, _account_id, target.username,
                            )
                            db.commit()
                            continue
                        else:
                            # No accounts can resolve this username — mark target failed and move on
                            target.status = "failed"
                            target.error = (
                                f"@{target.username} cannot be resolved by any available account "
                                "(likely DC routing restriction)"
                            )
                            logger.warning(
                                "Campaign %s: no accounts can resolve @%s — marking failed",
                                campaign_id, target.username,
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
        logger.error(f"Campaign {campaign_id} worker error: {e}", exc_info=True)
    finally:
        _campaign_tasks.pop(campaign_id, None)
