# Auto-Reply Quality, Booking, And Human Timing Plan

## Outcome

Make live auto-reply feel less templated, shorter, and operationally safer:

- replies should add new information instead of repeating prior thoughts;
- unclear messages should trigger a clarifying question instead of invented context;
- scheduling must check calendar availability before claiming a slot;
- users should be able to book without sharing email by receiving a calendar add/event link;
- Telegram should mark messages as read and show typing behavior before sending, with delay based on message/task complexity.

## Current Root Causes

1. **Repetitive replies**
   The n8n workflow has a static system prompt and passes recent messages, but it does not explicitly require incremental replies. It allows the model to restate the research pitch and repeat the same CTA.

2. **Long replies**
   The prompt says "1-3 предложения", but there are no hard length bands by intent. The model optimizes for completeness, not conversation speed.

3. **Weak scenario grounding**
   Dify is not wired into live generation yet. The repo already has `ScenarioCard` and `active_scenarios_for_text`, so the short-term replacement should be lightweight local scenario retrieval from DB, not a full Dify dependency.

4. **Booking contradiction**
   Current flow asks for email before booking. Therefore when a user proposes a slot without email, the agent can say "подойдет" before the backend checks Google Calendar. Busy detection currently happens only when booking is actually created.

5. **Email requirement is too heavy**
   Current booking flow prefers attendee email. User wants a lighter path: create event, send a link, and let the lead add/open it without sharing email.

6. **Timing feels mechanical**
   Auto-reply currently uses a fixed random delay window (`20-45s`). It does not depend on inbound length, reply length, or task type. It also does not separate read acknowledgment and typing behavior from send delay.

## Product Rules

### Reply Quality

- Every reply must answer the latest message as the next logical step in the thread.
- Do not restate the same pitch unless the user explicitly asks for a recap.
- If the answer would repeat the previous answer, compress it into a delta:
  - "Если совсем прямо: ..."
  - "Понял, вы про личную пользу. Тогда ..."
  - "Да, это скорее исследование, не продуктовая демка."
- If the model is unsure what the user means, ask one short clarification:
  - "Вы имеете в виду личную пользу для вас или что получит компания?"
  - "Вы про компенсацию, итог исследования или сам формат разговора?"
- Do not add a meeting CTA to every reply. Add it only when it naturally follows.

### Length Bands

| Intent | Target length | Rule |
|---|---:|---|
| simple clarification | 1 sentence, 80-180 chars | direct answer only |
| trust / "что за продукт" | 1-2 sentences, 160-320 chars | context + boundary |
| value question / "что мне будет" | 1-2 sentences, 120-260 chars | direct value, no full pitch |
| scheduling | 1 sentence, 80-180 chars | slot/link/alternative only |
| hard decline | 1 sentence, 40-120 chars | thank and close |
| ambiguous | 1 question, 40-160 chars | ask clarification |

### Example Target Behavior

Input:

```text
А что мне будет?
```

Good:

```text
Если прямо: могу потом прислать короткое резюме по типовым проблемам и паттернам, которые увижу в исследовании. Денег/сервиса за разговор пока нет.
```

Input:

```text
Я имею ввиду что я за это получу
```

Good:

```text
Понял. Личная выгода — краткий итог исследования после серии интервью. Если это не ценно, не буду отвлекать.
```

Bad:

```text
Понимаю вопрос — если коротко, прямой пользы в виде сервиса тут пока нет: это исследовательский разговор...
```

Reason: repeats the same idea and reopens the meeting pitch.

## Booking Rules

### Required Deterministic Flow

The model must not decide that a slot is free. Backend/booking adapter decides availability.

1. User gives a slot.
2. n8n extracts `start_at`, `duration_minutes`, optional `attendee_email`.
3. Backend checks Google Calendar.
4. If busy:
   - do not create event;
   - return 2-3 alternatives;
   - reply with alternatives only.
5. If free and email exists:
   - create Google Calendar event;
   - add attendee email;
   - send update/invite;
   - return calendar link.
6. If free and email does not exist:
   - create Google Calendar event in owner calendar;
   - create Zoom meeting if configured;
   - return a public "add to calendar" URL/template link plus event evidence;
   - do not ask for email by default.

### Important Link Decision

Google `htmlLink` is useful as owner-side event evidence, but may not be reliable as a public add-to-calendar link for a person who is not an attendee. Therefore the implementation should return two separate fields:

- `calendar_html_link`: backend/internal Google event link;
- `calendar_add_url`: lead-facing add-to-calendar URL generated from title, dates, timezone, description, and Zoom link.

The chat reply should use `calendar_add_url` when available. If email was provided, mention that an invite should also arrive by email.

### Forbidden Booking Replies

- "Подойдет, пришлите email" before checking availability.
- "Зафиксировал" before event creation succeeds.
- "Инвайт отправлен" without attendee email and successful Google API response.
- Zoom link as the main chat link unless calendar link generation fails.

## Interim Scenario System Before Dify

Use the existing local DB scenario cards as a "half-step" before Dify:

- seed/activate core scenario pack;
- select top 3-5 cards through `active_scenarios_for_text(db, latest_user_text)`;
- include selected cards in the n8n payload under `scenario_cards`;
- update n8n prompt to treat them as compact rules/examples, not as long RAG context.

This gives scenario grounding without adding Dify runtime risk.

Later Dify can replace the selection source while keeping the same n8n payload contract.

## Human Timing Rules

### Read/Typing Phases

For every incoming message eligible for auto-reply:

1. Persist incoming message immediately.
2. Within `2-10s`, mark the Telegram dialog as read.
3. Start a short typing pulse within `2-10s`.
4. Generate the reply in background.
5. Before sending, show typing again for a duration based on reply length.
6. Send only after computed human delay has elapsed.

### Delay Formula

Use deterministic task classification plus jitter:

| Task type | Base delay |
|---|---:|
| clarification / short answer | 12-25s |
| trust/context answer | 20-45s |
| scheduling without booking | 12-25s |
| booking/calendar action | 25-60s |
| fallback/human-review | no auto-send |

Additional adjustments:

- inbound length: `+ min(20s, chars * 0.03s)`;
- reply length: typing duration `clamp(reply_chars / 14, 3s, 18s)`;
- if booking API call is used: add at least `5-10s` perceived operation delay;
- cap normal auto-reply delay at `90s` unless task is explicitly deferred.

## Implementation Milestones

### M1 — Response Quality Prompt + Policy

Status: `[ ]`

Tasks:

- Update n8n system prompt with incremental reply rules.
- Add length bands by intent.
- Add "ask clarification if ambiguous" rule.
- Add examples for "что мне будет" and repeated clarification.
- Add verifier/policy check for repeated CTA and overlong replies.

Definition of done:

- Replay examples produce shorter, non-repetitive answers.
- No default CTA on every answer.
- Ambiguous test returns a question.

Validation:

```bash
PYTHONPATH=. python tests/test_outreach_runtime.py -k "n8n or policy or scenario"
```

### M2 — Local Scenario Retrieval Into Pipeline

Status: `[ ]`

Tasks:

- Ensure founder research scenario pack is seeded locally.
- Add `scenario_cards` to pipeline request payload using `active_scenarios_for_text`.
- Limit payload to top 3-5 cards and compact fields: title, intent, recommended_reply, avoid_reply.
- Update n8n prompt to use cards as scenario guidance.

Definition of done:

- Replay shows selected scenario cards in `AgentRun.input_json`.
- "Что за продукт", "что мне будет", "это продажа" use scenario-specific short responses.

Validation:

```bash
PYTHONPATH=. python tests/test_outreach_runtime.py -k "scenario or pipeline"
```

### M3 — Availability-First Booking Without Required Email

Status: `[ ]`

Tasks:

- Add booking availability check endpoint or adapter method.
- Change n8n booking logic:
  - slot + no email -> check/create event/link, not `request_email`;
  - slot + email -> create event with attendee;
  - busy -> alternatives only.
- Add `calendar_add_url` to booking response.
- Reply with lead-facing calendar add link.

Definition of done:

- The system never says a slot is suitable before backend availability check.
- User can book by sending only a slot.
- Busy slot returns alternatives without creating duplicate event.
- Email remains optional.

Validation:

```bash
PYTHONPATH=. python tests/test_outreach_runtime.py -k "booking"
python /Users/NIKITA/Desktop/JJFR/artifacts/n8n/run_live_booking_tests.py
```

### M4 — Dynamic Read/Typing/Delay

Status: `[ ]`

Tasks:

- Replace fixed `20-45s` delay with task/length-based delay helper.
- Add read acknowledgment task within `2-10s`.
- Add Telegram typing action/pulse before send.
- Log delay inputs and computed timing.

Definition of done:

- Runtime logs show read delay, typing start, computed send delay, and send time.
- Short replies send faster than booking replies.
- No duplicate outgoing messages.

Validation:

```bash
PYTHONPATH=. python tests/test_outreach_runtime.py -k "auto_reply"
```

### M5 — Evidence And Regression Pack

Status: `[ ]`

Tasks:

- Add replay fixtures for the provided conversation sample.
- Save replay outputs for quality before/after.
- Add live local proof logs for booking and no-overlap.
- Add one manual Telegram smoke test after local replay passes.

Definition of done:

- Evidence includes chat transcript, n8n decision, policy, delay log, and booking result.
- No production deployment required.

Validation:

```bash
PYTHONPATH=. python tests/test_outreach_runtime.py
npm --prefix frontend run build
```

## Stop-And-Fix Rules

- If n8n returns malformed JSON, stop and fix workflow schema before prompt tuning.
- If booking creates a duplicate slot, stop and fix backend availability check before more prompt changes.
- If typing/read causes duplicate sends or stale replies, stop and fix task lifecycle before live testing.
- If Google add-to-calendar URL is not usable externally, fall back to asking email only after explaining why.

## Out Of Scope For This Patch

- Full Dify production integration.
- Full eval harness UI.
- Multi-account production rollout.
- Railway deployment.
