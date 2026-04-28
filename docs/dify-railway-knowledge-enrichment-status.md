# Статус: Railway Dify knowledge enrichment

Дата: 2026-04-28

## Текущая фаза

Offline enrichment pipeline реализован и прогнан на продовом экспорте. Railway Dify пока не изменялся.

## Уже известно

- Railway Dify доступен.
- Dataset `TG Outreach Scenarios` существует.
- Dataset id: `2b7a1b14-43ac-4a24-8fb0-1c9374c35993`.
- API base: `https://dify-api-main-staging.up.railway.app/v1`.
- В экспорт попали `58` диалогов с ответами.
- Сейчас в локальной Scenario DB есть `15` активных сценариев, уже синхронизированных с Dify.
- В Dify сейчас `18` доступных документов: `15` scenario docs и `3` вспомогательных документа.

## Done

- [x] Подтверждено, что Dify dataset отвечает через API.
- [x] Подтверждено, что текущие документы индексируются и доступны.
- [x] Сделан первичный ручной curated seed из продовых переписок.
- [x] Старые auto-analysis suggested карточки переведены в legacy.
- [x] Подготовлен детальный план нормального enrichment pipeline.
- [x] Реализованы offline scripts в `scripts/dify_enrichment`.
- [x] Сгенерированы inventory, episodes, scenario candidates, Dify markdown docs, manifest, review report.
- [x] Privacy scan по generated Dify docs прошел без critical findings.
- [x] Добавлены regression tests для enrichment rules.

## In progress

- [~] Review 7 сценариев с `review_required=true` перед возможной заливкой в Railway Dify.

## Next

1. Просмотреть `artifacts/dify-enrichment/2026-04-28/review_report.md`.
2. Решить, оставляем ли 7 `review_required` сценариев как active или правим тексты.
3. После review запустить upload в Railway Dify отдельным шагом.
4. После upload запустить retrieval smoke-test.

## Решения

- Не заливать полный экспорт напрямую в Dify.
- Не считать старые ответы ассистента автоматически правильными.
- Делать несколько типов документов: core context, scenario cards, conversation examples, negative patterns, eval cases.
- Для Dify документов использовать version tag `2026-04-28-prod-replies-v1`.
- Перед заливкой в Railway Dify обязателен review report.

## Предположения

- Railway Dify используется как staging knowledge base, а не как production TG Outreach logic.
- n8n будет читать Dify retrieval, но пока финальный agentic flow может меняться.
- Личные данные из переписок нужно вычищать перед заливкой в Dify.
- Для первого прохода достаточно semi-automatic подхода: автоматическая нарезка + отчет + ручной review спорных сценариев.

## Блокеры

- Нет блокеров для offline анализа.
- Для upload в Dify нужны актуальные `DIFY_API_BASE_URL`, `DIFY_API_KEY`, `DIFY_DATASET_ID` в окружении.

## Audit log

- 2026-04-28: создан план enrichment pipeline.
- 2026-04-28: текущая база проверена: `15 active` scenario cards, `18` Dify documents available.
- 2026-04-28: реализован offline pipeline.
- 2026-04-28: прогон на экспорте дал `58` conversations, `122` episodes, `25` active scenario candidates, `69` conversation examples, `6` negative patterns, `45` eval cases.
- 2026-04-28: generated docs count `149`, privacy critical findings `0`.
- 2026-04-28: `python3 tests/test_dify_enrichment.py` прошел.
- 2026-04-28: `python3 -m compileall -q scripts/dify_enrichment` прошел.

## Smoke checks

Последний подтвержденный Dify retrieval:

- `А мне это зачем?` -> scenario value question / conversation examples.
- `это бот?` -> bot disclosure scenario / negative patterns.
- `ссылка не открывается` -> link objection scenario / negative patterns.
- `у меня компания 150 человек` -> company size fit / not-large-company scenarios.
- `стоимость консультации 10000` -> paid consultation scenario.
