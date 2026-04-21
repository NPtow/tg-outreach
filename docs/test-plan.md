# TG Outreach Runtime Simplification Test Plan

## Test Levels
- Unit/regression: validate account health mapping and outreach inbox persistence in `tests/test_outreach_runtime.py`.
- Integration-light: search code for removed account-limit states and verify no remaining runtime branch writes them as account health.
- Frontend build: verify Accounts/Campaigns UI compiles after removing old limit labels and filters.
- Production smoke: verify Railway serves the pushed commit and `/api/accounts/` returns simplified health without transient limit/debug leakage.

## Critical Regression Cases
- Online account with valid session/proxy and stale `PEER_FLOOD` remains `working`.
- Online account with valid session/proxy and stale `FLOOD_WAIT` remains `working`.
- Online account with valid session/proxy and stale `USERNAME_RESOLUTION_RESTRICTED` remains `working`.
- Public health/debug does not expose `PEER_FLOOD`, `FLOOD_WAIT`, `USERNAME_RESOLUTION_RESTRICTED`, `blocked_quarantine`, or `blocked_resolution`.
- Internal campaign eligibility does not block on transient send or username-resolution codes.
- Flood handlers do not write account health errors.
- Username resolution failure marks the target failed or records a campaign-level reason, but does not mark the account restricted.
- Incoming outreach message is saved before AI provider checks.
- Missing OpenAI key or disabled AI does not prevent inbox persistence.
- Campaign send creates conversation and assistant message immediately.
- Manual send and AI reply persist outgoing assistant messages without duplicates.
- Non-outreach incoming chat does not create a conversation.

## Commands
- `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -p 'test_outreach_runtime.py'`
- `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -p 'test_warming_worker.py'`
- `cd frontend && npm run build`
- `rg -n "PEER_FLOOD|FLOOD_WAIT|USERNAME_RESOLUTION_RESTRICTED|blocked_resolution|blocked_quarantine|quarantine" backend frontend tests`

## Production Smoke
- Confirm latest local commit is pushed to GitHub.
- Deploy Railway service `tg-outreach`.
- Confirm latest Railway deployment is successful.
- Call `GET https://tg-outreach-production.up.railway.app/api/accounts/`.
- Verify each valid online account has `health.status="working"` and `health.reason="Аккаунт онлайн и принимает сообщения"`.
- Verify account `health.debug.last_error_code` and `health.debug.last_error_message` do not contain old flood/quarantine text.
- If an account is not working, verify the reason is one of the real blockers: auth, session, proxy, runtime/client offline, or Telegram deactivation.

## Release Gates
- Backend regression tests pass.
- Warming regression tests still pass.
- Frontend build passes.
- Code search has no active account-limit/quarantine branches outside explicitly justified compatibility names or tests.
- Git status is clean after commit.
- Railway production API shows the new health model.

## Known Non-Goals
- Do not backfill old campaign conversations.
- Do not ingest all personal Telegram chats into inbox.
- Do not remove real auth/proxy/runtime failure diagnostics.
