# TG Outreach Test Plan

## Critical Flows
- Account with valid proxy reconnects and becomes `eligible`
- Broken proxy yields `blocked_proxy`
- Expired session with stored `tdata` recovers automatically
- Expired session without recovery path yields `reauth_required`
- Campaign start returns structured blocked reasons when no eligible accounts exist
- Campaign continues using healthy accounts while quarantining risky ones
- Campaign pauses or blocks an account when Telegram cannot resolve a publicly existing username
- Web UI works against same-origin API and configurable WebSocket URL
- Settings API does not return secret values
- Warming start produces a heartbeat within minutes and logs attempted/success/skipped action rows
- Warming score stays near zero when no actions were executed
- Phase 1 can subscribe to one channel per day when pool entries are available
- Warming UI refreshes without manual reload and shows last decision / next action / last error

## Commands
- `python3 -m compileall backend`
- `cd frontend && npx tsc --noEmit`

## Manual Smoke
- Open Accounts page, inspect worker/account health chips
- Run proxy test on one account
- Start a campaign with at least one blocked account and verify structured response
- Confirm live updates arrive after worker emits campaign/account events
