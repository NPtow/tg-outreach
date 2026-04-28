from typing import Iterable, Optional

from sqlalchemy.orm import Session

from backend.models import Message, ScenarioCard
from backend.scenarios import active_scenarios_for_text, serialize_scenario


def generate_structured_reply(
    db: Optional[Session],
    *,
    history: list,
    model: str = "local-heuristic-agent",
    candidate_prompt: str = "",
) -> dict:
    latest_text = _latest_user_text(history)
    action = _infer_action(latest_text)
    scenarios: list[ScenarioCard] = active_scenarios_for_text(db, latest_text) if db is not None else []
    reply_text = _reply_for_action(action, latest_text, candidate_prompt, scenarios)
    return {
        "reply_text": reply_text,
        "action": action,
        "confidence": 0.82 if action != "send_reply" else 0.7,
        "model": model,
        "scenario_ids_used": [card.id for card in scenarios],
        "selected_scenarios": [serialize_scenario(card) for card in scenarios],
    }


def guardrail_check(reply: dict, *, scheduled_meeting_exists: bool = False) -> dict:
    text = reply.get("reply_text") or ""
    issues = []
    if "[[" in text or "]]" in text:
        issues.append("technical_marker")
    if len(text) > 1200:
        issues.append("too_long")
    if "zoom.us/" in text.lower() and not scheduled_meeting_exists:
        issues.append("fake_zoom_link")
    return {
        "safe_to_send": not issues,
        "issues": issues,
        "rewritten_reply": None if not issues else text.replace("[[BOOK_MEETING]]", "").strip(),
    }


def _latest_user_text(history: list) -> str:
    for item in reversed(history):
        role = getattr(item, "role", None) if not isinstance(item, dict) else item.get("role")
        text = getattr(item, "text", None) if not isinstance(item, dict) else item.get("text", "")
        if role == "user":
            return text or ""
    return ""


def _infer_action(text: str) -> str:
    lower = (text or "").lower()
    if any(token in lower for token in ["стоп", "не пишите", "отпиш", "unsubscribe"]):
        return "do_not_contact"
    if any(token in lower for token in ["созвон", "встреч", "календар", "zoom", "зум", "call", "meeting"]):
        return "book_meeting"
    return "send_reply"


def _reply_for_action(action: str, latest_text: str, candidate_prompt: str, scenarios: list[ScenarioCard] | None = None) -> str:
    if action == "book_meeting":
        return "Отлично, давайте созвонимся. Сейчас подберу ближайшее свободное время и пришлю ссылку."
    if action == "do_not_contact":
        return "Понял, больше не буду писать."
    scenario_reply = _reply_from_scenarios(scenarios or [])
    if scenario_reply:
        return scenario_reply
    if "длит" in (latest_text or "").lower():
        return "Обычно интервью занимает 20-30 минут. Это исследовательский разговор, не продажа."
    return "Расскажу коротко: я провожу исследовательские интервью про процессы найма и хочу понять ваш практический опыт."


def messages_to_history(messages: Iterable[Message]) -> list[dict]:
    return [{"role": msg.role, "text": msg.text, "created_at": msg.created_at} for msg in messages]


def _reply_from_scenarios(scenarios: list[ScenarioCard]) -> str | None:
    for card in scenarios:
        group = _tag_value(card.tags or "", "group")
        if group in {"faq", "closing", "fallback"} and card.recommended_reply:
            return card.recommended_reply
    return None


def _tag_value(tags: str, key: str) -> str | None:
    prefix = f"{key}:"
    for tag in (tags or "").split(","):
        tag = tag.strip()
        if tag.startswith(prefix):
            return tag[len(prefix):]
    return None
