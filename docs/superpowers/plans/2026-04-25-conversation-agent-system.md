# Conversation Agent System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-ready Telegram conversation agent that improves from real conversations, books meetings through Google Calendar + Zoom, exposes a transparent sandbox, and runs repeatable evals before prompt/model changes reach production.

**Architecture:** Keep deterministic business actions outside the LLM: scheduling, persistence, campaign state, and notifications remain backend services. The LLM becomes a structured decision layer that can select safe actions, reference approved scenarios, and produce a reply. Every agent run is logged, replayable, and evaluable.

**Tech Stack:** FastAPI, SQLAlchemy, Telethon runtime, existing React UI, OpenAI Responses API/function calling first, optional OpenAI Agents SDK for handoffs/tracing after the structured runtime is stable, Google Calendar API, Zoom Server-to-Server OAuth, pytest/local eval harness, optional OpenAI Evals API later.

---

## Current Baseline

Already implemented locally:
- Google OAuth connect/callback and token refresh.
- Google FreeBusy and Calendar event creation.
- Zoom Server-to-Server OAuth meeting creation.
- `ScheduledMeeting` persistence.
- Manual endpoint `POST /api/conversations/{id}/schedule-meeting`.
- Chat UI button `Book meeting` that creates a booking and inserts reply text without auto-sending.
- Auto-reply hidden-marker bridge `[[BOOK_MEETING]]`, with fallback if scheduling fails.
- Tests: `47 OK`; frontend build OK.

Known production work before deploy:
- Add production env vars in Railway.
- Add production Google OAuth redirect URI.
- Re-authorize Google Calendar against the production redirect URI.
- Decide whether production scheduling starts as manual-only or auto-reply booking is enabled immediately.

---

## Agent Roles

### Runtime Agents

1. **Conversation Triage Agent**
   - Reads latest conversation turn and recent history.
   - Outputs structured intent: `answer_question`, `ask_followup`, `book_meeting`, `handoff_to_human`, `do_not_contact`, `not_enough_context`.
   - Does not create final user-facing text.

2. **Reply Agent**
   - Generates the actual Telegram reply.
   - Uses account prompt > campaign prompt > global prompt.
   - Uses approved scenario cards as compact guidance.
   - Must return structured output: `reply_text`, `action`, `confidence`, `scenario_ids_used`.

3. **Scheduler Tool/Agent**
   - Deterministic backend service, not free-form LLM logic.
   - Finds free slot in allowed window, creates Zoom, creates Google Calendar event, saves `ScheduledMeeting`.
   - Idempotent per conversation.

4. **Guardrail Agent**
   - Checks outbound reply before send.
   - Blocks or rewrites if message is too pushy, too long, contains fake links, leaks marker/tool syntax, or books a meeting without a real `ScheduledMeeting`.

5. **Ops Agent**
   - Monitors account auth/proxy/campaign/runtime events.
   - Produces actionable diagnosis: `proxy_bad`, `auth_required`, `peer_flood`, `campaign_worker_stuck`, `calendar_token_expired`.

### Improvement Agents

6. **Scenario Mining Agent**
   - Reads completed/active conversations.
   - Extracts recurring objections, questions, outcomes, and good/bad replies.
   - Proposes scenario cards for human approval.

7. **Scenario Curator Agent**
   - Deduplicates scenario proposals.
   - Merges similar scenarios.
   - Marks scenario as `draft`, `approved`, `archived`, or `active`.

8. **Sandbox Agent**
   - Replays real conversation slices against a candidate prompt/model/scenario set.
   - Shows full input, selected scenarios, tool decisions, generated response, and diffs against production behavior.

9. **Eval Agent**
   - Runs deterministic test cases and rubric-based LLM judging.
   - Produces pass/fail scorecards before prompt/model/scenario changes go live.

---

## Data Model Additions

### Task 1: Agent Run Logging

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/database.py`
- Create: `backend/agent_runtime.py`
- Test: `tests/test_outreach_runtime.py`

- [ ] Add `AgentRun` model:

```python
class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)
    run_type = Column(String(50), nullable=False)  # triage | reply | guardrail | scenario_mining | eval
    model = Column(String(100), nullable=True)
    input_json = Column(Text, nullable=False)
    output_json = Column(Text, nullable=True)
    status = Column(String(30), default="started")  # started | succeeded | failed
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
```

- [ ] Add safe columns/table creation in `init_db()`.

- [ ] Add helper:

```python
def record_agent_run(db, *, conversation_id, run_type, model, input_payload, output_payload=None, status="succeeded", error=None):
    ...
```

- [ ] Test: creating a run stores JSON and never stores raw secrets.

### Task 2: Scenario Database

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/database.py`
- Create: `backend/scenarios.py`
- Create: `backend/routers/scenarios.py`
- Modify: `backend/main.py`
- Test: `tests/test_outreach_runtime.py`
- UI later: `frontend/src/pages/Scenarios.jsx`, `frontend/src/api.js`, `frontend/src/App.jsx`

- [ ] Add `ScenarioCard`:

```python
class ScenarioCard(Base):
    __tablename__ = "scenario_cards"

    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    intent = Column(String(100), nullable=False)
    trigger_summary = Column(Text, nullable=False)
    recommended_reply = Column(Text, nullable=False)
    avoid_reply = Column(Text, nullable=True)
    tags = Column(String(300), nullable=True)
    status = Column(String(30), default="draft")  # draft | approved | active | archived
    source_conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
```

- [ ] Add API:
  - `GET /api/scenarios/`
  - `POST /api/scenarios/`
  - `PATCH /api/scenarios/{id}`
  - `POST /api/scenarios/{id}/activate`
  - `POST /api/scenarios/{id}/archive`

- [ ] Test: active scenarios are returned compactly for prompt injection.

### Task 3: Conversation Scenario Mining

**Files:**
- Create: `backend/scenario_miner.py`
- Modify: `backend/routers/scenarios.py`
- Test: `tests/test_outreach_runtime.py`

- [ ] Add endpoint:
  - `POST /api/scenarios/mine?conversation_id=...`

- [ ] Local first behavior:
  - Load conversation messages.
  - Ask model for structured JSON proposal.
  - Save as `draft`.
  - Do not auto-activate.

- [ ] Structured output:

```json
{
  "title": "Lead asks if this is sales",
  "intent": "not_sales_reassurance",
  "trigger_summary": "Lead worries the interview is actually a sales pitch.",
  "recommended_reply": "Shortly reassure it is research, not a sale...",
  "avoid_reply": "Do not over-explain or push for a meeting immediately.",
  "tags": ["objection", "research_interview"]
}
```

- [ ] Test: mining creates a draft scenario, not an active scenario.

---

## Structured Conversation Runtime

### Task 4: Replace Hidden Marker With Structured Tool Decision

**Files:**
- Modify: `backend/gpt_handler.py`
- Create: `backend/conversation_agent.py`
- Modify: `backend/telegram_client.py`
- Test: `tests/test_outreach_runtime.py`

- [ ] Keep hidden marker only as compatibility fallback.

- [ ] Add `generate_structured_reply(...)` returning:

```python
{
    "reply_text": "Да, давайте. Я сейчас забронирую слот.",
    "action": "book_meeting",
    "confidence": 0.86,
    "scenario_ids_used": [3, 7],
}
```

- [ ] Valid actions:
  - `send_reply`
  - `book_meeting`
  - `handoff_to_human`
  - `mark_done`
  - `do_not_contact`

- [ ] If `action == book_meeting`, call `book_meeting_for_conversation`.

- [ ] Final sent text:
  - Reply text + booking text if booking succeeds.
  - Reply text + fallback if booking fails.

- [ ] Test: action `book_meeting` creates one meeting and sends one clean message.

### Task 5: Scenario Injection Into Reply Agent

**Files:**
- Modify: `backend/conversation_agent.py`
- Modify: `backend/scenarios.py`
- Test: `tests/test_outreach_runtime.py`

- [ ] Retrieve top active scenarios by simple keyword overlap first.
- [ ] Inject maximum 3 compact scenario cards.
- [ ] Log `scenario_ids_used` in `AgentRun`.
- [ ] Do not use vector/RAG yet.

Reasoning: start with deterministic scenario selection. RAG comes only when scenario count grows enough that token budget or quality suffers.

### Task 6: Guardrail Pass

**Files:**
- Create: `backend/guardrails.py`
- Modify: `backend/telegram_client.py`
- Test: `tests/test_outreach_runtime.py`

- [ ] Add cheap deterministic checks:
  - no `[[...]]` markers
  - no empty reply
  - max length
  - no Zoom/calendar fake link unless `ScheduledMeeting` exists

- [ ] Add optional model-based guardrail:

```python
{
  "safe_to_send": true,
  "reason": "short, relevant, no unsupported claims",
  "rewritten_reply": null
}
```

- [ ] If unsafe and no rewrite, pause conversation and emit runtime note.

---

## Sandbox

### Task 7: Sandbox Backend

**Files:**
- Create: `backend/sandbox.py`
- Create: `backend/routers/sandbox.py`
- Modify: `backend/main.py`
- Test: `tests/test_outreach_runtime.py`

- [ ] Add `POST /api/sandbox/replay-conversation`.

- [ ] Request:

```json
{
  "conversation_id": 123,
  "candidate_prompt": "...",
  "model": "gpt-5.4-mini",
  "scenario_ids": [1, 2],
  "dry_run_tools": true
}
```

- [ ] Response:

```json
{
  "triage": {...},
  "selected_scenarios": [...],
  "reply": {...},
  "guardrail": {...},
  "would_book_meeting": true,
  "tool_result_preview": {...}
}
```

- [ ] Tool dry-run must not create Google/Zoom events.

### Task 8: Sandbox UI

**Files:**
- Create: `frontend/src/pages/Sandbox.jsx`
- Modify: `frontend/src/api.js`
- Modify: `frontend/src/App.jsx`

- [ ] Select existing conversation.
- [ ] Choose model/prompt/scenario set.
- [ ] Run replay.
- [ ] Show:
  - input messages
  - selected scenarios
  - proposed reply
  - action/tool decision
  - guardrail result
  - diff against last production reply if present

---

## Eval Harness

### Task 9: Local Eval Dataset From Conversations

**Files:**
- Create: `backend/evals/dataset_builder.py`
- Create: `backend/evals/cases/*.jsonl`
- Test: `tests/test_outreach_runtime.py`

- [ ] Build eval cases from real conversations:

```json
{
  "id": "conv_123_turn_5",
  "history": [...],
  "expected_action": "book_meeting",
  "must_include": ["исследовательское интервью"],
  "must_not_include": ["продажа", "[[BOOK_MEETING]]"],
  "notes": "Lead agreed to call."
}
```

- [ ] Start with 20-50 cases manually reviewed by UI, not hand-written from scratch.

### Task 10: Local Eval Runner

**Files:**
- Create: `backend/evals/runner.py`
- Create: `backend/routers/evals.py`
- Modify: `backend/main.py`
- Test: `tests/test_outreach_runtime.py`

- [ ] Run candidate agent on JSONL cases.
- [ ] Grade deterministic checks:
  - expected action matches
  - banned strings absent
  - required strings present
  - reply length within threshold
  - no booking link without tool result

- [ ] Add optional model-judge grader:

```json
{
  "score": 0.0,
  "reason": "missed booking intent"
}
```

- [ ] Output scorecard:

```json
{
  "passed": 42,
  "failed": 3,
  "score": 0.933,
  "failures": [...]
}
```

### Task 11: OpenAI Evals API Integration Later

Use OpenAI Evals API after local evals are stable and cases are clean.

- [ ] Export local cases to OpenAI eval schema.
- [ ] Use platform graders for rubric checks.
- [ ] Keep local runner as CI/smoke path.

Reasoning: local evals are faster, cheaper, and easier to debug. Hosted evals become useful once the dataset is stable.

---

## Meeting System Productionization

### Task 12: Production Google OAuth

**Files:**
- Modify: `backend/google_calendar.py`
- Modify: `backend/routers/integrations.py`
- Test: `tests/test_outreach_runtime.py`

- [ ] Add production `GOOGLE_REDIRECT_URI`, e.g.:
  - `https://tg-outreach-production.up.railway.app/api/integrations/google/callback`

- [ ] Add status endpoint showing:
  - configured
  - connected
  - token expiry
  - calendar email

- [ ] Never expose tokens in API response.

### Task 13: Booking Preferences

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/database.py`
- Create: `backend/routers/scheduling_settings.py`
- UI later: `frontend/src/pages/Settings.jsx`

- [ ] Add settings:
  - timezone: `Europe/Moscow`
  - booking window: `16:00-22:00`
  - duration: `30`
  - buffer: `15`
  - search horizon: `14 days`
  - notification email

- [ ] Use these settings in `find_next_available_slot`.

### Task 14: Email Notifications

**Files:**
- Create: `backend/email_notifications.py`
- Modify: `backend/meeting_scheduler.py`
- Test: `tests/test_outreach_runtime.py`

- [ ] Use one provider:
  - Recommended first: Resend API key.
  - Alternative: Gmail SMTP app password.

- [ ] Send email after successful booking:
  - lead name/username
  - account
  - campaign
  - slot
  - Zoom link
  - Google Calendar link

---

## Ops And Reliability

### Task 15: Runtime Events For Scheduling And Agents

**Files:**
- Modify: `backend/meeting_scheduler.py`
- Modify: `backend/telegram_client.py`
- Modify: `backend/routers/conversations.py`
- Test: `tests/test_outreach_runtime.py`

- [ ] Emit structured runtime events:
  - `meeting_booking_started`
  - `meeting_booking_succeeded`
  - `meeting_booking_reused`
  - `meeting_booking_failed`
  - `agent_reply_generated`
  - `guardrail_blocked`

- [ ] Show them in frontend later.

### Task 16: Production Safety Toggles

**Files:**
- Modify: `backend/models.py`
- Modify: `backend/database.py`
- Modify: `backend/settings.py` / `backend/routers/settings.py`
- Test: `tests/test_outreach_runtime.py`

- [ ] Add toggles:
  - `auto_reply_enabled`
  - `auto_booking_enabled`
  - `guardrail_enabled`
  - `scenario_mining_enabled`
  - `sandbox_write_tools_enabled`

- [ ] Default production:
  - manual booking enabled
  - auto booking disabled until confirmed
  - guardrail enabled
  - scenario mining draft-only

---

## Suggested Implementation Order

1. Commit current local scheduling MVP after review.
2. Add production env vars and Google production OAuth redirect.
3. Deploy manual booking only.
4. Add `AgentRun` logging.
5. Replace hidden marker with structured reply/action.
6. Add scenario cards and manual scenario UI.
7. Add scenario mining draft generator.
8. Add sandbox backend and UI.
9. Add local eval runner.
10. Add model/rubric graders.
11. Enable auto booking behind a feature flag.
12. Add email notifications.
13. Consider Agents SDK handoffs/tracing after the structured runtime is stable.

---

## What Is Needed From Nikita

Now:
- Confirm whether current scheduling MVP should be committed before the next implementation slice.
- Confirm production start mode: manual booking only, or auto-booking behind disabled feature flag.

Before production deploy:
- Add Railway env vars for Google and Zoom.
- Add production Google redirect URI in Google Cloud Console.
- Re-authorize Google Calendar via production URL.

For email notifications:
- Provide Resend API key or Gmail SMTP app password.
- Confirm notification email address.

For scenarios/evals:
- No manual writing needed initially.
- Human approval is needed only to activate mined scenario cards.

---

## Source Notes

- OpenAI Agents SDK supports tools, handoffs, streaming, and tracing; use it after the simpler structured runtime is stable.
- OpenAI Responses API supports tool/function calling and stateful responses; it is the lowest-risk next API surface for structured actions.
- OpenAI Evals API supports datasets, graders, and eval runs; use it after local JSONL evals are stable.
