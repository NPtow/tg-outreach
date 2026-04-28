# n8n Agent System Status

## Current Phase

Pipeline MVP complete locally: backend now has universal `AgentPipeline`, `/prompts` UI is replaced by Agent Pipelines, campaigns can select a pipeline, and live auto-reply can use an active n8n pipeline.

## Done

- [x] Current auto-reply flow identified in `backend/telegram_client.py`.
- [x] Existing Agent Lab, sandbox, `AgentRun`, scenarios, Google Calendar, and Zoom primitives identified.
- [x] Safe integration boundary selected: replace generation/ops decision, keep Telegram send in backend/worker.
- [x] Rollout mode selected: `off -> sandbox -> shadow -> live allowlist`.
- [x] Added `backend/n8n_agent.py` with typed webhook request/decision models and timeout-safe call result.
- [x] Added `backend/agent_policy.py` with deterministic checks for unsafe booking/reminder claims.
- [x] Extended `/api/sandbox/replay` with `engine="local|n8n"`.
- [x] Added Agent Lab engine selector for local heuristic vs n8n webhook.
- [x] Added regression tests for n8n sandbox, unsafe booking claim blocking, and malformed webhook output.
- [x] Added `AgentPipeline` and `AgentPipelineVersion` models.
- [x] Added `/api/agent-pipelines` CRUD and replay endpoint.
- [x] Replaced `/prompts` UI with Agent Pipelines UI.
- [x] Added campaign-level `agent_pipeline_id`.
- [x] Campaign create UI now selects active pipeline instead of prompt.
- [x] Auto-reply resolves `account.pipeline > campaign.pipeline > legacy prompt`.
- [x] Local server restarted on `http://127.0.0.1:8010` with local SQLite DB.
- [x] Added n8n workspace UI inside Agent Pipelines: iframe/open editor, workflow list, JSON import/export, bind workflow to pipeline.
- [x] Added backend proxy endpoints for n8n workflow list/get/import/bind without exposing n8n API calls from browser directly.

## In Progress

- [ ] n8n workflow service itself is not deployed/configured yet.
- [ ] Need configure a real n8n webhook URL in a pipeline before end-to-end replay/live test.

## Next

Create/deploy the first n8n workflow, then use `Пайплайны -> n8n Workspace`: enter n8n base URL/API key, load workflows, import/export JSON if needed, bind workflow to an active pipeline, and test via replay/live local auto-reply.

## Decisions

- n8n is orchestration layer, not source of truth.
- Backend owns policy validation and deterministic actions.
- Worker remains the only Telegram send path.
- Initial n8n live rollout must be allowlisted by account/campaign.
- First usable test should be sandbox replay, then shadow mode, then one-account live pilot.

## Assumptions

- User wants to test locally/parallel first before production rollout.
- n8n webhook URL and shared secret will be configured after n8n service exists.
- Current dirty branch `feature/conversation-agent-system` is acceptable for planning, but implementation should happen in a controlled branch/worktree before deploy.
- Live auto-reply uses a pipeline only when an active pipeline is assigned to the account or campaign. Without a pipeline, legacy prompt flow is unchanged.

## Commands

```bash
# Backend focused tests
pytest tests/test_outreach_runtime.py -k 'sandbox or agent or auto_reply'

# Frontend build after Agent Lab changes
npm --prefix frontend run build

# Verified in this environment
/Users/NIKITA/Desktop/JJFR/tg-outreach/.venv312/bin/python -m unittest discover -s tests -p 'test_outreach_runtime.py'
npm --prefix frontend run build

# Optional live API smoke after deployment
curl -fsS https://tg-outreach-production.up.railway.app/api/agents/runs | head
```

## Blockers

- n8n service URL and shared secret are not created yet.
- Need actual n8n workflow before end-to-end replay/live can call a real webhook.

## Audit Log

- 2026-04-27: plan created for n8n-based auto-reply orchestration with sandbox/shadow/live rollout.
- 2026-04-27: implemented n8n sandbox adapter/policy/UI selector; full `test_outreach_runtime.py` passed via unittest; frontend build passed.
- 2026-04-27: implemented universal AgentPipeline block and campaign assignment; full `test_outreach_runtime.py` passed via unittest; frontend build passed; local API smoke passed.
- 2026-04-27: implemented n8n workspace inside Agent Pipelines; full `test_outreach_runtime.py` passed via unittest; frontend build passed; local API smoke passed.
