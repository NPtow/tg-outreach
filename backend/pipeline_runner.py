from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from backend.agent_policy import validate_agent_decision
from backend.agent_runtime import record_agent_run
from backend.dify_retriever import retrieve_dify_knowledge_cards
from backend.meeting_scheduler import build_meeting_reply_text, get_existing_scheduled_meeting
from backend.models import Account, AgentPipeline, Campaign, Conversation, Message
from backend.n8n_agent import N8nAgentRequest, call_n8n_agent
from backend.scenarios import active_scenarios_for_text

_URL_RE = re.compile(r"https?://\S+")
_MEETING_WORD_RE = re.compile(r"(встреч|созвон|звон|zoom|зум|календар|ссылк)", re.IGNORECASE)
_MEETING_STATUS_RE = re.compile(
    r"(что там|где|когда|назнач|постав|получ|подтверд|верно|актуальн|скин|пришл)",
    re.IGNORECASE,
)
_SLOT_HINT_RE = re.compile(
    r"(\b\d{1,2}[:.]\d{2}\b|\b\d{1,2}\s*(час|ч)\b|сегодня|завтра|послезавтра|понедельник|вторник|сред|четверг|пятниц|суббот|воскрес)",
    re.IGNORECASE,
)


def resolve_agent_pipeline(
    db: Session,
    *,
    account: Optional[Account],
    campaign: Optional[Campaign],
) -> Optional[AgentPipeline]:
    pipeline_id = None
    if account and getattr(account, "agent_pipeline_id", None):
        pipeline_id = account.agent_pipeline_id
    elif campaign and getattr(campaign, "agent_pipeline_id", None):
        pipeline_id = campaign.agent_pipeline_id
    if not pipeline_id:
        return None
    pipeline = db.query(AgentPipeline).filter(AgentPipeline.id == pipeline_id).first()
    if not pipeline or pipeline.status != "active":
        return None
    return pipeline


async def run_pipeline_for_auto_reply(
    db: Session,
    *,
    pipeline: AgentPipeline,
    conversation: Conversation,
    messages: Iterable[Message],
    trigger_message_id: int,
) -> dict:
    return await _run_pipeline(
        db,
        pipeline=pipeline,
        conversation=conversation,
        messages=messages,
        event_id=f"auto-reply:{conversation.id}:{trigger_message_id}",
        mode="live",
        dry_run_tools=False,
        run_type="auto_reply_pipeline",
    )


async def replay_pipeline_for_conversation(
    db: Session,
    *,
    pipeline: AgentPipeline,
    conversation: Conversation,
    messages: Iterable[Message],
    dry_run_tools: bool = True,
) -> dict:
    return await _run_pipeline(
        db,
        pipeline=pipeline,
        conversation=conversation,
        messages=messages,
        event_id=f"pipeline-replay:{pipeline.id}:{conversation.id}",
        mode="sandbox",
        dry_run_tools=dry_run_tools,
        run_type="pipeline_replay",
    )


async def smoke_pipeline_for_conversation(
    db: Session,
    *,
    pipeline: AgentPipeline,
    conversation: Conversation,
    messages: Iterable[Message],
    dry_run_tools: bool = True,
) -> dict:
    return await _run_pipeline(
        db,
        pipeline=pipeline,
        conversation=conversation,
        messages=messages,
        event_id=f"pipeline-smoke:{pipeline.id}:{conversation.id}",
        mode="sandbox",
        dry_run_tools=dry_run_tools,
        run_type="pipeline_smoke_auto_reply",
    )


async def _run_pipeline(
    db: Session,
    *,
    pipeline: AgentPipeline,
    conversation: Conversation,
    messages: Iterable[Message],
    event_id: str,
    mode: str,
    dry_run_tools: bool,
    run_type: str,
) -> dict:
    if pipeline.type == "legacy_prompt":
        result = {
            "ok": False,
            "engine": "legacy_prompt",
            "error": "legacy_prompt pipelines use the old prompt fallback and are not executable through PipelineRunner",
        }
        record_agent_run(
            db,
            conversation_id=conversation.id,
            run_type=run_type,
            model="legacy_prompt",
            input_payload={"pipeline_id": pipeline.id, "event_id": event_id},
            output_payload=result,
            status="blocked",
            error=result["error"],
        )
        return result
    if pipeline.type != "n8n_webhook":
        result = {"ok": False, "engine": pipeline.type, "error": f"Unsupported pipeline type: {pipeline.type}"}
        record_agent_run(
            db,
            conversation_id=conversation.id,
            run_type=run_type,
            model=pipeline.type,
            input_payload={"pipeline_id": pipeline.id, "event_id": event_id},
            output_payload=result,
            status="blocked",
            error=result["error"],
        )
        return result

    config = _pipeline_config(pipeline)
    config_mode = (config.get("mode") or "sandbox").strip()
    if mode == "live" and config_mode != "live":
        result = {
            "ok": False,
            "engine": "n8n_webhook",
            "pipeline_id": pipeline.id,
            "pipeline_name": pipeline.name,
            "event_id": event_id,
            "mode": config_mode,
            "error": f"Pipeline mode is {config_mode}; set it to live before using it for auto-reply",
        }
        record_agent_run(
            db,
            conversation_id=conversation.id,
            run_type=run_type,
            model="n8n_webhook",
            input_payload={"pipeline_id": pipeline.id, "event_id": event_id, "mode": mode},
            output_payload=result,
            status="blocked",
            error=result["error"],
        )
        return result
    message_payloads = [_message_payload(message) for message in messages]
    conversation_state = build_conversation_state(db, conversation, message_payloads)
    guarded_reply = _reply_from_conversation_state_guard(conversation_state)
    if guarded_reply:
        decision = {
            "approved": True,
            "stage": "scheduling",
            "intent": "availability_offer",
            "reply_text": guarded_reply,
            "ops_action": "none",
            "booking": conversation_state.get("scheduled_meeting") or {},
            "reason": "existing_meeting_status_guard",
        }
        policy = validate_agent_decision(decision, booking_record_exists=True, recent_messages=message_payloads)
        result = {
            "ok": bool(policy["safe_to_send"]),
            "engine": "conversation_state_guard",
            "pipeline_id": pipeline.id,
            "pipeline_name": pipeline.name,
            "event_id": event_id,
            "mode": mode,
            "conversation_state": conversation_state,
            "decision": decision,
            "policy": policy,
            "reply_text": policy.get("final_reply_text"),
            "would_send": bool(not dry_run_tools and policy["safe_to_send"]),
        }
        record_agent_run(
            db,
            conversation_id=conversation.id,
            run_type=run_type,
            model="conversation_state_guard",
            input_payload={
                "pipeline_id": pipeline.id,
                "event_id": event_id,
                "mode": mode,
                "messages": message_payloads,
                "conversation_state": conversation_state,
            },
            output_payload=result,
            status="succeeded" if result["ok"] else "blocked",
            error=None,
        )
        return result

    scenario_cards = _scenario_payloads(db, message_payloads, project_id=conversation.project_id)
    knowledge = await retrieve_dify_knowledge_cards(
        _dify_retrieval_query(message_payloads),
        top_k=int(config.get("dify_top_k") or 5),
    )
    knowledge_cards = knowledge.get("cards") or []
    request = N8nAgentRequest(
        event_id=event_id,
        mode=config_mode if mode == "live" else mode,
        conversation=_conversation_payload(conversation),
        messages=message_payloads,
        conversation_state=conversation_state,
        scenario_cards=scenario_cards,
        knowledge_cards=knowledge_cards,
        settings={
            "timezone": config.get("timezone") or "Europe/Moscow",
            "meeting_window": config.get("meeting_window") or "16:00-22:00",
            "duration_minutes": int(config.get("duration_minutes") or 30),
            "dry_run_tools": dry_run_tools,
            "pipeline_id": pipeline.id,
            "pipeline_name": pipeline.name,
            "knowledge": {
                "source": "dify" if knowledge_cards else "local_scenario_cards",
                "query": knowledge.get("query") or "",
                "cards_count": len(knowledge_cards),
                "fallback_cards_count": len(scenario_cards),
                "error": knowledge.get("error"),
                "configured": bool(knowledge.get("configured")),
            },
        },
        constraints={
            "do_not_send_links": True,
            "do_not_claim_booking_without_record": True,
            "do_not_promise_reminder_without_task": True,
        },
    )
    call_result = await call_n8n_agent(
        request,
        webhook_url=config.get("webhook_url") or config.get("production_webhook_url") or "",
        shared_secret=config.get("shared_secret") or "",
        timeout_s=float(config.get("timeout_s") or 20),
    )
    decision = call_result.decision.model_dump(mode="json") if call_result.decision else None
    booking_payload = (decision or {}).get("booking") or {}
    booking_record_exists = bool(
        booking_payload.get("calendar_event_id")
        or booking_payload.get("external_booking_id")
        or booking_payload.get("calendar_add_url")
    )
    policy = (
        validate_agent_decision(
            decision,
            booking_record_exists=booking_record_exists,
            reminder_task_created=False,
            recent_messages=message_payloads,
        )
        if decision
        else {"safe_to_send": False, "issues": ["n8n_call_failed"], "final_reply_text": None}
    )
    result = {
        "ok": bool(call_result.ok and policy["safe_to_send"]),
        "engine": "n8n_webhook",
        "pipeline_id": pipeline.id,
        "pipeline_name": pipeline.name,
        "event_id": event_id,
        "mode": mode,
        "n8n": call_result.model_dump(mode="json"),
        "decision": decision,
        "policy": policy,
        "reply_text": policy.get("final_reply_text"),
        "would_send": bool(not dry_run_tools and call_result.ok and policy["safe_to_send"]),
    }
    record_agent_run(
        db,
        conversation_id=conversation.id,
        run_type=run_type,
        model="n8n_webhook",
        input_payload=request.model_dump(mode="json"),
        output_payload=result,
        status="succeeded" if result["ok"] else "blocked",
        error=call_result.error,
    )
    return result


def _pipeline_config(pipeline: AgentPipeline) -> dict:
    try:
        return json.loads(pipeline.config_json or "{}")
    except Exception:
        return {}


def _conversation_payload(conversation: Conversation) -> dict:
    return {
        "id": conversation.id,
        "project_id": conversation.project_id,
        "account_id": conversation.account_id,
        "tg_user_id": conversation.tg_user_id,
        "tg_username": conversation.tg_username,
        "tg_first_name": conversation.tg_first_name,
        "tg_last_name": conversation.tg_last_name,
        "status": conversation.status,
        "source_campaign_id": conversation.source_campaign_id,
        "is_hot": bool(conversation.is_hot),
        "created_at": conversation.created_at.isoformat() if conversation.created_at else None,
        "last_message_at": conversation.last_message_at.isoformat() if conversation.last_message_at else None,
    }


def _message_payload(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "text": message.text,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def _dify_retrieval_query(messages: list[dict], max_messages: int = 6) -> str:
    latest_user_text = ""
    previous_context = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            latest_user_text = _compact_retrieval_text(message.get("text") or "", limit=700)
            break
    for message in reversed(messages[-max_messages:]):
        text = _compact_retrieval_text(message.get("text") or "", limit=120)
        if text and text != latest_user_text:
            previous_context = text
            break
    pieces = [
        "Последнее сообщение пользователя:",
        latest_user_text[:140],
    ]
    if previous_context:
        pieces.extend(["Контекст:", previous_context[:80]])
    query = "\n".join(
        piece for piece in pieces if piece
    ).strip()
    return query[:250]


def _verbose_dify_retrieval_query(messages: list[dict], max_messages: int = 6) -> str:
    history = []
    for message in messages[-max_messages:]:
        role = message.get("role") or "unknown"
        text = _compact_retrieval_text(message.get("text") or "", limit=350)
        if text:
            history.append(f"{role}: {text}")
    return "\n".join(
        [
            "Последнее сообщение пользователя:",
            _compact_retrieval_text(next((m.get("text") or "" for m in reversed(messages) if m.get("role") == "user"), ""), limit=1000),
            "",
            "Краткий контекст последних сообщений:",
            "\n".join(history),
        ]
    ).strip()


def _compact_retrieval_text(text: str, *, limit: int) -> str:
    compact = _URL_RE.sub("[link]", text or "")
    compact = " ".join(compact.split())
    return compact[:limit]


def build_conversation_state(db: Session, conversation: Conversation, messages: list[dict]) -> dict:
    latest_user_messages = _latest_user_messages_after_last_assistant(messages)
    latest_user_text = "\n".join(item.get("text") or "" for item in latest_user_messages).strip()
    scheduled_meeting = get_existing_scheduled_meeting(db, conversation.id)
    serialized_meeting = _serialize_meeting_for_state(scheduled_meeting) if scheduled_meeting else None
    if serialized_meeting:
        meeting_state = "scheduled"
    elif _SLOT_HINT_RE.search(latest_user_text):
        meeting_state = "slot_requested"
    else:
        meeting_state = "none"

    return {
        "qualification_state": "qualified" if meeting_state in {"slot_requested", "scheduled"} else "unknown",
        "meeting_state": meeting_state,
        "scheduled_meeting": serialized_meeting,
        "latest_user_messages": latest_user_messages,
        "latest_user_text": latest_user_text,
        "latest_user_message_count": len(latest_user_messages),
    }


def _latest_user_messages_after_last_assistant(messages: list[dict]) -> list[dict]:
    latest: list[dict] = []
    for message in reversed(messages):
        role = (message.get("role") or "").strip()
        if role == "assistant":
            break
        if role == "user":
            latest.append(message)
    return list(reversed(latest))


def _reply_from_conversation_state_guard(conversation_state: dict) -> str:
    if conversation_state.get("meeting_state") != "scheduled":
        return ""
    latest_text = conversation_state.get("latest_user_text") or ""
    if not (_MEETING_WORD_RE.search(latest_text) and _MEETING_STATUS_RE.search(latest_text)):
        return ""
    meeting = conversation_state.get("scheduled_meeting") or {}
    return meeting.get("status_reply") or meeting.get("reply_text") or ""


def _serialize_meeting_for_state(meeting) -> dict:
    reply_text = build_meeting_reply_text(
        meeting.scheduled_start,
        meeting.scheduled_end,
        meeting.zoom_join_url,
        meeting.calendar_html_link,
        meeting.calendar_add_url,
    )
    return {
        "id": meeting.id,
        "status": meeting.status,
        "start_at": _iso_or_none(meeting.scheduled_start),
        "end_at": _iso_or_none(meeting.scheduled_end),
        "timezone": meeting.timezone,
        "calendar_event_id": meeting.calendar_event_id,
        "calendar_html_link": meeting.calendar_html_link,
        "calendar_add_url": meeting.calendar_add_url,
        "zoom_meeting_id": meeting.zoom_meeting_id,
        "zoom_join_url": meeting.zoom_join_url,
        "reply_text": reply_text,
        "status_reply": _meeting_status_reply_text(meeting),
    }


def _meeting_status_reply_text(meeting) -> str:
    slot = ""
    if isinstance(meeting.scheduled_start, datetime) and isinstance(meeting.scheduled_end, datetime):
        slot = build_meeting_reply_text(meeting.scheduled_start, meeting.scheduled_end, None)
        slot = (
            slot.replace("Забронировал встречу на ", "")
            .replace("Поставил встречу на ", "")
            .rstrip(".")
        )
    parts = [f"Встреча уже назначена на {slot}." if slot else "Встреча уже назначена."]
    if meeting.zoom_join_url:
        parts.append(f"Ссылка Zoom: {meeting.zoom_join_url}")
    elif meeting.calendar_add_url:
        parts.append(f"Ссылка для добавления в календарь: {meeting.calendar_add_url}")
    elif meeting.calendar_html_link:
        parts.append(f"Ссылка на событие в календаре: {meeting.calendar_html_link}")
    return " ".join(parts).strip()


def _iso_or_none(value) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _scenario_payloads(db: Session, messages: list[dict], limit: int = 5, project_id: int | None = None) -> list[dict]:
    latest_user_text = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            latest_user_text = message.get("text") or ""
            break
    cards = active_scenarios_for_text(db, latest_user_text, limit=limit, project_id=project_id)
    return [
        {
            "id": card.id,
            "title": card.title,
            "intent": card.intent,
            "trigger_summary": card.trigger_summary,
            "recommended_reply": card.recommended_reply,
            "avoid_reply": card.avoid_reply or "",
            "tags": card.tags or "",
        }
        for card in cards
    ]
