# Railway Deployment Status

## Current Phase
M1 — Commit & Push (не начато)

## Done
- [x] Фикс зависания worker: `asyncio.wait_for(client.connect(), timeout=30)` в telegram_client.py
- [x] Фикс Python 3.9 compat: `Optional[Dict[str, Any]]` в worker_client.py
- [x] Фикс авто-ответа: `getattr(event, "is_out", None)` в telegram_client.py
- [x] Удалена секция "Промпт" из Settings.jsx
- [x] Удалены Warming/Quarantine из UI

## In Progress
- [ ] M1: Commit pending changes + push to main

## Next
→ M1: git add + commit + push
→ M2: проверить auto-deploy web на Railway
→ M3: redeploy worker
→ M4: smoke check

## Незакоммиченные файлы
- `backend/telegram_client.py` — connect timeout + is_out fix
- `backend/worker_client.py` — Python 3.9 compat
- `frontend/src/pages/Settings.jsx` — удалена секция Промпт

## Команды
```bash
# M1 — commit
git add backend/telegram_client.py backend/worker_client.py frontend/src/pages/Settings.jsx
git commit -m "fix: connect timeout, worker_client compat, remove prompt section from Settings"
git push origin main

# M2 — web redeploy (если не auto)
railway redeploy

# M3 — worker redeploy
railway variables --service tg-outreach-worker
railway redeploy --service tg-outreach-worker

# M4 — smoke
open https://tg-outreach-production.up.railway.app
```

## Blockers
- Нет

## Audit log
- 2026-04-22: план создан, изменения готовы к коммиту
