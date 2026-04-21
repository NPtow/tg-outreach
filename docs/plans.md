# TG Outreach Minimal Accounts Plan

## Goal
- Remove the invented account health model from public API/UI.
- Remove the warming module completely from backend, frontend, models, bootstrap, and tests.
- Keep accounts simple: DB row, Telegram session, proxy, and live Telethon client.
- Public account output exposes only direct status fields: `status`, `reason`, `is_online`, `can_receive`, `can_auto_reply`, `can_start_outreach`.

## Required Blocks
- Accounts CRUD and tdata/session import.
- Telegram runtime connect/reconnect/send/receive.
- Campaign sending.
- Inbox persistence and AI replies.
- Settings, prompts, contacts, conversations, DNC.

## Removed Blocks
- Warming worker.
- Warming router and `/api/warming/*`.
- Warming frontend page and sidebar item.
- Warming ORM models and bootstrap columns.
- Nested account diagnostic payload.
- `/api/accounts/{id}/health`.

## Validation
- Backend compile: `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m compileall backend`
- Runtime tests: `/Users/NIKITA/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m unittest discover -s tests -p 'test_outreach_runtime.py'`
- Frontend build: `cd frontend && npm run build`
- Search gate: no backend/frontend references to warming; no public account `health` payload.
