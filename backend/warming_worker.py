"""
Warming worker.

Runs one asyncio task per warming profile and keeps the process observable:
- forces an initial burst after start/resume;
- persists worker heartbeat and next wake-up;
- logs every action as attempted -> final result;
- respects per-type daily quotas instead of treating them as booleans.
"""

import asyncio
import json
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChatWriteForbiddenError,
    FloodWaitError,
    PeerFloodError,
    RPCError,
    UserNotMutualContactError,
    UserPrivacyRestrictedError,
)
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.contacts import SearchRequest
from telethon.tl.functions.messages import SendReactionRequest
from telethon.tl.types import InputChannel, ReactionEmoji

from backend.database import SessionLocal
from backend.models import Account, AccountWarming, WarmingAction, WarmingChannelPool

logger = logging.getLogger(__name__)

_workers: dict[int, "WarmingWorker"] = {}

_HOUR_WEIGHT = {
    8: 0.4,
    9: 0.7,
    10: 1.0,
    11: 1.0,
    12: 0.9,
    13: 0.7,
    14: 0.8,
    15: 0.9,
    16: 0.9,
    17: 0.8,
    18: 0.7,
    19: 1.0,
    20: 1.0,
    21: 0.9,
    22: 0.6,
    23: 0.3,
}

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
    "новости",
    "работа удалённо",
    "маркетинг",
    "стартапы",
    "инвестиции",
    "python разработка",
    "дизайн",
    "бизнес идеи",
    "технологии 2025",
    "путешествия",
    "рецепты",
    "спорт",
    "кино",
    "музыка",
    "подкасты",
    "финансы",
    "криптовалюта",
    "нейросети",
    "ии",
]

_REACTIONS = ["👍", "❤️", "🔥", "🎉", "👏", "🤔", "😮", "💯", "😁", "🙏"]

_ACTION_COUNTER_FIELDS = {
    "online_session": "online_sessions_today",
    "subscribe": "subscriptions_today",
    "react": "reactions_today",
    "search": "searches_today",
    "read_dialog": "dialog_reads_today",
    "msg_sent": "mutual_messages_today",
}

_DAILY_COUNTER_FIELDS = [
    "actions_today",
    "online_sessions_today",
    "subscriptions_today",
    "reactions_today",
    "searches_today",
    "dialog_reads_today",
    "mutual_messages_today",
]


class ActionSkip(Exception):
    def __init__(self, reason: str, details: Optional[dict[str, Any]] = None):
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


@dataclass
class PlannedAction:
    action_type: str
    target: Optional[str]
    runner: Callable[[], Awaitable[Optional[dict[str, Any]]]]
    decision_context: dict[str, Any]


def get_worker(warming_id: int) -> Optional["WarmingWorker"]:
    return _workers.get(warming_id)


def gaussian_delay(mean: float, sigma: float, min_val: float = 1.0) -> float:
    return max(min_val, random.gauss(mean, sigma))


def _msk_hour() -> int:
    return (datetime.utcnow() + timedelta(hours=3)).hour


def _weekday() -> int:
    return datetime.utcnow().weekday()


def _should_act_now() -> bool:
    hour = _msk_hour()
    weekday_weight = 0.65 if _weekday() >= 5 else 1.0
    probability = _HOUR_WEIGHT.get(hour, 0.0) * weekday_weight
    return random.random() < probability


def _loads_json(raw: Optional[str], default: Any):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _parse_iso_datetime(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _normalize_blocked_actions(raw: Optional[str]) -> dict[str, dict[str, Any]]:
    blocks = _loads_json(raw, {})
    if not isinstance(blocks, dict):
        return {}

    normalized: dict[str, dict[str, Any]] = {}
    now = datetime.utcnow()
    for action_key, entry in blocks.items():
        if not isinstance(entry, dict):
            continue
        until = _parse_iso_datetime(entry.get("until"))
        if until and until <= now:
            continue
        normalized[action_key] = {
            "reason": entry.get("reason", "temporarily_blocked"),
            "until": until.isoformat() if until else None,
            "details": entry.get("details") if isinstance(entry.get("details"), dict) else {},
        }
    return normalized


def _get_active_block(blocked_actions: dict[str, Any], action_key: str) -> Optional[dict[str, Any]]:
    block = blocked_actions.get(action_key)
    if not isinstance(block, dict):
        return None
    until = _parse_iso_datetime(block.get("until"))
    if until and until <= datetime.utcnow():
        return None
    return block


def _reset_daily_counters(warming: AccountWarming):
    today = date.today()
    if warming.actions_today_date == today:
        for field in _DAILY_COUNTER_FIELDS:
            if getattr(warming, field) is None:
                setattr(warming, field, 0)
        return

    warming.actions_today_date = today
    for field in _DAILY_COUNTER_FIELDS:
        setattr(warming, field, 0)


def _apply_health_score(warming: AccountWarming):
    days_alive = max(0, (datetime.utcnow() - warming.started_at).days)
    total_actions = warming.total_actions or 0
    successful_today = warming.actions_today or 0
    phase_bonus = 6 if warming.status == "maintenance" else {1: 2, 2: 5, 3: 8}.get(warming.phase, 0)
    ban_penalty = min(45, (warming.ban_events or 0) * 12)

    if total_actions == 0:
        warming.health_score = min(5, phase_bonus)
        return

    action_score = min(55, total_actions * 3)
    age_score = min(20, days_alive * 2)
    consistency_score = min(15, successful_today * 2)
    score = action_score + age_score + consistency_score + phase_bonus - ban_penalty
    warming.health_score = max(0, min(100, int(score)))


def _get_warming(warming_id: int) -> Optional[AccountWarming]:
    db = SessionLocal()
    try:
        return db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
    finally:
        db.close()


def _get_warming_account_id(warming_id: int) -> Optional[int]:
    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        return warming.account_id if warming else None
    finally:
        db.close()


def _get_account_phone(account_id: int) -> Optional[str]:
    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        return account.phone if account else None
    finally:
        db.close()


def _touch_warming(warming_id: int, **updates):
    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not warming:
            return
        _reset_daily_counters(warming)
        updates.setdefault("last_tick_at", datetime.utcnow())
        for field, value in updates.items():
            if hasattr(warming, field):
                setattr(warming, field, value)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to update warming heartbeat", extra={"warming_id": warming_id})
    finally:
        db.close()


def _block_action(
    warming_id: int,
    action_key: str,
    *,
    reason: str,
    cooldown: timedelta,
    details: Optional[dict[str, Any]] = None,
):
    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not warming:
            return
        blocks = _normalize_blocked_actions(warming.blocked_actions)
        until = datetime.utcnow() + cooldown
        blocks[action_key] = {
            "reason": reason,
            "until": until.isoformat(),
            "details": details or {},
        }
        warming.blocked_actions = json.dumps(blocks)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to block warming action", extra={"warming_id": warming_id, "action_key": action_key})
    finally:
        db.close()


def _clear_action_block(warming_id: int, action_key: str):
    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not warming:
            return
        blocks = _normalize_blocked_actions(warming.blocked_actions)
        if action_key not in blocks:
            return
        blocks.pop(action_key, None)
        warming.blocked_actions = json.dumps(blocks)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to clear warming action block", extra={"warming_id": warming_id, "action_key": action_key})
    finally:
        db.close()


def _update_health(warming_id: int):
    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not warming:
            return
        _reset_daily_counters(warming)
        _apply_health_score(warming)
        db.commit()
    finally:
        db.close()


def _advance_phase(warming_id: int):
    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not warming or warming.status != "warming":
            return

        profile = warming.profile
        now = datetime.utcnow()
        days_in_phase = (now - warming.phase_started_at).days
        changed = False

        if warming.phase == 1 and days_in_phase >= profile.phase_1_days:
            warming.phase = 2
            warming.phase_started_at = now
            changed = True
            logger.info("Warming %s -> phase 2", warming_id)
        elif warming.phase == 2 and days_in_phase >= profile.phase_2_days:
            warming.phase = 3
            warming.phase_started_at = now
            changed = True
            logger.info("Warming %s -> phase 3", warming_id)
        elif warming.phase == 3 and profile.permanent_maintenance and days_in_phase >= 14:
            warming.status = "maintenance"
            changed = True
            logger.info("Warming %s -> maintenance", warming_id)

        if changed:
            db.commit()
    finally:
        db.close()


def _get_phase_config(warming_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not warming:
            return {}
        if warming.status == "maintenance":
            return _loads_json(warming.profile.maintenance_config, {})
        configs = {
            1: warming.profile.phase_1_config,
            2: warming.profile.phase_2_config,
            3: warming.profile.phase_3_config,
        }
        return _loads_json(configs.get(warming.phase, warming.profile.phase_3_config), {})
    finally:
        db.close()


def _get_peer_clients(warming_id: int) -> list[tuple[int, int]]:
    from backend.telegram_client import _clients

    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not warming:
            return []

        peer_ids = _loads_json(warming.peer_account_ids, [])
        result = []
        for peer_id in peer_ids:
            if peer_id not in _clients:
                continue
            peer_warming = (
                db.query(AccountWarming)
                .filter(
                    AccountWarming.account_id == peer_id,
                    AccountWarming.status.in_(["warming", "maintenance"]),
                )
                .first()
            )
            if peer_warming:
                result.append((peer_id, peer_warming.id))
        return result
    finally:
        db.close()


def _channel_candidate(channel: WarmingChannelPool) -> dict[str, Any]:
    return {
        "username": channel.username,
        "title": channel.title,
        "verification_status": channel.verification_status or "unknown",
        "entity_type": channel.entity_type,
        "peer_id": channel.peer_id,
        "access_hash": channel.access_hash,
        "invite_link": channel.invite_link,
        "resolve_fail_count": channel.resolve_fail_count or 0,
    }


def _channel_input(candidate: Optional[dict[str, Any]]) -> Optional[InputChannel]:
    if not candidate:
        return None
    peer_id = candidate.get("peer_id")
    access_hash = candidate.get("access_hash")
    if peer_id is None or access_hash is None:
        return None
    try:
        return InputChannel(int(peer_id), int(access_hash))
    except (TypeError, ValueError):
        return None


def _record_channel_verification(
    username: str,
    entity: Any,
    *,
    resolution_method: Optional[str] = None,
):
    db = SessionLocal()
    try:
        channel = (
            db.query(WarmingChannelPool)
            .filter(WarmingChannelPool.username == username.lstrip("@"))
            .first()
        )
        if not channel:
            return
        channel.entity_type = entity.__class__.__name__
        channel.peer_id = str(getattr(entity, "id", ""))
        access_hash = getattr(entity, "access_hash", None)
        channel.access_hash = str(access_hash) if access_hash is not None else None
        if not channel.title:
            channel.title = getattr(entity, "title", None)
        channel.verification_status = "verified"
        channel.last_verified_at = datetime.utcnow()
        channel.last_resolve_error = None
        channel.resolve_fail_count = 0
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to persist warming channel verification",
            extra={"username": username, "resolution_method": resolution_method},
        )
    finally:
        db.close()


def _record_channel_resolve_failure(username: str, error_message: str):
    db = SessionLocal()
    try:
        channel = (
            db.query(WarmingChannelPool)
            .filter(WarmingChannelPool.username == username.lstrip("@"))
            .first()
        )
        if not channel:
            return
        channel.resolve_fail_count = (channel.resolve_fail_count or 0) + 1
        channel.last_resolve_error = error_message
        if (channel.resolve_fail_count or 0) >= 3:
            channel.verification_status = "resolve_failed"
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to persist warming channel resolve failure", extra={"username": username})
    finally:
        db.close()


def _get_channel_candidate_by_username(username: str) -> Optional[dict[str, Any]]:
    db = SessionLocal()
    try:
        channel = (
            db.query(WarmingChannelPool)
            .filter(WarmingChannelPool.username == username.lstrip("@"))
            .first()
        )
        return _channel_candidate(channel) if channel else None
    finally:
        db.close()


def _pick_channels(warming_id: int, count: int, *, verified_only: bool = False) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        subscribed = _loads_json(warming.subscribed_channels if warming else "[]", [])
        query = (
            db.query(WarmingChannelPool)
            .filter(
                WarmingChannelPool.is_active.is_(True),
                WarmingChannelPool.username.notin_(subscribed),
            )
        )
        if verified_only:
            query = query.filter(WarmingChannelPool.verification_status == "verified")
        pool = query.all()
        if not pool:
            return []
        random.shuffle(pool)
        pool.sort(
            key=lambda channel: (
                0 if (channel.verification_status or "unknown") == "verified" else 1,
                channel.resolve_fail_count or 0,
            )
        )
        chosen = pool[: min(count, len(pool))]
        return [_channel_candidate(channel) for channel in chosen]
    finally:
        db.close()


def _mark_subscribed(warming_id: int, channel_username: str):
    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not warming:
            return
        subscribed = _loads_json(warming.subscribed_channels, [])
        if channel_username not in subscribed:
            subscribed.append(channel_username)
            warming.subscribed_channels = json.dumps(subscribed)
            db.commit()
    finally:
        db.close()


def _get_warming_state(warming_id: int) -> Optional[dict[str, Any]]:
    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not warming:
            return None
        _reset_daily_counters(warming)
        db.commit()
        return {
            "account_id": warming.account_id,
            "status": warming.status,
            "phase": warming.phase,
            "peer_account_ids": _loads_json(warming.peer_account_ids, []),
            "subscribed_channels": _loads_json(warming.subscribed_channels, []),
            "blocked_actions": _normalize_blocked_actions(warming.blocked_actions),
            "online_sessions_today": warming.online_sessions_today or 0,
            "subscriptions_today": warming.subscriptions_today or 0,
            "reactions_today": warming.reactions_today or 0,
            "searches_today": warming.searches_today or 0,
            "dialog_reads_today": warming.dialog_reads_today or 0,
            "mutual_messages_today": warming.mutual_messages_today or 0,
        }
    finally:
        db.close()


def _begin_action(
    warming_id: int,
    action_type: str,
    target: Optional[str],
    decision_context: Optional[dict[str, Any]] = None,
) -> Optional[int]:
    db = SessionLocal()
    try:
        warming = db.query(AccountWarming).filter(AccountWarming.id == warming_id).first()
        if not warming:
            return None
        _reset_daily_counters(warming)
        now = datetime.utcnow()
        action = WarmingAction(
            account_warming_id=warming_id,
            action_type=action_type,
            target=target,
            result="attempted",
            attempted_at=now,
            executed_at=now,
            decision_context=json.dumps(decision_context) if decision_context else None,
        )
        warming.last_tick_at = now
        warming.last_decision = f"attempted:{action_type}"
        db.add(action)
        db.commit()
        db.refresh(action)
        return action.id
    except Exception:
        db.rollback()
        logger.exception(
            "Failed to create warming action",
            extra={"warming_id": warming_id, "action_type": action_type, "target": target},
        )
        return None
    finally:
        db.close()


def _finish_action(
    action_id: Optional[int],
    result: str,
    *,
    details: Optional[dict[str, Any]] = None,
    error_message: Optional[str] = None,
    flood_wait_seconds: Optional[int] = None,
):
    if not action_id:
        return

    db = SessionLocal()
    try:
        action = db.query(WarmingAction).filter(WarmingAction.id == action_id).first()
        if not action:
            return
        warming = db.query(AccountWarming).filter(AccountWarming.id == action.account_warming_id).first()
        if not warming:
            return

        _reset_daily_counters(warming)
        now = datetime.utcnow()
        action.result = result
        action.completed_at = now
        action.error_message = error_message
        action.flood_wait_seconds = flood_wait_seconds
        action.details = json.dumps(details) if details else None

        warming.last_tick_at = now
        warming.last_decision = f"{result}:{action.action_type}"

        if result == "success":
            warming.actions_today = (warming.actions_today or 0) + 1
            warming.total_actions = (warming.total_actions or 0) + 1
            warming.last_action_at = now
            warming.last_success_at = now
            counter_field = _ACTION_COUNTER_FIELDS.get(action.action_type)
            if counter_field:
                setattr(warming, counter_field, (getattr(warming, counter_field) or 0) + 1)
        elif result == "flood_wait":
            warming.ban_events = (warming.ban_events or 0) + 1
            warming.last_error_at = now
            warming.last_error_message = error_message or f"Flood wait for {action.action_type}"
        elif result == "failed":
            warming.last_error_at = now
            warming.last_error_message = error_message or "Unknown warming action failure"
        elif result == "skipped" and error_message:
            warming.last_decision = f"skipped:{error_message}"

        _apply_health_score(warming)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to finalize warming action", extra={"action_id": action_id, "result": result})
    finally:
        db.close()


def _record_skipped_action(
    warming_id: int,
    action_type: str,
    *,
    target: Optional[str] = None,
    reason: str,
    decision_context: Optional[dict[str, Any]] = None,
):
    action_id = _begin_action(warming_id, action_type, target, decision_context)
    _finish_action(
        action_id,
        "skipped",
        details={"reason": reason},
        error_message=reason,
    )


async def _send_message_human(client: TelegramClient, chat, text: str):
    typing_seconds = max(1.5, min(len(text) * random.gauss(0.09, 0.02), 15))
    async with client.action(chat, "typing"):
        await asyncio.sleep(typing_seconds)
    await client.send_message(chat, text)


async def _online_session(client: TelegramClient) -> dict[str, Any]:
    minutes = max(1.0, random.gauss(6, 3))
    await client(UpdateStatusRequest(offline=False))
    await asyncio.sleep(minutes * 60)
    await client(UpdateStatusRequest(offline=True))
    return {"duration_seconds": int(minutes * 60)}


async def _mutual_message(warming_id: int, peer_account_id: int) -> dict[str, Any]:
    from backend.telegram_client import _clients

    account_id = _get_warming_account_id(warming_id)
    client = _clients.get(account_id) if account_id else None
    peer_client = _clients.get(peer_account_id)
    if not client or not peer_client:
        raise ActionSkip("peer_runtime_unavailable")

    peer_phone = _get_account_phone(peer_account_id)
    my_phone = _get_account_phone(account_id) if account_id else None
    if not peer_phone or not my_phone:
        raise ActionSkip("missing_peer_phone")

    try:
        peer_entity = await client.get_entity(peer_phone)
        my_entity = await peer_client.get_entity(my_phone)
        exchanges = random.randint(2, 4)
        sent = 0
        for idx in range(exchanges):
            message = random.choice(random.choice(_MUTUAL_POOL))
            if idx % 2 == 0:
                await _send_message_human(client, peer_entity, message)
                sent += 1
                await asyncio.sleep(gaussian_delay(40, 18, 8))
                reply = random.choice(random.choice(_MUTUAL_POOL))
                await _send_message_human(peer_client, my_entity, reply)
            else:
                await asyncio.sleep(gaussian_delay(25, 12, 5))
        return {"peer_account_id": peer_account_id, "peer_phone": peer_phone, "messages_sent": sent}
    except (UserPrivacyRestrictedError, UserNotMutualContactError):
        raise ActionSkip("privacy_restricted")
    except ChatWriteForbiddenError:
        raise ActionSkip("chat_write_forbidden")


async def _subscribe_channel(
    client: TelegramClient,
    warming_id: int,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    await asyncio.sleep(gaussian_delay(5, 2, 2))
    username = candidate["username"]
    current_account_id = _get_warming_account_id(warming_id)
    try:
        cached_input = _channel_input(candidate)
        resolution_method = "username"

        if cached_input is not None:
            try:
                await client(JoinChannelRequest(cached_input))
                entity = await client.get_entity(cached_input)
                resolution_method = "cached_peer"
            except Exception:
                entity = None
        else:
            entity = None

        if entity is None:
            try:
                await client(JoinChannelRequest(username))
                entity = await client.get_entity(username)
                _record_channel_verification(username, entity, resolution_method="username")
            except Exception as username_exc:
                resolved = await _resolve_channel_via_any_client(
                    username,
                    exclude_account_id=current_account_id,
                )
                resolved_input = _channel_input(resolved) if resolved else None
                if resolved_input is None:
                    raise username_exc
                await client(JoinChannelRequest(resolved_input))
                entity = await client.get_entity(resolved_input)
                resolution_method = "peer_verified"

        _mark_subscribed(warming_id, username)
        await asyncio.sleep(gaussian_delay(6, 2, 2))
        message_count = random.randint(3, 8)
        await client.get_messages(entity, limit=message_count)
        await asyncio.sleep(gaussian_delay(25, 12, 8))
        return {
            "channel": username,
            "messages_read": message_count,
            "resolution_method": resolution_method,
        }
    except ChannelPrivateError:
        raise ActionSkip("private_channel")


async def _react_to_post(client: TelegramClient, candidate: dict[str, Any]) -> dict[str, Any]:
    entity, resolution_method = await _resolve_channel_entity(client, candidate)
    channel_username = candidate["username"]
    messages = await client.get_messages(entity, limit=10)
    if not messages:
        raise ActionSkip("no_recent_messages")

    target = random.choice(messages[: min(5, len(messages))])
    reaction = random.choice(_REACTIONS)
    await asyncio.sleep(gaussian_delay(10, 5, 3))
    await client(
        SendReactionRequest(
            peer=entity,
            msg_id=target.id,
            reaction=[ReactionEmoji(emoticon=reaction)],
        )
    )
    return {
        "channel": channel_username,
        "message_id": target.id,
        "reaction": reaction,
        "resolution_method": resolution_method,
    }


async def _search(client: TelegramClient, query: str) -> dict[str, Any]:
    await client(SearchRequest(q=query, limit=random.randint(3, 8)))
    await asyncio.sleep(gaussian_delay(12, 6, 4))
    return {"query": query}


async def _read_dialogs(client: TelegramClient) -> dict[str, Any]:
    dialogs = await client.get_dialogs(limit=random.randint(3, 7))
    for dialog in dialogs:
        await client.get_messages(dialog, limit=random.randint(3, 6))
        await asyncio.sleep(gaussian_delay(20, 10, 5))
    return {"dialogs_read": len(dialogs)}


def _is_frozen_search_error(exc: Exception) -> bool:
    if not isinstance(exc, RPCError):
        return False
    return "FROZEN_METHOD_INVALID" in str(exc).upper()


def _is_username_resolve_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "no user has" in message
        or "nobody is using this username" in message
        or "cannot find any entity" in message
        or "username not occupied" in message
    )


async def _resolve_channel_via_any_client(username: str, *, exclude_account_id: Optional[int] = None) -> Optional[dict[str, Any]]:
    from backend.telegram_client import _clients

    normalized_username = username.lstrip("@")
    for account_id, resolver in _clients.items():
        if exclude_account_id is not None and account_id == exclude_account_id:
            continue
        try:
            entity = await resolver.get_entity(normalized_username)
            _record_channel_verification(normalized_username, entity, resolution_method="resolver_client")
            access_hash = getattr(entity, "access_hash", None)
            return {
                "username": normalized_username,
                "verification_status": "verified",
                "entity_type": entity.__class__.__name__,
                "peer_id": str(getattr(entity, "id", "")),
                "access_hash": str(access_hash) if access_hash is not None else None,
                "invite_link": None,
                "resolve_fail_count": 0,
            }
        except Exception:
            continue
    return None


async def _resolve_channel_entity(
    client: TelegramClient,
    candidate: dict[str, Any],
) -> tuple[Any, str]:
    cached_input = _channel_input(candidate)
    username = candidate["username"]

    if cached_input is not None:
        try:
            entity = await client.get_entity(cached_input)
            return entity, "cached_peer"
        except Exception:
            pass

    entity = await client.get_entity(username)
    _record_channel_verification(username, entity, resolution_method="username")
    return entity, "username"


def _handle_action_success(warming_id: int, action: PlannedAction, details: Optional[dict[str, Any]]):
    if action.action_type == "search":
        _clear_action_block(warming_id, "search")
        return

    if action.action_type == "subscribe" and details:
        if details.get("resolution_method") == "username":
            _clear_action_block(warming_id, "subscribe_username_resolve")


def _handle_action_failure(warming_id: int, action: PlannedAction, exc: Exception):
    if action.action_type == "search" and _is_frozen_search_error(exc):
        _block_action(
            warming_id,
            "search",
            reason="FROZEN_METHOD_INVALID",
            cooldown=timedelta(hours=48),
            details={"error": str(exc)},
        )
        return

    if action.action_type != "subscribe":
        return

    if _is_username_resolve_error(exc):
        if action.target:
            _record_channel_resolve_failure(action.target, str(exc))
        _block_action(
            warming_id,
            "subscribe_username_resolve",
            reason="username_resolve_failed",
            cooldown=timedelta(hours=24),
            details={"target": action.target, "error": str(exc)},
        )


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
        logger.info("Warming worker %s started", self.warming_id)
        _touch_warming(self.warming_id, last_decision="worker_started", next_action_at=datetime.utcnow())

        try:
            initial_delay = await self._run_iteration(force=True)
            if initial_delay > 0:
                await asyncio.sleep(initial_delay)

            while not self._stop.is_set():
                delay = await self._run_iteration(force=False)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.info("Warming worker %s cancelled", self.warming_id)
        except Exception as exc:
            logger.error("Warming worker %s crashed: %s", self.warming_id, exc, exc_info=True)
            _touch_warming(
                self.warming_id,
                last_decision="worker_crashed",
                last_error_at=datetime.utcnow(),
                last_error_message=str(exc),
                next_action_at=None,
            )
        finally:
            _workers.pop(self.warming_id, None)

    async def _run_iteration(self, *, force: bool) -> float:
        warming = _get_warming(self.warming_id)
        if not warming:
            return 60.0
        if warming.status in {"paused", "completed"}:
            next_run = datetime.utcnow() + timedelta(seconds=60)
            _touch_warming(self.warming_id, last_decision=f"waiting_for_{warming.status}", next_action_at=next_run)
            return 60.0

        _advance_phase(self.warming_id)
        _update_health(self.warming_id)

        if not force and not _should_act_now():
            delay = gaussian_delay(1200, 240, 300)
            next_run = datetime.utcnow() + timedelta(seconds=delay)
            logger.info("Warming %s: burst_skipped_time_window", self.warming_id)
            _touch_warming(self.warming_id, last_decision="burst_skipped_time_window", next_action_at=next_run)
            return delay

        outcome = await self._execute_burst()
        if outcome == "burst_skipped_no_client":
            delay = 180.0
        elif outcome == "burst_skipped_no_actions":
            delay = 900.0
        else:
            delay = gaussian_delay(2400, 720, 600)

        _update_health(self.warming_id)
        _touch_warming(self.warming_id, next_action_at=datetime.utcnow() + timedelta(seconds=delay))
        return delay

    async def _execute_burst(self) -> str:
        from backend.telegram_client import _clients

        account_id = _get_warming_account_id(self.warming_id)
        if not account_id:
            logger.info("Warming %s: burst_skipped_no_account", self.warming_id)
            _touch_warming(self.warming_id, last_decision="burst_skipped_no_account")
            return "burst_skipped_no_actions"

        client = _clients.get(account_id)
        if not client:
            logger.info("Warming %s: burst_skipped_no_client", self.warming_id)
            _touch_warming(self.warming_id, last_decision="waiting_for_runtime")
            return "burst_skipped_no_client"

        config = _get_phase_config(self.warming_id)
        actions, skipped = self._build_action_list(client, config)
        for skipped_action in skipped:
            _record_skipped_action(
                self.warming_id,
                skipped_action["action_type"],
                target=skipped_action.get("target"),
                reason=skipped_action["reason"],
                decision_context=skipped_action.get("decision_context"),
            )

        if not actions:
            logger.info("Warming %s: burst_skipped_no_actions", self.warming_id)
            _touch_warming(self.warming_id, last_decision="burst_skipped_no_actions")
            return "burst_skipped_no_actions"

        logger.info("Warming %s: burst_started (%s planned)", self.warming_id, len(actions))
        _touch_warming(self.warming_id, last_decision="burst_started")

        random.shuffle(actions)
        burst_size = random.randint(1, min(4, len(actions)))
        executed = 0

        for action in actions[:burst_size]:
            if self._stop.is_set():
                break
            try:
                result = await self._execute_action(action)
                executed += 1
                if result == "flood_wait":
                    break
                await asyncio.sleep(gaussian_delay(35, 18, 8))
            except FloodWaitError as exc:
                wait_seconds = exc.seconds + int(gaussian_delay(30, 10, 10))
                logger.warning("Warming %s: FloodWait %ss", self.warming_id, exc.seconds)
                _touch_warming(
                    self.warming_id,
                    last_decision="burst_paused_flood_wait",
                    last_error_at=datetime.utcnow(),
                    last_error_message=f"FloodWaitError: {exc.seconds}s",
                    next_action_at=datetime.utcnow() + timedelta(seconds=wait_seconds),
                )
                await asyncio.sleep(wait_seconds)
                break
            except PeerFloodError:
                logger.warning("Warming %s: PeerFlood pause 2h", self.warming_id)
                _touch_warming(
                    self.warming_id,
                    last_decision="burst_paused_peer_flood",
                    last_error_at=datetime.utcnow(),
                    last_error_message="PeerFloodError",
                    next_action_at=datetime.utcnow() + timedelta(seconds=7200),
                )
                await asyncio.sleep(7200)
                break

        logger.info("Warming %s: burst_completed (%s executed)", self.warming_id, executed)
        _touch_warming(self.warming_id, last_decision="burst_completed")
        return "burst_completed"

    async def _execute_action(self, action: PlannedAction) -> str:
        action_id = _begin_action(self.warming_id, action.action_type, action.target, action.decision_context)

        try:
            details = await action.runner()
            _handle_action_success(self.warming_id, action, details)
            _finish_action(action_id, "success", details=details)
            return "success"
        except ActionSkip as exc:
            _finish_action(
                action_id,
                "skipped",
                details={"reason": exc.reason, **exc.details},
                error_message=exc.reason,
            )
            return "skipped"
        except FloodWaitError as exc:
            _finish_action(
                action_id,
                "flood_wait",
                details={"exception": "FloodWaitError", "seconds": exc.seconds},
                error_message=f"FloodWaitError: {exc.seconds}s",
                flood_wait_seconds=exc.seconds,
            )
            raise
        except PeerFloodError:
            _finish_action(
                action_id,
                "flood_wait",
                details={"exception": "PeerFloodError"},
                error_message="PeerFloodError",
            )
            raise
        except Exception as exc:
            logger.exception(
                "Warming %s action failed",
                self.warming_id,
                extra={"action_type": action.action_type, "target": action.target},
            )
            _handle_action_failure(self.warming_id, action, exc)
            _finish_action(
                action_id,
                "failed",
                details={"exception": exc.__class__.__name__},
                error_message=str(exc),
            )
            return "failed"

    def _build_action_list(
        self,
        client: TelegramClient,
        config: dict[str, Any],
    ) -> tuple[list[PlannedAction], list[dict[str, Any]]]:
        state = _get_warming_state(self.warming_id)
        if not state:
            return [], []

        actions: list[PlannedAction] = []
        skipped: list[dict[str, Any]] = []
        blocked_actions = state.get("blocked_actions", {})

        def remaining(config_key: str, counter_key: str) -> int:
            return max(0, int(config.get(config_key, 0) or 0) - int(state.get(counter_key, 0) or 0))

        online_left = remaining("online_sessions_per_day", "online_sessions_today")
        if online_left > 0:
            actions.append(
                PlannedAction(
                    action_type="online_session",
                    target="self",
                    runner=lambda: _online_session(client),
                    decision_context={"quota_remaining": online_left, "phase": state["phase"]},
                )
            )

        mutual_left = remaining("mutual_messages_per_day", "mutual_messages_today")
        if mutual_left > 0:
            if state.get("peer_account_ids"):
                peers = _get_peer_clients(self.warming_id)
            else:
                peers = []
            if peers:
                peer_account_id, _ = random.choice(peers)
                peer_phone = _get_account_phone(peer_account_id) or str(peer_account_id)
                actions.append(
                    PlannedAction(
                        action_type="msg_sent",
                        target=peer_phone,
                        runner=lambda pid=peer_account_id: _mutual_message(self.warming_id, pid),
                        decision_context={"quota_remaining": mutual_left, "peer_account_id": peer_account_id},
                    )
                )

        subscriptions_left = remaining("subscriptions_per_day", "subscriptions_today")
        if subscriptions_left > 0:
            resolve_block = _get_active_block(blocked_actions, "subscribe_username_resolve")
            channels = _pick_channels(
                self.warming_id,
                min(1, subscriptions_left),
                verified_only=resolve_block is not None,
            )
            if channels:
                for channel in channels:
                    actions.append(
                        PlannedAction(
                            action_type="subscribe",
                            target=channel["username"],
                            runner=lambda ch=channel: _subscribe_channel(client, self.warming_id, ch),
                            decision_context={
                                "quota_remaining": subscriptions_left,
                                "phase": state["phase"],
                                "verification_status": channel.get("verification_status"),
                            },
                        )
                    )
            else:
                skipped.append(
                    {
                        "action_type": "subscribe",
                        "target": None,
                        "reason": "no_verified_channels_available" if resolve_block else "no_available_channels",
                        "decision_context": {
                            "quota_remaining": subscriptions_left,
                            "phase": state["phase"],
                            "blocked": resolve_block,
                        },
                    }
                )

        reactions_left = remaining("reactions_per_day", "reactions_today")
        if reactions_left > 0:
            subscribed = state["subscribed_channels"]
            if subscribed:
                channel = random.choice(subscribed)
                actions.append(
                    PlannedAction(
                        action_type="react",
                        target=channel,
                        runner=lambda ch=channel: _react_to_post(
                            client,
                            _get_channel_candidate_by_username(ch) or {"username": ch},
                        ),
                        decision_context={"quota_remaining": reactions_left, "phase": state["phase"]},
                    )
                )
            else:
                skipped.append(
                    {
                        "action_type": "react",
                        "target": None,
                        "reason": "no_subscribed_channels",
                        "decision_context": {"quota_remaining": reactions_left, "phase": state["phase"]},
                    }
                )

        searches_left = remaining("searches_per_day", "searches_today")
        search_block = _get_active_block(blocked_actions, "search")
        if searches_left > 0 and search_block is None:
            query = random.choice(_SEARCH_QUERIES)
            actions.append(
                PlannedAction(
                    action_type="search",
                    target=query,
                    runner=lambda q=query: _search(client, q),
                    decision_context={"quota_remaining": searches_left, "phase": state["phase"]},
                )
            )

        dialog_left = remaining("dialog_reads_per_day", "dialog_reads_today")
        if dialog_left > 0:
            actions.append(
                PlannedAction(
                    action_type="read_dialog",
                    target="dialogs",
                    runner=lambda: _read_dialogs(client),
                    decision_context={"quota_remaining": dialog_left, "phase": state["phase"]},
                )
            )

        return actions, skipped


async def start_all_warming_tasks():
    db = SessionLocal()
    try:
        warmings = (
            db.query(AccountWarming)
            .filter(AccountWarming.status.in_(["warming", "maintenance"]))
            .all()
        )
        ids = [warming.id for warming in warmings]
    finally:
        db.close()

    for warming_id in ids:
        if warming_id in _workers:
            continue
        worker = WarmingWorker(warming_id)
        worker.start()
        logger.info("Resumed warming task %s", warming_id)


def restart_warming_for_account(account_id: int):
    db = SessionLocal()
    try:
        warming = (
            db.query(AccountWarming)
            .filter(
                AccountWarming.account_id == account_id,
                AccountWarming.status.in_(["warming", "maintenance"]),
            )
            .first()
        )
        if warming and warming.id not in _workers:
            worker = WarmingWorker(warming.id)
            worker.start()
            logger.info("Restarted warming %s after account %s reconnect", warming.id, account_id)
    finally:
        db.close()
