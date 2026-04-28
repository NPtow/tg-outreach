from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.agent_runtime import record_agent_run
from backend.agent_policy import validate_agent_decision
from backend.conversation_agent import generate_structured_reply, guardrail_check, messages_to_history
from backend.dify_retriever import retrieve_dify_knowledge_cards
from backend.n8n_agent import N8nAgentRequest, call_n8n_agent
from backend.models import Conversation, Message
from backend.pipeline_runner import _dify_retrieval_query
from backend.scenarios import active_scenarios_for_text


def replay_conversation_sandbox(
    db: Session,
    *,
    conversation_id: int,
    candidate_prompt: str = "",
    model: str = "local-heuristic-agent",
    dry_run_tools: bool = True,
) -> dict:
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )
    history = messages_to_history(messages)
    reply = generate_structured_reply(db, history=history, model=model, candidate_prompt=candidate_prompt)
    guardrail = guardrail_check(reply, scheduled_meeting_exists=False)
    would_book_meeting = reply["action"] == "book_meeting"
    tool_result_preview = {
        "mode": "dry_run" if dry_run_tools else "live_disabled_in_sandbox",
        "tool": "schedule_meeting" if would_book_meeting else None,
        "would_create_google_event": bool(would_book_meeting),
        "would_create_zoom_meeting": bool(would_book_meeting),
    }
    result = {
        "conversation_id": conversation_id,
        "history": history,
        "selected_scenarios": reply.pop("selected_scenarios", []),
        "reply": reply,
        "guardrail": guardrail,
        "would_book_meeting": would_book_meeting,
        "tool_result_preview": tool_result_preview,
    }
    record_agent_run(
        db,
        conversation_id=conversation_id,
        run_type="sandbox",
        model=model,
        input_payload={
            "candidate_prompt": candidate_prompt,
            "dry_run_tools": dry_run_tools,
            "history": history,
        },
        output_payload=result,
    )
    return result


async def replay_conversation_n8n_sandbox(
    db: Session,
    *,
    conversation_id: int,
    candidate_prompt: str = "",
    model: str = "n8n-agent",
    dry_run_tools: bool = True,
) -> dict:
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
        .all()
    )
    history = [_json_safe_message(item) for item in messages]
    latest_user_text = ""
    for item in reversed(history):
        if item.get("role") == "user":
            latest_user_text = item.get("text") or ""
            break
    scenario_cards = [
        {
            "id": card.id,
            "title": card.title,
            "intent": card.intent,
            "trigger_summary": card.trigger_summary,
            "recommended_reply": card.recommended_reply,
            "avoid_reply": card.avoid_reply or "",
            "tags": card.tags or "",
        }
        for card in active_scenarios_for_text(db, latest_user_text, limit=5, project_id=conversation.project_id)
    ]
    knowledge = await retrieve_dify_knowledge_cards(_dify_retrieval_query(history), top_k=5)
    knowledge_cards = knowledge.get("cards") or []
    request = N8nAgentRequest(
        event_id=f"sandbox:{conversation_id}",
        mode="sandbox",
        conversation={
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
        },
        messages=history,
        scenario_cards=scenario_cards,
        knowledge_cards=knowledge_cards,
        settings={
            "timezone": "Europe/Moscow",
            "meeting_window": "16:00-22:00",
            "duration_minutes": 30,
            "candidate_prompt": candidate_prompt,
            "dry_run_tools": dry_run_tools,
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
    call_result = await call_n8n_agent(request)
    decision = call_result.decision.model_dump(mode="json") if call_result.decision else None
    policy = (
        validate_agent_decision(
            decision,
            booking_record_exists=bool(((decision or {}).get("booking") or {}).get("calendar_add_url")),
            reminder_task_created=False,
            recent_messages=history,
        )
        if decision
        else {"safe_to_send": False, "issues": ["n8n_call_failed"], "final_reply_text": None}
    )
    result = {
        "conversation_id": conversation_id,
        "engine": "n8n",
        "history": history,
        "n8n": call_result.model_dump(mode="json"),
        "decision": decision,
        "policy": policy,
        "would_send": False,
        "tool_result_preview": {
            "mode": "dry_run" if dry_run_tools else "live_disabled_in_sandbox",
            "ops_action": decision.get("ops_action") if decision else None,
        },
    }
    record_agent_run(
        db,
        conversation_id=conversation_id,
        run_type="sandbox_n8n",
        model=model,
        input_payload=request.model_dump(mode="json"),
        output_payload=result,
        status="succeeded" if call_result.ok and policy["safe_to_send"] else "blocked",
        error=call_result.error,
    )
    return result


def _json_safe_message(message: Message) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "text": message.text,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }
