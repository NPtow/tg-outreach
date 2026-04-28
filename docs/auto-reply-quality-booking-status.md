# Auto-Reply Quality, Booking, And Human Timing Status

## Current Phase

Local implementation complete for M1-M4. Ready for local n8n/backend live replay or manual Telegram smoke test.

## Done

- [x] User examples analyzed.
- [x] Root causes separated by layer: prompt, scenario grounding, booking adapter, Telegram timing.
- [x] Existing local scenario-card infrastructure identified: `ScenarioCard`, `active_scenarios_for_text`, founder research pack.
- [x] Existing booking weakness identified: busy check happens only when booking is created; no-email flow currently causes premature "slot works" language.
- [x] Existing timing behavior identified: fixed `AUTO_REPLY_DELAY_MIN_S=20`, `AUTO_REPLY_DELAY_MAX_S=45`.
- [x] n8n workflow prompt updated with short incremental reply rules.
- [x] Backend policy blocks overlong repeated CTA replies.
- [x] Pipeline request now includes active local scenario cards.
- [x] Booking supports `slot + no email` and returns `calendar_add_url`.
- [x] Telegram auto-reply now attempts read + typing presence and logs dynamic timing.
- [x] Local DB schema initialized with `scheduled_meetings.calendar_add_url`.
- [x] Active local n8n sqlite workflow `VSI5AeNIE6dykCh4` updated from generated JSON.

## In Progress

- [ ] Local manual live smoke is not running yet because backend/n8n are currently stopped.

## Next

Start backend and n8n, then replay one real conversation and one booking scenario.

## Decisions

- Local scenario cards are the interim scenario database before Dify.
- n8n remains the orchestration layer.
- Backend remains responsible for calendar availability, event creation, Zoom, and final safety.
- Email becomes optional for booking.
- Chat should prefer `calendar_add_url` over owner-side Google `htmlLink` and raw Zoom.
- Availability must be checked before confirming a slot.

## Assumptions

- Testing stays local first.
- The user accepts creating test calendar events during explicit live booking tests.
- Dify will be integrated later; this patch should not depend on Dify being available.
- If no-email calendar event links are not externally usable enough, fallback will be to ask for email after explaining why.

## Commands

```bash
# Backend tests
PYTHONPATH=. python tests/test_outreach_runtime.py

# Focused tests while implementing
PYTHONPATH=. python tests/test_outreach_runtime.py -k "n8n or policy or scenario or booking or auto_reply"

# Frontend build if UI touched
npm --prefix frontend run build

# Local live booking proof after booking changes
python /Users/NIKITA/Desktop/JJFR/artifacts/n8n/run_live_booking_tests.py
```

## Blockers

- n8n binary/server is not currently running on local port `5678`.

## Audit Log

- 2026-04-28: created focused plan for shorter replies, local scenario grounding, availability-first booking, no-email booking link, and dynamic read/typing delay.
- 2026-04-28: implemented local code changes and verified `86` backend tests pass with `.venv/bin/python`.
