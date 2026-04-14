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
- Confirm runtime env setup for app token, worker token, and encryption key

## Next
- Configure Railway services with separate roles
- Run a live smoke test with one real account and proxy
- Verify campaign preflight against healthy and unhealthy accounts

## Decisions
- Runtime roles: `all` for local/dev, `web` for public API, `worker` for long-lived Telegram ownership
- Conservative anti-ban defaults
- `tdata` stays the recovery source when available

## Commands
- `python3 -m compileall backend`
- `cd frontend && npx tsc --noEmit`
