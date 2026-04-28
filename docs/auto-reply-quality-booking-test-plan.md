# Test Plan — Auto-Reply Quality, Booking, And Human Timing

## Test Levels

| Level | Goal | Command / check |
|---|---|---|
| Unit | Validate helpers, policy, delay formula, booking URL generation | `PYTHONPATH=. python tests/test_outreach_runtime.py -k "policy or booking or auto_reply"` |
| n8n replay | Validate model decision without Telegram send | `POST /api/agent-pipelines/1/replay` |
| Scenario replay | Validate replies against known conversation samples | dedicated fixtures in `tests/test_outreach_runtime.py` |
| Live local booking | Validate Google/Zoom event creation and no-overlap | `python /Users/NIKITA/Desktop/JJFR/artifacts/n8n/run_live_booking_tests.py` |
| Telegram smoke | Validate read/typing/send timing on one local account | one manual inbound message |

## Critical Conversation Fixtures

### Fixture 1 — Repeated "what is product"

Transcript:

```text
user: Так что за продукт
assistant: Это раннее исследование про найм...
user: А что мне будет?
assistant: Ничего обязательного...
user: Я имею ввиду что я за это получу
```

Expected:

- no repeated full pitch;
- no repeated meeting CTA;
- answer directly about personal value;
- length <= 260 chars;
- if ambiguous, asks one clarifying question.

### Fixture 2 — Slot then email

Transcript:

```text
assistant: Подойдет, уточните email...
user: pussernikita@gmail.com
```

Expected after fix:

- this exact flow should not happen anymore;
- system must check availability before saying "подойдет";
- if slot is busy, alternatives are returned before asking email;
- if slot is free, event can be created without email.

### Fixture 3 — Slot without email

Transcript:

```text
user: Завтра в 16:00 подойдет
```

Expected:

- n8n extracts slot;
- backend checks busy;
- if free: creates event and returns calendar add link;
- if busy: returns alternatives;
- no email request by default.

### Fixture 4 — Ambiguous short message

Transcript:

```text
user: И что?
```

Expected:

- asks a clarification question;
- does not invent meaning;
- no booking CTA.

### Fixture 5 — Hard decline

Transcript:

```text
user: Не интересно
```

Expected:

- one short close reply;
- no follow-up question;
- no meeting CTA.

## Booking Acceptance Gates

- [ ] Backend has an availability check path independent from event creation.
- [ ] `slot + no email` does not produce `request_email` by default.
- [ ] `slot + busy` creates no `ScheduledMeeting`.
- [ ] `slot + free` creates exactly one `ScheduledMeeting`.
- [ ] `calendar_add_url` is present for no-email booking.
- [ ] `calendar_html_link` remains stored as evidence.
- [ ] Zoom link is included in event details, not used as primary chat link.

## Reply Quality Acceptance Gates

- [ ] Replies are within intent-specific length bands.
- [ ] Repeated questions get incremental answers.
- [ ] Ambiguous messages get clarifying questions.
- [ ] Trust/context replies do not end with CTA unless user intent is scheduling.
- [ ] Scenario cards used in prompt are visible in `AgentRun.input_json`.

## Timing Acceptance Gates

- [ ] Read acknowledgment is attempted within `2-10s`.
- [ ] Typing pulse starts within `2-10s`.
- [ ] Send delay is logged with task type, input length, reply length, and final delay.
- [ ] Booking replies have longer delay than short clarifications.
- [ ] Stale trigger cancellation still prevents duplicate sends.

## Negative Tests

| Case | Expected |
|---|---|
| n8n says slot is free without backend result | blocked or ignored |
| booking API returns busy | no event, alternatives in reply |
| booking API fails | no fake invite claim |
| reply repeats previous assistant message | policy blocks or trims |
| reply too long for simple intent | policy blocks or trims |
| Telegram receives newer user message while old reply pending | old task canceled |
| no scenario match | ask clarification or safe fallback |

## Evidence Artifacts

Each full local test should save or print:

- input transcript;
- selected scenario cards;
- n8n structured decision;
- backend policy result;
- booking API result;
- read/typing/send timing logs;
- final reply text.

Existing proof location for booking tests:

```text
/Users/NIKITA/Desktop/JJFR/artifacts/n8n/live-booking-tests/
```
