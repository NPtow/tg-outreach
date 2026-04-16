# TG Outreach Self-Healing Runtime Plan

## Goal
- Split the app into `web` and `telegram-worker` runtime roles.
- Make account health explicit and observable.
- Ensure campaigns only run on eligible accounts with conservative anti-ban behavior.

## Milestones
- [x] Add runtime foundations: role config, worker forwarding, auth, encryption, event relay.
- [x] Extend persistence with account health fields and runtime event storage.
- [x] Rework Telegram runtime for health-aware reconnect, proxy checks, quarantine, and preflight campaign start.
- [x] Update public API for account health, proxy test, runtime status, and safe campaign start.
- [x] Update frontend for account health, proxy management, worker status, and structured campaign failures.
- [~] Validate build/runtime flows and document deploy assumptions for Railway `web` + `worker`.
- [~] Add username-resolution restriction detection so campaigns block restricted accounts instead of falsely failing valid public usernames.
- [~] Repair warming execution path so Phase 1 performs real actions, quotas are enforced, and progress/heartbeats are observable in API and UI.

## Validation Assumptions
- Backend syntax: `python3 -m compileall backend`
- Frontend typecheck: `cd frontend && npx tsc --noEmit`
- Full smoke: start app in `TG_RUNTIME_ROLE=all` locally and verify API/UI
