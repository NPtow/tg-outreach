# TG Outreach Minimal Accounts Test Plan

## Checks
- Account list returns direct fields: `status`, `reason`, `is_online`, `can_receive`, `can_auto_reply`, `can_start_outreach`.
- Account list does not return nested diagnostic account payload.
- Removed warming files are not imported by backend or frontend.
- Campaign account picker uses direct `can_receive`.
- Inbox and auto-reply regression tests still pass.

## Commands
- `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall backend`
- `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -p 'test_outreach_runtime.py'`
- `cd frontend && npm run build`
- `rg -n "warming|Warming|warmup|warm_|min_health_score|AccountWarming|WarmingAction|WarmingProfile|WarmingChannelPool|account_health" backend frontend/src tests`

## Production Smoke
- Deploy Railway service `tg-outreach`.
- Call `GET /api/accounts/`.
- Confirm each account has direct status fields and no nested diagnostic payload.
- Confirm `/api/warming/*` is gone.
