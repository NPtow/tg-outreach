"""
Telethon client manager + Campaign worker.
"""
import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta
from typing import Dict

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    PeerFloodError,
    UserPrivacyRestrictedError,
    UsernameNotOccupiedError,
    UsernameInvalidError,
)
from telethon.sessions import StringSession
from telethon.tl.types import User

from backend.database import SessionLocal
from backend.models import (
    Account, Campaign, CampaignTarget, Conversation,
    DoNotContact, Message, Settings,
)

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


def set_ws_broadcast(fn):
    global _ws_broadcast
    _ws_broadcast = fn


def _session_path(account_id: int) -> str:
    return os.path.join(SESSIONS_DIR, f"account_{account_id}")


def _build_proxy(account: Account):
    if not account.proxy_host or not account.proxy_port:
        return None
    import socks
    type_map = {"HTTP": socks.HTTP, "SOCKS5": socks.SOCKS5, "SOCKS4": socks.SOCKS4}
    ptype = type_map.get((account.proxy_type or "HTTP").upper(), socks.HTTP)
    return (ptype, account.proxy_host, int(account.proxy_port), True,
            account.proxy_user or None, account.proxy_pass or None)


def _make_client(account: Account) -> TelegramClient:
    proxy = _build_proxy(account)
    if account.session_string:
        session = StringSession(account.session_string)
    else:
        session = _session_path(account.id)
    return TelegramClient(session, int(account.app_id), account.app_hash, proxy=proxy)


async def _save_session_string(account_id: int, client: TelegramClient):
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if acc:
            acc.session_string = client.session.save()
            db.commit()
    finally:
        db.close()


def _resolve_prompt(settings: Settings, account: Account, campaign: Campaign | None) -> str:
    """
    Resolve the active system prompt with priority:
    campaign.prompt_template > account.prompt_template > settings.system_prompt
    """
    if campaign and campaign.prompt_template_id and campaign.prompt_template:
        return campaign.prompt_template.system_prompt
    if account and account.prompt_template_id and account.prompt_template:
        return account.prompt_template.system_prompt
    return settings.system_prompt if settings else ""


def _is_in_dnc(db, username: str | None, tg_user_id: str | None) -> bool:
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


def _add_to_dnc(db, username: str | None, tg_user_id: str | None, reason: str):
    if not username and not tg_user_id:
        return
    existing = _is_in_dnc(db, username, tg_user_id)
    if not existing:
        db.add(DoNotContact(username=username, tg_user_id=tg_user_id, reason=reason))
        db.commit()


def _find_source_campaign(db, account_id: int, username: str | None) -> int | None:
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
        if provider == "openai" and not settings.openai_key:
            return
        if provider == "anthropic" and not getattr(settings, "anthropic_key", ""):
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
            openai_key=settings.openai_key or "",
            anthropic_key=getattr(settings, "anthropic_key", "") or "",
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


async def _set_needs_reauth(account_id: int, value: bool):
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if acc:
            acc.needs_reauth = value
            db.commit()
    finally:
        db.close()


async def start_client(account: Account) -> bool:
    if account.id in _clients:
        return True

    client = _make_client(account)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning(f"Account {account.id} session expired — needs re-auth")
            await client.disconnect()
            await _set_needs_reauth(account.id, True)
            return False

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
    except Exception as e:
        logger.error(f"Failed to start client {account.id}: {e}")
        await client.disconnect()
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
                needs_reauth = getattr(acc, "needs_reauth", False)
                has_session = acc.session_string or os.path.exists(_session_path(acc.id) + ".session")
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
                acc.session_string = session_str
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
                        acc.session_string = session_str
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
                available = [(aid, _clients[aid]) for aid in acc_ids if aid in _clients]
                if not available:
                    logger.warning(f"Campaign {campaign_id}: no accounts connected, retrying in 60s")
                    db.close()
                    await asyncio.sleep(60)
                    continue
                _account_id, client = random.choice(available)

                messages = json.loads(campaign.messages)
                text = random.choice(messages)
                text = _apply_personalization(text, target)

                try:
                    await client.send_message(target.username, text)
                    target.status = "sent"
                    target.sent_at = datetime.utcnow()
                    logger.info(f"Campaign {campaign_id}: sent to {target.username}")
                except FloodWaitError as e:
                    wait = e.seconds + 5
                    logger.warning(f"Campaign {campaign_id}: FloodWait {e.seconds}s, sleeping {wait}s")
                    db.commit()
                    db.close()
                    await asyncio.sleep(wait)
                    continue
                except PeerFloodError:
                    logger.error(f"Campaign {campaign_id}: PeerFloodError — pausing to protect account")
                    campaign.status = "paused"
                    db.commit()
                    break
                except (UserPrivacyRestrictedError, UsernameNotOccupiedError, UsernameInvalidError) as e:
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
