from __future__ import annotations

import re
from typing import Any


BOOKING_CLAIM_TOKENS = (
    "инвайт отправ",
    "приглашение отправ",
    "отправил приглашение",
    "отправила приглашение",
    "ссылка zoom",
    "ссылка зум",
    "zoom.us/",
    "поставил встреч",
    "поставила встреч",
    "забронировал встреч",
    "зафиксировал встреч",
)

REMINDER_PROMISE_TOKENS = (
    "напомню",
    "пингану",
    "напишу позже",
    "напишу вам позже",
    "напишу в понедельник",
    "напишу во вторник",
    "напишу в среду",
    "напишу в четверг",
    "напишу в пятницу",
)


def validate_agent_decision(
    decision: dict[str, Any],
    *,
    booking_record_exists: bool = False,
    reminder_task_created: bool = False,
    recent_messages: list[dict[str, Any]] | None = None,
) -> dict:
    """Return deterministic safety checks for a proposed n8n agent decision."""

    issues: list[str] = []
    reply_text = (decision.get("reply_text") or "").strip()
    ops_action = (decision.get("ops_action") or "none").strip()

    if not decision.get("approved", False):
        issues.append("decision_not_approved")
    if not reply_text and ops_action not in {"set_reminder", "create_booking", "human_review", "close_thread"}:
        issues.append("empty_reply")
    if "[[" in reply_text or "]]" in reply_text:
        issues.append("technical_marker")

    lower = reply_text.lower()
    if any(token in lower for token in BOOKING_CLAIM_TOKENS) and not booking_record_exists:
        issues.append("booking_claim_without_record")

    reminder = decision.get("reminder") or {}
    has_reminder_payload = bool(reminder.get("due_at") or reminder.get("reason"))
    promises_reminder = any(token in lower for token in REMINDER_PROMISE_TOKENS)
    if promises_reminder and not (ops_action == "set_reminder" and has_reminder_payload and reminder_task_created):
        issues.append("reminder_promise_without_task")

    if ops_action == "set_reminder" and not has_reminder_payload:
        issues.append("set_reminder_without_payload")
    if ops_action == "create_booking" and not (decision.get("booking") or {}).get("start_at"):
        issues.append("create_booking_without_start_at")

    issues.extend(_quality_issues(reply_text, decision=decision, recent_messages=recent_messages or []))

    return {
        "safe_to_send": not issues,
        "issues": issues,
        "final_reply_text": reply_text if not issues else None,
    }


def _quality_issues(reply_text: str, *, decision: dict[str, Any], recent_messages: list[dict[str, Any]]) -> list[str]:
    if not reply_text:
        return []

    issues: list[str] = []
    latest_user = _latest_text(recent_messages, "user").lower()
    lower = reply_text.lower()
    intent = (decision.get("intent") or "other").strip()

    length_text = _text_without_urls(reply_text)
    max_chars = _max_chars_for_intent(intent, latest_user)
    if max_chars and len(length_text) > max_chars:
        issues.append("reply_too_long_for_intent")

    if _is_value_question(latest_user) and _has_meeting_cta(lower):
        issues.append("repeated_meeting_cta")

    last_assistant = _latest_text(recent_messages, "assistant")
    if last_assistant and _token_overlap_ratio(reply_text, last_assistant) >= 0.72:
        issues.append("reply_repeats_previous_answer")

    return issues


def _latest_text(messages: list[dict[str, Any]], role: str) -> str:
    for message in reversed(messages):
        if (message.get("role") or "").strip() == role:
            return (message.get("text") or "").strip()
    return ""


def _max_chars_for_intent(intent: str, latest_user: str) -> int:
    if _is_ambiguous(latest_user):
        return 160
    if _is_value_question(latest_user):
        return 260
    if "что за продукт" in latest_user or "какой продукт" in latest_user:
        return 320
    if intent == "availability_offer":
        return 220
    if intent == "hard_decline":
        return 140
    return 420


def _is_value_question(text: str) -> bool:
    return any(token in text for token in ("что мне будет", "что я получу", "за это получу", "мне за это"))


def _is_ambiguous(text: str) -> bool:
    compact = text.strip(" ?!.").lower()
    return compact in {"и что", "что", "а смысл", "зачем", "почему"}


def _has_meeting_cta(text: str) -> bool:
    return (
        ("20" in text or "30" in text or "минут" in text)
        and any(token in text for token in ("можем", "созвон", "выбрать", "удобн", "поговор"))
    )


def _text_without_urls(text: str) -> str:
    return re.sub(r"https?://\S+", "[link]", text or "")


def _token_overlap_ratio(left: str, right: str) -> float:
    left_tokens = set(_meaningful_tokens(left))
    right_tokens = set(_meaningful_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))


def _meaningful_tokens(text: str) -> list[str]:
    stop = {
        "это",
        "если",
        "вам",
        "для",
        "что",
        "как",
        "про",
        "или",
        "тут",
        "пока",
        "можем",
        "который",
        "которые",
    }
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return [token for token in normalized.split() if len(token) > 3 and token not in stop]
