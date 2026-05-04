from __future__ import annotations

import os
import time
from typing import Any, Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError


N8nMode = Literal["off", "sandbox", "shadow", "live"]
Stage = Literal["qualification", "scheduling", "defer", "closing", "referral", "async"]
Intent = Literal[
    "trust_question",
    "availability_offer",
    "ask_followup_later",
    "hard_decline",
    "async_offer",
    "ops_problem",
    "other",
]
OpsAction = Literal["none", "set_reminder", "request_email", "create_booking", "human_review", "close_thread"]


class ReminderPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    due_at: Optional[str] = None
    reason: str = ""


class BookingPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    start_at: Optional[str] = None
    duration_minutes: int = 30
    attendee_email: Optional[str] = None


class N8nAgentDecision(BaseModel):
    model_config = ConfigDict(extra="allow")

    approved: bool = False
    stage: Stage = "qualification"
    intent: Intent = "other"
    reply_text: str = ""
    ops_action: OpsAction = "none"
    reminder: ReminderPayload = Field(default_factory=ReminderPayload)
    booking: BookingPayload = Field(default_factory=BookingPayload)
    risk_flags: list[str] = Field(default_factory=list)
    reason: str = ""


class N8nAgentRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str
    mode: N8nMode = "sandbox"
    conversation: dict[str, Any]
    messages: list[dict[str, Any]]
    scenario_cards: list[dict[str, Any]] = Field(default_factory=list)
    knowledge_cards: list[dict[str, Any]] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
    constraints: dict[str, Any] = Field(default_factory=dict)


class N8nAgentCallResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool
    decision: Optional[N8nAgentDecision] = None
    raw_response: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    duration_ms: int = 0


def _first_non_empty_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_n8n_decision_payload(raw: Any) -> Any:
    """Accept small n8n output wrappers while keeping explicit decisions intact."""

    if isinstance(raw, list) and len(raw) == 1:
        return _normalize_n8n_decision_payload(raw[0])
    if not isinstance(raw, dict):
        return raw

    for wrapper_key in ("decision", "output", "response", "result", "data"):
        nested = raw.get(wrapper_key)
        if isinstance(nested, dict):
            return _normalize_n8n_decision_payload(nested)

    draft = raw.get("draft") if isinstance(raw.get("draft"), dict) else None
    if not draft:
        return raw

    reply_text = _first_non_empty_text(
        draft.get("reply_text"),
        draft.get("body"),
        draft.get("text"),
        raw.get("reply_text"),
        raw.get("body"),
        raw.get("text"),
    )
    if not reply_text:
        return raw

    return {
        **raw,
        "approved": raw["approved"] if "approved" in raw else draft.get("approved", True),
        "stage": raw.get("stage") or draft.get("stage") or "qualification",
        "intent": raw.get("intent") or draft.get("intent") or "other",
        "reply_text": reply_text,
        "ops_action": raw.get("ops_action") or draft.get("ops_action") or "none",
        "reminder": raw.get("reminder") or draft.get("reminder") or {},
        "booking": raw.get("booking") or draft.get("booking") or {},
        "risk_flags": raw.get("risk_flags") or draft.get("risk_flags") or [],
        "reason": _first_non_empty_text(raw.get("reason"), draft.get("reason")) or "draft_response",
    }


def n8n_agent_mode() -> N8nMode:
    value = (os.getenv("N8N_AGENT_MODE") or "off").strip().lower()
    if value in {"off", "sandbox", "shadow", "live"}:
        return value  # type: ignore[return-value]
    return "off"


def n8n_agent_webhook_url() -> str:
    return (os.getenv("N8N_AGENT_WEBHOOK_URL") or "").strip()


def n8n_agent_shared_secret() -> str:
    return (os.getenv("N8N_AGENT_SHARED_SECRET") or "").strip()


def _parse_id_set(raw: str) -> set[int]:
    result: set[int] = set()
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError:
            continue
    return result


def n8n_agent_enabled_for(*, account_id: int, campaign_id: Optional[int], mode: Optional[str] = None) -> bool:
    current_mode = (mode or n8n_agent_mode()).strip().lower()
    if current_mode not in {"shadow", "live"}:
        return False
    if not n8n_agent_webhook_url():
        return False

    account_ids = _parse_id_set(os.getenv("N8N_AGENT_ACCOUNT_IDS", ""))
    campaign_ids = _parse_id_set(os.getenv("N8N_AGENT_CAMPAIGN_IDS", ""))
    if not account_ids and not campaign_ids:
        return False
    if account_id in account_ids:
        return True
    return campaign_id is not None and campaign_id in campaign_ids


async def call_n8n_agent(
    request: N8nAgentRequest,
    *,
    webhook_url: Optional[str] = None,
    shared_secret: Optional[str] = None,
    timeout_s: float = 20.0,
) -> N8nAgentCallResult:
    """Call n8n webhook and validate the response into a typed decision."""

    url = (webhook_url if webhook_url is not None else n8n_agent_webhook_url()).strip()
    if not url:
        return N8nAgentCallResult(ok=False, error="N8N_AGENT_WEBHOOK_URL is not configured")

    secret = n8n_agent_shared_secret() if shared_secret is None else shared_secret
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if secret:
        headers["X-N8N-Agent-Secret"] = secret

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(url, json=request.model_dump(mode="json"), headers=headers)
        duration_ms = int((time.monotonic() - started) * 1000)
        response.raise_for_status()
        raw = response.json()
        decision = N8nAgentDecision.model_validate(_normalize_n8n_decision_payload(raw))
        return N8nAgentCallResult(
            ok=True,
            decision=decision,
            raw_response=raw,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
    except ValidationError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return N8nAgentCallResult(ok=False, error=f"Invalid n8n decision schema: {exc}", duration_ms=duration_ms)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        return N8nAgentCallResult(ok=False, error=str(exc), status_code=status_code, duration_ms=duration_ms)
