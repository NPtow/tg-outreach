from __future__ import annotations

import json
import re
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from backend.agent_policy import validate_agent_decision
from backend.agent_runtime import record_agent_run
from backend.dify_retriever import retrieve_dify_knowledge_cards
from backend.models import Account, AgentPipeline, Campaign, Conversation, Message
from backend.n8n_agent import N8nAgentRequest, call_n8n_agent
from backend.scenarios import active_scenarios_for_text

_URL_RE = re.compile(r"https?://\S+")


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
