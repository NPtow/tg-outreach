"""
Warming Worker — Human Imitation Engine.

Runs as a per-account asyncio task. Simulates realistic Telegram user behaviour:
online sessions, typing, mutual messaging, channel subscriptions, reactions, searches.

Phases (driven by WarmingProfile):
  1 — mutual messages + online presence only
  2 — add channel subscriptions + reactions + searches
  3 — full activity; if permanent_maintenance → moves to maintenance after phase_1+2+3 days
  maintenance — minimal keep-alive actions forever
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta, date
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, PeerFloodError, UserPrivacyRestrictedError, \
    ChatWriteForbiddenError, ChannelPrivateError, UserNotMutualContactError
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import ReactionEmoji

from backend.database import SessionLocal
from backend.models import AccountWarming, WarmingAction, WarmingChannelPool, Account

logger = logging.getLogger(__name__)

# ─── global registry of running workers ────────────────────────────────────────
_workers: dict[int, "WarmingWorker"] = {}   # keyed by account_warming_id


def get_worker(warming_id: int) -> Optional["WarmingWorker"]:
    return _workers.get(warming_id)


# ─── Timing helpers ─────────────────────────────────────────────────────────────

def gaussian_delay(mean: float, sigma: float, min_val: float = 1.0) -> float:
    return max(min_val, random.gauss(mean, sigma))


def _msk_hour() -> int:
    return (datetime.utcnow() + timedelta(hours=3)).hour


def _weekday() -> int:
    return datetime.utcnow().weekday()


_HOUR_WEIGHT = {
    8: 0.4, 9: 0.7, 10: 1.0, 11: 1.0, 12: 0.9,
    13: 0.7, 14: 0.8, 15: 0.9, 16: 0.9, 17: 0.8,
    18: 0.7, 19: 1.0, 20: 1.0, 21: 0.9, 22: 0.6, 23: 0.3,
}


def _should_act_now() -> bool:
    h = _msk_hour()
    day_w = 0.65 if _weekday() >= 5 else 1.0
    prob = _HOUR_WEIGHT.get(h, 0.0) * day_w
    return random.random() < prob


# ─── Small-talk templates for mutual messaging ──────────────────────────────────

_MUTUAL_POOL = [
    ["Привет", "Привет!", "Здарова", "Хей", "Даров"],
    ["Как дела?", "Всё норм?", "Что делаешь?", "Как ты?"],
    ["Норм", "Всё ок", "Хорошо, спасибо", "Да, ок"],
    ["Окей", "Понял", "Ок, понял", "Ясно"],
    ["Слушай, ты сегодня чем занимаешься?", "Есть время?"],
    ["Отлично", "Круто", "Хорошо"],
    ["Давай", "Окей, договорились", "Хорошо, потом"],
]

_SEARCH_QUERIES = [
    "новости", "работа удалённо", "маркетинг", "стартапы", "инвестиции",
    "python разработка", "дизайн", "бизнес идеи", "технологии 2025",
    "путешествия", "рецепты", "спорт", "кино", "музыка", "подкасты",
    "финансы", "криптовалюта", "нейросети", "ии",
]

_REACTIONS = ["👍", "❤️", "🔥", "🎉", "👏", "🤔", "😮", "💯", "😁", "🙏"]


# ─── DB helpers ─────────────────────────────────────────────────────────────────

def _get_warming(warming_id: int) -> Optional[AccountWarming]:
    db = SessionLocal()
    try:
        return db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
    finally:
        db.close()


def _log_action(warming_id: int, action_type: str, target: str, result: str,
                flood_wait_seconds: int = None, details: dict = None):
    db = SessionLocal()
    try:
        entry = WarmingAction(
            account_warming_id=warming_id,
            action_type=action_type,
            target=target,
            result=result,
            flood_wait_seconds=flood_wait_seconds,
            details=json.dumps(details) if details else None,
        )
        db.add(entry)
        # update counters
        w = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if w and result == "success":
            today = date.today()
            if w.actions_today_date != today:
                w.actions_today = 0
                w.actions_today_date = today
            w.actions_today += 1
            w.total_actions += 1
            w.last_action_at = datetime.utcnow()
        if w and result == "flood_wait":
            w.ban_events += 1
        db.commit()
    except Exception as e:
        logger.error(f"Warming log error: {e}")
    finally:
        db.close()


def _update_health(warming_id: int):
    db = SessionLocal()
    try:
        w = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not w:
            return
        score = 0
        days_alive = max(0, (datetime.utcnow() - w.started_at).days)
        score += min(30, days_alive * 2)
        score += min(25, w.total_actions // 10)
        ban_penalty = min(25, w.ban_events * 8)
        score += max(0, 25 - ban_penalty)
        phase_pts = {1: 5, 2: 12, 3: 20}
        score += phase_pts.get(w.phase, 0)
        w.health_score = min(100, score)
        db.commit()
    finally:
        db.close()


def _advance_phase(warming_id: int):
    """Check if it's time to move to the next phase."""
    db = SessionLocal()
    try:
        w = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not w or w.status != "warming":
            return
        p = w.profile
        now = datetime.utcnow()
        days_in_phase = (now - w.phase_started_at).days

        if w.phase == 1 and days_in_phase >= p.phase_1_days:
            w.phase = 2
            w.phase_started_at = now
            logger.info(f"Warming {warming_id}: → phase 2")
        elif w.phase == 2 and days_in_phase >= p.phase_2_days:
            w.phase = 3
            w.phase_started_at = now
            logger.info(f"Warming {warming_id}: → phase 3")
        elif w.phase == 3 and p.permanent_maintenance:
            # phase 3 has no fixed end — check if we've been here long enough (another 14 days)
            if days_in_phase >= 14:
                w.status = "maintenance"
                logger.info(f"Warming {warming_id}: → maintenance (permanent)")
        db.commit()
    finally:
        db.close()


def _get_phase_config(warming_id: int) -> dict:
    db = SessionLocal()
    try:
        w = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not w:
            return {}
        if w.status == "maintenance":
            return json.loads(w.profile.maintenance_config)
        configs = {1: w.profile.phase_1_config, 2: w.profile.phase_2_config, 3: w.profile.phase_3_config}
        return json.loads(configs.get(w.phase, w.profile.phase_3_config))
    finally:
        db.close()


def _get_peer_clients(warming_id: int):
    """Return list of (peer_account_id, peer_warming_id) for mutual messaging."""
    from backend.telegram_client import _clients
    db = SessionLocal()
    try:
        w = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not w:
            return []
        peer_ids = json.loads(w.peer_account_ids or "[]")
        result = []
        for pid in peer_ids:
            if pid in _clients:
                peer_w = db.query(AccountWarming).filter(
                    AccountWarming.account_id == pid,
                    AccountWarming.status.in_(["warming", "maintenance"])
                ).first()
                if peer_w:
                    result.append((pid, peer_w.id))
        return result
    finally:
        db.close()


def _pick_channels(warming_id: int, count: int) -> list[str]:
    """Pick random channels from pool, excluding already subscribed."""
    db = SessionLocal()
    try:
        w = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        subscribed = json.loads(w.subscribed_channels or "[]") if w else []
        pool = db.query(WarmingChannelPool).filter(
            WarmingChannelPool.is_active == True,
            WarmingChannelPool.username.notin_(subscribed)
        ).all()
        chosen = random.sample(pool, min(count, len(pool)))
        return [c.username for c in chosen]
    finally:
        db.close()


def _mark_subscribed(warming_id: int, channel: str):
    db = SessionLocal()
    try:
        w = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if w:
            subs = json.loads(w.subscribed_channels or "[]")
            if channel not in subs:
                subs.append(channel)
            w.subscribed_channels = json.dumps(subs)
            db.commit()
    finally:
        db.close()


def _get_account_phone(account_id: int) -> Optional[str]:
    db = SessionLocal()
    try:
        acc = db.query(Account).filter(Account.id == account_id).first()
        return acc.phone if acc else None
    finally:
        db.close()


# ─── Individual actions ─────────────────────────────────────────────────────────

async def _online_session(client: TelegramClient, warming_id: int):
    """Go online for a random human-like duration, then go offline."""
    minutes = max(1.0, random.gauss(6, 3))
    await client(UpdateStatusRequest(offline=False))
    _log_action(warming_id, "online", "self", "success")
    await asyncio.sleep(minutes * 60)
    await client(UpdateStatusRequest(offline=True))
    _log_action(warming_id, "offline", "self", "success")


async def _send_message_human(client: TelegramClient, chat, text: str):
    """Send message with realistic typing simulation."""
    typing_secs = max(1.5, min(len(text) * random.gauss(0.09, 0.02), 15))
    async with client.action(chat, "typing"):
        await asyncio.sleep(typing_secs)
    await client.send_message(chat, text)


async def _mutual_message(warming_id: int, peer_account_id: int):
    """Short back-and-forth exchange with a peer account."""
    from backend.telegram_client import _clients
    client = _clients.get(_get_warming_account_id(warming_id))
    peer_client = _clients.get(peer_account_id)
    if not client or not peer_client:
        return

    peer_phone = _get_account_phone(peer_account_id)
    if not peer_phone:
        return

    try:
        peer_entity = await client.get_entity(peer_phone)
        my_entity = await peer_client.get_entity(_get_account_phone(_get_warming_account_id(warming_id)))
        exchanges = random.randint(2, 4)
        for i in range(exchanges):
            msg = random.choice(random.choice(_MUTUAL_POOL))
            if i % 2 == 0:
                await _send_message_human(client, peer_entity, msg)
                _log_action(warming_id, "msg_sent", peer_phone, "success")
                await asyncio.sleep(gaussian_delay(40, 18, 8))
                # peer replies
                reply = random.choice(random.choice(_MUTUAL_POOL))
                await _send_message_human(peer_client, my_entity, reply)
            else:
                await asyncio.sleep(gaussian_delay(25, 12, 5))
    except (UserPrivacyRestrictedError, UserNotMutualContactError):
        _log_action(warming_id, "msg_sent", peer_phone, "skipped", details={"reason": "privacy"})
    except Exception as e:
        _log_action(warming_id, "msg_sent", str(peer_account_id), "failed", details={"error": str(e)})


async def _subscribe_channel(client: TelegramClient, warming_id: int, username: str):
    """Join a channel then read a few recent posts."""
    await asyncio.sleep(gaussian_delay(5, 2, 2))
    try:
        await client(JoinChannelRequest(username))
        _mark_subscribed(warming_id, username)
        _log_action(warming_id, "subscribe", username, "success")
        # simulate reading
        await asyncio.sleep(gaussian_delay(6, 2, 2))
        entity = await client.get_entity(username)
        await client.get_messages(entity, limit=random.randint(3, 8))
        await asyncio.sleep(gaussian_delay(25, 12, 8))
    except ChannelPrivateError:
        _log_action(warming_id, "subscribe", username, "skipped", details={"reason": "private"})
    except FloodWaitError as e:
        _log_action(warming_id, "subscribe", username, "flood_wait", flood_wait_seconds=e.seconds)
        raise
    except Exception as e:
        _log_action(warming_id, "subscribe", username, "failed", details={"error": str(e)})


async def _react_to_post(client: TelegramClient, warming_id: int, channel_username: str):
    """Read a few posts in a subscribed channel and react to one."""
    try:
        entity = await client.get_entity(channel_username)
        messages = await client.get_messages(entity, limit=10)
        if not messages:
            return
        target = random.choice(messages[:5])
        await asyncio.sleep(gaussian_delay(10, 5, 3))
        reaction = random.choice(_REACTIONS)
        await client(SendReactionRequest(
            peer=entity,
            msg_id=target.id,
            reaction=[ReactionEmoji(emoticon=reaction)],
        ))
        _log_action(warming_id, "react", f"{channel_username}#{target.id}", "success",
                    details={"reaction": reaction})
    except FloodWaitError as e:
        _log_action(warming_id, "react", channel_username, "flood_wait", flood_wait_seconds=e.seconds)
        raise
    except Exception as e:
        _log_action(warming_id, "react", channel_username, "failed", details={"error": str(e)})


async def _search(client: TelegramClient, warming_id: int):
    """Simulate searching for Telegram content."""
    query = random.choice(_SEARCH_QUERIES)
    try:
        await client(SearchRequest(q=query, limit=random.randint(3, 8)))
        await asyncio.sleep(gaussian_delay(12, 6, 4))
        _log_action(warming_id, "search", query, "success")
    except Exception as e:
        _log_action(warming_id, "search", query, "failed", details={"error": str(e)})


async def _read_dialogs(client: TelegramClient, warming_id: int):
    """Open a few dialogs and mark them as read."""
    try:
        dialogs = await client.get_dialogs(limit=random.randint(3, 7))
        for d in dialogs:
            await client.get_messages(d, limit=random.randint(3, 6))
            await asyncio.sleep(gaussian_delay(20, 10, 5))
        _log_action(warming_id, "read_dialog", f"{len(dialogs)} dialogs", "success")
    except Exception as e:
        _log_action(warming_id, "read_dialog", "", "failed", details={"error": str(e)})


def _get_warming_account_id(warming_id: int) -> Optional[int]:
    db = SessionLocal()
    try:
        w = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        return w.account_id if w else None
    finally:
        db.close()


# ─── Main worker class ───────────────────────────────────────────────────────────

class WarmingWorker:
    def __init__(self, warming_id: int):
        self.warming_id = warming_id
        self._stop = asyncio.Event()
        self._task: Optional[asyncio.Task] = None

    def start(self):
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=f"warming-{self.warming_id}")
        _workers[self.warming_id] = self

    def stop(self):
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
        _workers.pop(self.warming_id, None)

    async def _run(self):
        logger.info(f"Warming worker {self.warming_id} started")
        try:
            while not self._stop.is_set():
                if not _should_act_now():
                    await asyncio.sleep(gaussian_delay(1200, 240, 300))
                    continue

                _advance_phase(self.warming_id)
                _update_health(self.warming_id)

                db = SessionLocal()
                try:
                    w = db.query(AccountWarming).filter(AccountWarming.id == self.warming_id).first()
                    if not w or w.status == "paused" or w.status == "completed":
                        await asyncio.sleep(60)
                        continue
                finally:
                    db.close()

                await self._execute_burst()

                # Pause between bursts: Gaussian around 40 min
                pause = gaussian_delay(2400, 720, 600)
                await asyncio.sleep(pause)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Warming worker {self.warming_id} crashed: {e}", exc_info=True)
        finally:
            _workers.pop(self.warming_id, None)

    async def _execute_burst(self):
        from backend.telegram_client import _clients
        account_id = _get_warming_account_id(self.warming_id)
        if not account_id:
            return
        client = _clients.get(account_id)
        if not client:
            return

        config = _get_phase_config(self.warming_id)
        actions = self._build_action_list(client, config)
        if not actions:
            return

        random.shuffle(actions)
        burst_size = random.randint(2, min(4, len(actions)))

        for action_fn in actions[:burst_size]:
            if self._stop.is_set():
                break
            try:
                await action_fn()
                await asyncio.sleep(gaussian_delay(35, 18, 8))
            except FloodWaitError as e:
                wait = e.seconds + int(gaussian_delay(30, 10, 10))
                logger.warning(f"Warming {self.warming_id}: FloodWait {e.seconds}s")
                await asyncio.sleep(wait)
            except PeerFloodError:
                logger.warning(f"Warming {self.warming_id}: PeerFlood — pausing 2h")
                _log_action(self.warming_id, "peer_flood", "", "flood_wait",
                            details={"pause_seconds": 7200})
                db = SessionLocal()
                try:
                    w = db.query(AccountWarming).filter(AccountWarming.id == self.warming_id).first()
                    if w:
                        w.ban_events += 1
                        db.commit()
                finally:
                    db.close()
                await asyncio.sleep(7200)
                break
            except Exception as e:
                logger.debug(f"Warming {self.warming_id} action error: {e}")

    def _build_action_list(self, client, config: dict) -> list:
        """Build list of callable action coroutines based on phase config."""
        actions = []
        wid = self.warming_id

        online_quota = config.get("online_sessions_per_day", 4)
        if online_quota > 0:
            actions.append(lambda: _online_session(client, wid))

        msg_quota = config.get("mutual_messages_per_day", 0)
        if msg_quota > 0:
            peers = _get_peer_clients(wid)
            if peers:
                peer_id, _ = random.choice(peers)
                actions.append(lambda pid=peer_id: _mutual_message(wid, pid))

        sub_quota = config.get("subscriptions_per_day", 0)
        if sub_quota > 0:
            channels = _pick_channels(wid, sub_quota)
            for ch in channels:
                actions.append(lambda c=ch: _subscribe_channel(client, wid, c))

        react_quota = config.get("reactions_per_day", 0)
        if react_quota > 0:
            db = SessionLocal()
            try:
                w = db.query(AccountWarming).filter(AccountWarming.id == wid).first()
                subs = json.loads(w.subscribed_channels or "[]") if w else []
            finally:
                db.close()
            if subs:
                ch = random.choice(subs)
                actions.append(lambda c=ch: _react_to_post(client, wid, c))

        search_quota = config.get("searches_per_day", 0)
        if search_quota > 0:
            actions.append(lambda: _search(client, wid))

        dialog_quota = config.get("dialog_reads_per_day", 0)
        if dialog_quota > 0:
            actions.append(lambda: _read_dialogs(client, wid))

        return actions


# ─── Manager: start all warming tasks on boot ────────────────────────────────────

async def start_all_warming_tasks():
    """Called on app startup — resume all active warming tasks."""
    db = SessionLocal()
    try:
        warmings = db.query(AccountWarming).filter(
            AccountWarming.status.in_(["warming", "maintenance"])
        ).all()
        ids = [w.id for w in warmings]
    finally:
        db.close()

    for wid in ids:
        if wid not in _workers:
            worker = WarmingWorker(wid)
            worker.start()
            logger.info(f"Resumed warming task {wid}")


def restart_warming_for_account(account_id: int):
    """Called by supervisor when account reconnects."""
    db = SessionLocal()
    try:
        w = db.query(AccountWarming).filter(
            AccountWarming.account_id == account_id,
            AccountWarming.status.in_(["warming", "maintenance"])
        ).first()
        if w and w.id not in _workers:
            worker = WarmingWorker(w.id)
            worker.start()
            logger.info(f"Restarted warming {w.id} after account {account_id} reconnect")
    finally:
        db.close()
