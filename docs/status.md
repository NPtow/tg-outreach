# TG Outreach Execution Status

## Current Phase
- In progress: final validation and Railway deployment wiring

## Done
- Repository analyzed
- Delivery plan finalized
- External references checked for Railway, Telethon, and OpenTele constraints
- Runtime split foundations implemented
- Account health model implemented
- Worker forwarding and internal runtime API implemented
- Frontend updated for health states, proxy test, worker status, and safer settings

## In Progress
- Confirm end-to-end deploy wiring for Railway `web` + `worker`
- Add account-level username-resolution restriction check so public handles are not misclassified as dead targets

## Next
- Run a live smoke test with one real account and proxy
- Verify campaign behavior when a public username exists but the account cannot resolve it
- Verify campaign preflight against healthy and unhealthy accounts

## Decisions
- Runtime roles: `all` for local/dev, `web` for public API, `worker` for long-lived Telegram ownership
- Conservative anti-ban defaults
- `tdata` stays the recovery source when available

## Commands
- `python3 -m compileall backend`
- `cd frontend && npx tsc --noEmit`
