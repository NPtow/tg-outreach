# Git and Railway deployment rules

This project has two Railway application services:

- `tg-outreach` - web/API service.
- `tg-outreach-worker` - Telegram runtime service.

Both services must deploy from the same GitHub repository and the same `main`
commit. Production must not depend on a local machine state.

## Production source of truth

- GitHub repository: `NPtow/tg-outreach`
- Production branch: `main`
- Railway project: `artistic-purpose`
- Production environment: `production`

Required Railway source setup:

| Service | Source | Branch | Runtime role |
| --- | --- | --- | --- |
| `tg-outreach` | GitHub `NPtow/tg-outreach` | `main` | `TG_RUNTIME_ROLE=web` |
| `tg-outreach-worker` | GitHub `NPtow/tg-outreach` | `main` | `TG_RUNTIME_ROLE=worker` |

Production deployments should show a GitHub commit hash for both services. A
production deployment that shows `via CLI` is a release-process bug unless it is
an explicitly approved emergency rollback.

## Hard rules

1. Do not run `railway up` against `production`.
2. Do not deploy production from a dirty local worktree.
3. Do not deploy production from a feature branch.
4. Do not let web and worker run different commits.
5. Do not run multiple production Telegram workers against the same accounts.
6. Pause active campaigns before changes that restart `tg-outreach-worker`.
7. Production fixes must be committed to Git before deployment.

## Normal feature flow

1. Start from current `main`.

   ```bash
   git fetch origin main
   git switch -c feature/<short-name> origin/main
   ```

2. Make changes locally.
3. Run focused tests.
4. If the change affects production behavior, test it in staging first.
5. Merge/push to `main`.
6. Let Railway auto-deploy both `tg-outreach` and `tg-outreach-worker`.
7. Verify both services are on the same commit.

## Hotfix flow

Use this for small production fixes only.

1. Create a clean branch from `origin/main`.

   ```bash
   git fetch origin main
   git switch -c fix/<short-name> origin/main
   ```

2. Make the smallest safe change.
3. Add or update a focused regression test.
4. Run the relevant test command.
5. Commit and push to `main` only after tests pass.
6. Wait for Railway auto-deploy.
7. Confirm web and worker match the same commit.

## Local development

Local work can be messy; production cannot.

- Keep experimental work on feature branches.
- Do not use the production Railway environment for local experiments.
- Use staging for integration tests.
- If local work needs Telegram runtime, make sure it does not use the same
  production accounts at the same time as production worker.

## Staging policy

Staging is for validating risky changes before production.

Safe staging defaults:

- Separate staging database.
- Staging web can be deployed freely.
- Staging worker should be disabled unless it uses test Telegram accounts.
- Never run staging worker and production worker against the same Telegram
  accounts.

## Pre-deploy checklist

Before production deploy:

- `git status --short` is clean for the deployment worktree.
- The target commit is pushed to `origin/main`.
- Active campaigns are paused if `tg-outreach-worker` will restart.
- Tests relevant to the change passed.
- The change does not require a database migration that has not been tested.

## Post-deploy verification

Check service status:

```bash
railway service status --all --json --environment production
```

Check deployment metadata:

```bash
railway status --json
```

Expected result:

- `tg-outreach` source repo is `NPtow/tg-outreach`.
- `tg-outreach-worker` source repo is `NPtow/tg-outreach`.
- Both services show the same `commitHash`.
- Both services are `SUCCESS`.
- Worker runtime reports `role=worker` and `owns_runtime=true`.

Worker runtime check:

```bash
TOKEN=$(railway variable list --environment production --service tg-outreach --kv \
  | awk -F= '$1=="WORKER_SHARED_TOKEN"{print substr($0,index($0,"=")+1)}')

curl -sS -H "X-Worker-Token: $TOKEN" \
  https://tg-outreach-worker-production.up.railway.app/internal/runtime/status
```

Recent worker error check:

```bash
railway logs --environment production --service tg-outreach-worker --since 10m --lines 300 \
  | rg -i "ERROR|Traceback|Could not find the input entity|OpenAI-compatible|auto_reply_skipped"
```

## Rollback policy

Preferred rollback:

1. Pause campaigns.
2. Use Railway deployment history to rollback/redeploy the previous known-good
   deployment.
3. Confirm service health and logs.
4. Revert or fix `main` so Git remains the source of truth.

Do not create a new production CLI deployment as the default rollback path.
CLI deployment is allowed only if GitHub/Railway source deployment is blocked
and the user explicitly approves the emergency action.

## Red flags

Investigate before continuing if any of these are true:

- Worker deployment says `via CLI`.
- Web and worker have different commit hashes.
- Worker has no GitHub deployment trigger.
- A local folder is dirty and someone wants to deploy it.
- Two workers can access the same Telegram accounts.
- A production issue can only be reproduced in one service, not the other.

## Current baseline

As of the deployment-process cleanup, the expected production baseline is:

- `tg-outreach`: GitHub `NPtow/tg-outreach`, branch `main`.
- `tg-outreach-worker`: GitHub `NPtow/tg-outreach`, branch `main`.
- Baseline commit: `8618a4e` (`fix: resolve manual replies by username`).
