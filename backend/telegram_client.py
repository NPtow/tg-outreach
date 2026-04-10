"""
Telethon client manager + Campaign worker.
"""
import asyncio
import json
import logging
import os
import random
from datetime import datetime
from typing import Dict

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User

from backend.database import SessionLocal
from backend.models import Account, Campaign, CampaignTarget, Conversation, Message, Settings

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
    """Persist session string to DB so it survives restarts in cloud."""
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        if acc:
            acc.session_string = client.session.save()
            db.commit()
    finally:
        db.close()


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
        if not settings.openai_key:
            return

        tg_user_id = str(sender.id)
        text = event.message.text or ""

        conv = db.query(Conversation).filter(
            Conversation.account_id == account_id,
            Conversation.tg_user_id == tg_user_id
        ).first()

        if not conv:
            conv = Conversation(
                account_id=account_id,
                tg_user_id=tg_user_id,
                tg_username=sender.username or "",
                tg_first_name=sender.first_name or "",
                tg_last_name=sender.last_name or "",
            )
            db.add(conv)
            db.flush()

        if conv.status == "paused":
            msg = Message(conversation_id=conv.id, role="user", text=text)
            db.add(msg)
            conv.last_message = text
            conv.last_message_at = datetime.utcnow()
            db.commit()
            return

        msg = Message(conversation_id=conv.id, role="user", text=text)
        db.add(msg)
        db.flush()

        history = db.query(Message).filter(
            Message.conversation_id == conv.id
        ).order_by(Message.created_at.desc()).limit(settings.context_messages).all()
        history = list(reversed(history))
        db.commit()

        from backend.gpt_handler import generate_reply
        reply = await generate_reply(
            openai_key=settings.openai_key,
            model=settings.model,
            system_prompt=settings.system_prompt,
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
                })
    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
    finally:
        db.close()


async def start_client(account: Account) -> bool:
    if account.id in _clients:
        return True

    client = _make_client(account)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            logger.warning(f"Account {account.id} not authorized")
            await client.disconnect()
            return False

        await _save_session_string(account.id, client)

        @client.on(events.NewMessage())
        async def handler(event):
            await _handle_message(account.id, event)

        _clients[account.id] = client
        task = asyncio.create_task(_run_client(client, account.id))
        _tasks[account.id] = task

        logger.info(f"Started client for account {account.id} ({account.phone})")
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
    finally:
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


async def _campaign_worker(campaign_id: int):
    logger.info(f"Campaign {campaign_id} worker started")
    try:
        while True:
            db = SessionLocal()
            try:
                campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
                if not campaign or campaign.status != "running":
                    break

                # Check daily limit
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

                # Next pending target
                target = db.query(CampaignTarget).filter(
                    CampaignTarget.campaign_id == campaign_id,
                    CampaignTarget.status == "pending",
                ).first()

                if not target:
                    campaign.status = "done"
                    db.commit()
                    logger.info(f"Campaign {campaign_id}: all targets done")
                    break

                client = _clients.get(campaign.account_id)
                if not client:
                    logger.warning(f"Campaign {campaign_id}: account not connected, retrying in 60s")
                    db.close()
                    await asyncio.sleep(60)
                    continue

                messages = json.loads(campaign.messages)
                text = random.choice(messages)

                try:
                    await client.send_message(target.username, text)
                    target.status = "sent"
                    target.sent_at = datetime.utcnow()
                    logger.info(f"Campaign {campaign_id}: sent to {target.username}")
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

            delay = random.randint(
                db.query(Campaign).filter(Campaign.id == campaign_id).first().delay_min if False else 30,
                90
            )
            # Re-fetch delay from DB
            db2 = SessionLocal()
            try:
                c = db2.query(Campaign).filter(Campaign.id == campaign_id).first()
                if c:
                    delay = random.randint(c.delay_min, c.delay_max)
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
