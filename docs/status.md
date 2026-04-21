# TG Outreach Runtime Simplification Status

## Current Phase
- In progress: commit, push, Railway deploy, and production smoke.

## Current Worktree State
- Branch: `claude/hungry-greider-c9fdb3`
- Base: pushed `origin/main` contains commit `87512a2` with simplified public health and outreach inbox persistence.
- Modified files are the runtime simplification patch, docs pack, frontend status display, and regression tests.

## Done
- Durable plan written for removing account-limit/quarantine behavior.
- Subagents completed backend and frontend/API audits with no actionable findings.
- Public health ignores `PEER_FLOOD`, `FLOOD_WAIT`, and `USERNAME_RESOLUTION_RESTRICTED`.
- Public debug normalizes legacy `connection_state="quarantined"` to `offline`.
- Stored `blocked_quarantine` and `blocked_resolution` no longer flow into public/debug eligibility.
- Campaign worker no longer writes `PEER_FLOOD`, `FLOOD_WAIT`, or username-resolution errors into account health.
- Username resolution is handled as a target failure, not an account restriction.
- `clear-quarantine` public/internal endpoints were removed; `/unblock` remains as the reset/reconnect path.
- `quarantine_until` was removed from the ORM model and new DB bootstrap schema.
- Accounts UI no longer shows blocked-resolution or "temporarily cannot send" state.
- Campaign account picker uses `health.can_receive`, not transient outreach-limit state.

## Validation Completed
- `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -p 'test_outreach_runtime.py'` passed: 9 tests.
- `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -p 'test_warming_worker.py'` passed: 3 tests.
- `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall backend` passed.
- `cd frontend && npm run build` passed.

## In Progress
- Commit scoped changes.
- Push to `origin/main`.
- Deploy Railway service `tg-outreach`.
- Verify production `/api/accounts/` does not expose quarantine/flood account state.

## Next
- Run final `git status`.
- Commit with a scoped message.
- Push/deploy/smoke.

## Decisions
- Keep real blockers: auth, proxy, session, runtime offline, Telegram deactivation.
- Remove transient blockers: flood wait, peer flood, username resolution.
- Treat username resolution as target failure, not account failure.
- Keep legacy cleanup literals only to scrub old DB rows; they are not public API or runtime gating.

## Assumptions
- The source-of-truth worktree is `/Users/NIKITA/tg-outreach/.claude/worktrees/hungry-greider-c9fdb3`.
- `/Users/NIKITA/Desktop/JJFR/tg-outreach` is stale unless proven otherwise.
- Railway deployment should use the pushed GitHub state, not a separate local-only patch.

## Commands
- `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -p 'test_outreach_runtime.py'`
- `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -p 'test_warming_worker.py'`
- `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall backend`
- `cd frontend && npm run build`
- `rg -n "clear-quarantine|clear_quarantine|_mark_username_resolution_restricted|_mark_error\\([^\\n]*\\\"(PEER_FLOOD|FLOOD_WAIT|USERNAME_RESOLUTION_RESTRICTED)|outgoing_limited|blocked_resolution|blocked_quarantine|PEER_FLOOD|FLOOD_WAIT|USERNAME_RESOLUTION_RESTRICTED|quarantine" backend frontend tests`
- `railway up --service tg-outreach --detach`

## Audit Log
- 2026-04-21: Replaced older self-healing/quarantine plan with focused account-limit removal plan.
- 2026-04-21: Implemented runtime simplification and validated local tests/build.
