# Локальный Dify для базы сценариев

## Что уже подключено

TG Outreach умеет отправлять активные сценарии в Dify Knowledge API:

- `GET /api/scenarios/dify/status` показывает, настроена ли интеграция.
- `POST /api/scenarios/dify/sync?status=active` отправляет активные сценарии в Dify.
- Повторная синхронизация обновляет старый документ, если у сценария уже есть `dify_document_id`.
- Черновики и предложения не отправляются, пока не станут активными.

## Как поднять Dify локально

На этой машине сейчас нет команды `docker`, поэтому сначала нужен Docker Desktop.

После установки:

```bash
cd /Users/NIKITA/Desktop/JJFR
git clone https://github.com/langgenius/dify.git
cd dify/docker
cp .env.example .env
docker compose up -d
```

Открой Dify:

```text
http://127.0.0.1/install
```

Создай базу знаний для сценариев и возьми ключ именно во вкладке базы знаний `API Access`.

## Переменные для TG Outreach

```bash
export DIFY_API_BASE_URL=http://127.0.0.1/v1
export DIFY_API_KEY=ключ_из_Dify_Knowledge_API_Access
export DIFY_DATASET_ID=id_базы_знаний
```

После этого перезапусти backend и открой `/agents`. В блоке `Синхронизация с Dify` должен появиться статус `Dify настроен`.

## Проверка без интерфейса

```bash
curl http://127.0.0.1:8010/api/scenarios/dify/status
curl -X POST "http://127.0.0.1:8010/api/scenarios/dify/sync?status=active"
```

Если Dify вернет ошибку, она сохранится в полях сценария:

- `dify_sync_status`
- `dify_sync_error`
- `dify_synced_at`
