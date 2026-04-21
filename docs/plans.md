# Railway Deployment Plan

## Цель
Задеплоить текущую версию кода (main branch) на Railway так, чтобы:
- web-сервис отдавал frontend и API
- worker-сервис подключал Telegram-аккаунты и обрабатывал авто-ответы
- оба сервиса стартовали без зависаний

## Архитектура на Railway
```
tg-outreach (web)            tg-outreach-worker (worker)
TG_RUNTIME_ROLE=web   ←→    TG_RUNTIME_ROLE=worker
Dockerfile (same)            Dockerfile (same)
Serves frontend + API        Handles Telegram clients
Forwards TG ops to worker    DATABASE_URL (shared Postgres)
```

## Текущее состояние
- `main` branch: последний коммит `c9abe57` (Merge remote-tracking branch)
- Незакоммиченные изменения: `telegram_client.py`, `worker_client.py`, `Settings.jsx`
- Railway проект: `artistic-purpose`, сервис `tg-outreach`
- Worker сервис: `tg-outreach-worker` (отдельный сервис в проекте)

## Milestone 1 — Commit & Push
**Цель:** закоммитить все pending-изменения и отправить на GitHub

**Задачи:**
- [ ] `git add backend/telegram_client.py backend/worker_client.py frontend/src/pages/Settings.jsx`
- [ ] Коммит с описанием изменений
- [ ] `git push origin main`

**DoD:** `git log --oneline -1` показывает новый коммит, push прошёл без ошибок.

**Риски:** конфликт с remote — маловероятно, merge уже был.

---

## Milestone 2 — Redeploy web-сервиса
**Цель:** Railway web-сервис (`tg-outreach`) пересобран с новым кодом

**Задачи:**
- [ ] Railway авто-деплой срабатывает при push (если linked к GitHub)
- [ ] Если нет — `railway redeploy` (в директории проекта)
- [ ] Проверить build logs: frontend build OK, pip install OK, patch_opentele OK

**DoD:** Сервис `tg-outreach` показывает `Deployment successful`, открывается UI по домену.

**Stop rule:** Если build упал — исправить ошибку до перехода к M3.

---

## Milestone 3 — Redeploy worker-сервиса
**Цель:** Railway worker-сервис (`tg-outreach-worker`) пересобран с новым кодом

**Задачи:**
- [ ] Проверить `railway variables --service tg-outreach-worker` — убедиться что `TG_RUNTIME_ROLE=worker`
- [ ] `railway redeploy --service tg-outreach-worker`
- [ ] Проверить logs: нет зависания на `connect()`, аккаунты подключаются или выдают timeout-ошибку

**DoD:** Worker стартует, в логах нет бесконечного hanging, аккаунты переходят в online/degraded.

**Stop rule:** Если worker зависает — проверить логи, найти аккаунт с мёртвым прокси, отключить его.

---

## Milestone 4 — Smoke check
**Цель:** убедиться что всё работает end-to-end

**Задачи:**
- [ ] Открыть `https://tg-outreach-production.up.railway.app` — frontend грузится
- [ ] Вкладка Accounts — аккаунты отображаются, статус корректный
- [ ] Settings — секция "Промпт" отсутствует ✓ (уже удалена)
- [ ] Написать в Telegram на один из аккаунтов — авто-ответ приходит

**DoD:** Все 4 проверки прошли.

---

## Допущения
- Оба сервиса используют один Dockerfile, роль определяется переменной TG_RUNTIME_ROLE
- GitHub linked к Railway — push триггерит auto-deploy web-сервиса
- Worker сервис деплоится отдельной командой или через UI
