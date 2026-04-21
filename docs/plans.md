# TG Outreach Runtime Simplification Plan

## Goal
- Remove account-limit/quarantine as a product concept and as runtime gating.
- Keep the public account model simple: `working` or `not_working`, with one human-readable reason.
- Keep only real account failures as blockers: missing/expired session, reauth required, broken proxy, Telegram client offline, runtime unavailable, or deactivated Telegram account.
- Make outreach conversations reliable: campaign/manual/AI outgoing messages persist in inbox, incoming outreach replies persist before any AI decision, and auto-reply failures do not hide messages.

## Current State
- Production already has simplified public `health`, but stale transient errors can still leak through old DB rows or remaining runtime branches.
- `PEER_FLOOD`, `FLOOD_WAIT`, and `USERNAME_RESOLUTION_RESTRICTED` are still partially treated as account-level restrictions.
- The current worktree has uncommitted partial changes that start removing those restrictions from `backend/telegram_client.py` and add regression tests in `tests/test_outreach_runtime.py`.

## Assumptions
- Inbox should contain only outreach conversations, not all personal Telegram chats.
- Old campaign sends are not backfilled; fixes apply to new campaign/manual/AI sends and new inbound replies.
- Telegram flood errors can still be logged as campaign/target runtime events, but must not be stored as account health, must not display as quarantine, and must not block receiving messages.
- A username resolution failure is a target/campaign problem, not an account health problem.

## Milestones

### M1: Remove account-limit health gates
- Status: `[x]`
- Goal: `PEER_FLOOD`, `FLOOD_WAIT`, and username-resolution errors never make an account restricted/quarantined.
- Tasks: remove transient codes from `_compute_eligibility`, public health reason mapping, serialized debug fields, and campaign account selection.
- Tasks: scrub stale transient codes during startup, reconnect, reset, and supervisor loops.
- Done: account API shows `working` for online valid sessions even if DB had stale flood/resolution codes.
- Validation: `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -p 'test_outreach_runtime.py'`
- Stop-and-fix: if any test still exposes `PEER_FLOOD`, `FLOOD_WAIT`, `quarantine`, `blocked_quarantine`, or `blocked_resolution` in public health, fix before moving on.

### M2: Remove campaign worker persistence of account restrictions
- Status: `[x]`
- Goal: campaign send exceptions do not write transient Telegram limits into account health.
- Tasks: replace flood handlers so they log and sleep only, or clear stale account error while keeping the client online.
- Tasks: convert username-resolution failures into target failure text, not account failure state.
- Done: campaign worker has no `_mark_error(..., "PEER_FLOOD")`, no `_mark_error(..., "FLOOD_WAIT")`, and no account-level username-resolution marker.
- Validation: `rg -n "PEER_FLOOD|FLOOD_WAIT|USERNAME_RESOLUTION_RESTRICTED|blocked_resolution|blocked_quarantine|quarantine" backend/telegram_client.py frontend/src tests`
- Stop-and-fix: if transient limit strings remain outside migrations/backward-compatible endpoint names or explicit tests, explain and reduce them.

### M3: Simplify UI account selection and debug output
- Status: `[x]`
- Goal: UI no longer shows "temporary cannot send" or blocked-resolution states.
- Tasks: make campaign account picker rely on `health.can_receive` or equivalent working status.
- Tasks: remove blocked-resolution debug badge and make the Accounts card show only working/not working plus the real reason.
- Done: frontend cannot display `PEER_FLOOD: PeerFloodError - account quarantined` from account health.
- Validation: `cd frontend && npm run build`
- Stop-and-fix: if frontend build fails or UI still references removed states, fix before deploy.

### M4: Preserve inbox and auto-reply guarantees
- Status: `[x]`
- Goal: removing account restrictions must not regress outreach inbox persistence or AI reply flow.
- Tasks: keep incoming ingest before AI checks, keep outgoing persistence for campaign/manual/AI sends, and keep non-outreach chats ignored.
- Done: existing outreach runtime tests pass.
- Validation: `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -p 'test_outreach_runtime.py'`
- Stop-and-fix: if inbox persistence tests fail, repair before deploy.

### M5: Commit, push, deploy, and production smoke
- Status: `[~]`
- Goal: local, GitHub, and Railway run the same system.
- Tasks: commit scoped changes, push current branch to `origin/main`, deploy Railway, and verify production API.
- Done: Railway latest deployment uses the new commit and `/api/accounts/` shows no account-limit/quarantine state for valid online accounts.
- Validation: `git status --short --branch`, `git log -1 --oneline`, `railway up --service tg-outreach --detach`, production `GET /api/accounts/`
- Stop-and-fix: if Railway serves an older commit or API still returns stale transient health, inspect deploy logs and runtime env before further code changes.

## Done Definition
- No account can become `quarantined` or `blocked_quarantine` from runtime logic.
- `PEER_FLOOD` and `FLOOD_WAIT` do not appear in account health/debug and do not make `can_start_outreach=false`.
- Username resolution errors do not block account health.
- Campaign/manual/AI messages still appear in inbox as outreach conversations.
- Tests and frontend build pass before push/deploy.
