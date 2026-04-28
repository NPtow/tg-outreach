# План наполнения Railway Dify базы из продовых переписок

Дата: 2026-04-28

## Цель

Сформировать нормальную базу знаний для Dify, который хостится на Railway, на основе двух файлов:

- `/Users/NIKITA/Desktop/JJFR/artifacts/prod-conversations/prod_replied_conversations_20260428T125313Z.json`
- `/Users/NIKITA/Desktop/JJFR/artifacts/prod-conversations/prod_replied_conversations_20260428T125313Z_summary.json`

Результат должен быть не просто дампом переписок, а рабочей knowledge base для n8n/агента:

- агент находит релевантный сценарий по входящему сообщению;
- агент видит реальные примеры похожих переписок;
- агент знает, какие ответы уже были плохими или рискованными;
- каждое знание можно отследить до исходной переписки;
- база лежит в Railway-hosted Dify dataset `TG Outreach Scenarios`.

## Текущий источник данных

Экспорт содержит:

- `58` диалогов, где был хотя бы один ответ ассистента и хотя бы одно сообщение собеседника;
- `193` всего просмотренных диалога в проде;
- основные кампании: `HRD`, `Тест 2`, `7`, `9`;
- основные аккаунты: `Алексей`, `Никита`, `Пташка`, `Василиса`;
- в полном файле есть сами сообщения с `role`, `text`, `created_at`;
- в summary есть быстрые поля для отбора: `message_count`, `assistant_count`, `user_count`, `status`, `last_message`, `first_user_message_at`.

## Главный принцип

Нельзя заливать все переписки одним большим текстом. Такая база будет шумной: Dify будет находить случайные куски, а агент начнет копировать старые ошибки.

Нужно сделать слой нормализации:

1. Разобрать переписки на отдельные эпизоды.
2. Классифицировать эпизоды по смыслу.
3. Выделить хорошие ответы, плохие ответы и неоднозначные места.
4. Слить дубли.
5. Залить в Dify несколько типов документов с понятной структурой и метаданными.

## Целевая структура базы в Dify

### 1. Core context

Документы с неизменяемыми правилами проекта:

- кто пишет;
- что исследуем;
- что можно обещать;
- что нельзя обещать;
- как говорить про продукт;
- как отвечать, если информации нет;
- язык, тон, длина ответа;
- запрет на приветствия в ответных сообщениях;
- запрет на выдумывание фактов.

Документы:

- `core-context-hrd-research.md`
- `core-policy-answer-style.md`
- `core-policy-scheduling.md`
- `core-policy-boundaries.md`

### 2. Scenario cards

Короткие рабочие сценарии: когда применять, как отвечать, чего избегать, какие вопросы триггерят сценарий.

Каждый сценарий должен иметь:

- `scenario_key`;
- `title`;
- `intent`;
- `stage`: qualification / scheduling / closing / trust / fallback;
- `trigger_phrases`;
- `when_to_use`;
- `recommended_reply`;
- `avoid_reply`;
- `source_conversation_ids`;
- `confidence`;
- `status`: active / review / legacy.

Ориентир по объему после нормальной обработки 58 диалогов:

- `25-40` активных сценариев;
- `10-20` сценариев в review;
- старые или слабые сценарии переводятся в legacy.

### 3. Conversation examples

Реальные примеры диалогов, очищенные от персональных данных.

Зачем нужны:

- агент видит не только правило, но и живую динамику;
- можно тестировать, не ломает ли ответ контекст;
- можно учить агента не начинать диалог заново.

Формат одного примера:

- `conversation_id`;
- `stage`;
- `situation`;
- `last_user_message`;
- `short_history`;
- `good_next_reply`;
- `why_this_reply`;
- `risk_notes`.

Ориентир:

- `40-80` примеров;
- не больше `2-4` примеров на один повторяющийся паттерн, чтобы не раздуть шум.

### 4. Negative patterns

Документы про ошибки, которые агент не должен повторять.

Типы негативных паттернов:

- отправили ссылку до того, как сняли сомнение;
- ответили как будто диалог начался заново;
- повторили Calendly после проблемы со ссылкой;
- продолжили дожимать после отказа;
- стали спорить с собеседником;
- сделали вид, что продукт уже готов;
- ответили общо там, где нужен короткий прямой ответ;
- проигнорировали вопрос “это бот?”;
- выбрали ручной слот без проверки календаря;
- смешали ручное согласование и ссылку.

Каждый паттерн должен иметь:

- `pattern_key`;
- `bad_behavior`;
- `why_bad`;
- `better_behavior`;
- `source_conversation_ids`;
- `test_queries`.

Ориентир:

- `15-30` негативных паттернов.

### 5. Evaluation set

Отдельный набор тестовых кейсов, который не обязательно использовать как Dify knowledge, но он нужен для проверки.

Каждый кейс:

- входящее сообщение;
- короткая история;
- ожидаемые retrieved documents;
- ожидаемый тип ответа;
- forbidden behavior;
- acceptance criteria.

Ориентир:

- `30-50` eval cases;
- минимум по одному кейсу на каждый активный сценарий;
- несколько конфликтных кейсов: например “согласен на созвон, но ссылка не открывается”.

## План работ

### Milestone 1. Инвентаризация экспорта

Задача:

- прочитать full export и summary;
- собрать таблицу по всем 58 диалогам;
- для каждого диалога определить: длина, аккаунт, кампания, статус, сколько user/assistant turns, есть ли scheduling, отказ, вопрос, проблема со ссылкой, ручное согласование.

Выходные артефакты:

- `artifacts/dify-enrichment/2026-04-28/conversation_inventory.json`;
- `artifacts/dify-enrichment/2026-04-28/conversation_inventory.md`.

Definition of done:

- все 58 диалогов учтены;
- у каждого есть `conversation_id`;
- нет диалогов без сообщений;
- есть список диалогов, которые нужно исключить из базы.

Validation:

```bash
python scripts/dify_enrichment/analyze_export.py \
  --full /Users/NIKITA/Desktop/JJFR/artifacts/prod-conversations/prod_replied_conversations_20260428T125313Z.json \
  --summary /Users/NIKITA/Desktop/JJFR/artifacts/prod-conversations/prod_replied_conversations_20260428T125313Z_summary.json \
  --out artifacts/dify-enrichment/2026-04-28
```

Stop-and-fix rule:

- если количество обработанных диалогов не равно `58`, дальше не идти.

### Milestone 2. Нарезка на эпизоды

Задача:

- из каждого диалога выделить отдельные смысловые эпизоды;
- один диалог может дать несколько эпизодов: objection, scheduling, closing, trust question;
- каждый эпизод должен включать до 10 последних сообщений, но без лишнего старого шума;
- первое исходящее outreach-сообщение не должно автоматически становиться частью каждого сценария, если оно не нужно для понимания.

Выходные артефакты:

- `episodes.jsonl`;
- `episodes_review.md`.

Definition of done:

- получено примерно `80-140` эпизодов из 58 диалогов;
- каждый эпизод имеет `conversation_id`, `episode_id`, `stage`, `last_user_message`, `history`, `assistant_reply`, `quality_label`.

Validation:

```bash
python scripts/dify_enrichment/extract_episodes.py \
  --inventory artifacts/dify-enrichment/2026-04-28/conversation_inventory.json \
  --out artifacts/dify-enrichment/2026-04-28/episodes.jsonl
```

Stop-and-fix rule:

- если один диалог создает слишком много одинаковых эпизодов, добавить дедупликацию по смыслу.

### Milestone 3. Таксономия сценариев

Задача:

- создать стабильную систему групп, чтобы база не превращалась в хаос;
- текущие группы:
  - `qualification`;
  - `faq`;
  - `trust`;
  - `scheduling`;
  - `closing`;
  - `fallback`;
  - `negative_patterns`;
  - `calendar_ops`.

Базовые сценарии, которые должны появиться:

- зачем это собеседнику;
- зачем это компании;
- это бот или автоматизация;
- кто пишет;
- откуда контакт;
- что за проект;
- цель исследования;
- какие гипотезы проверяются;
- это продажа;
- это отклик на вакансию;
- есть ли продукт;
- есть ли клиенты;
- что будет с информацией;
- конфиденциальность;
- подходит ли мой опыт;
- подходит ли размер компании;
- не нанимаю product-роли;
- я рекрутер не для персонала;
- не сейчас, вернусь позже;
- нет времени;
- неинтересно / неактуально;
- хочу письменно;
- готов к созвону;
- предлагает конкретные слоты;
- просит ссылку;
- ссылка не открывается;
- не перехожу по ссылкам;
- уже выбрал слот;
- просит сайт или КП;
- предлагает платную консультацию;
- короткое завершение.

Выходные артефакты:

- `taxonomy.yml`;
- `scenario_candidates.json`;
- `scenario_candidates_review.md`.

Definition of done:

- каждый эпизод либо привязан к существующему сценарию, либо создает новый candidate, либо помечен как noise;
- у каждого сценария есть список исходных `conversation_id`.

Validation:

```bash
python scripts/dify_enrichment/classify_episodes.py \
  --episodes artifacts/dify-enrichment/2026-04-28/episodes.jsonl \
  --taxonomy artifacts/dify-enrichment/2026-04-28/taxonomy.yml \
  --out artifacts/dify-enrichment/2026-04-28/scenario_candidates.json
```

Stop-and-fix rule:

- если новый сценарий отличается от существующего только формулировкой, его нужно merge, а не создавать дубль.

### Milestone 4. Генерация документов для Dify

Задача:

- собрать Dify-ready документы из candidates;
- разделить документы по типам, а не складывать все в один markdown;
- убрать персональные данные: usernames, tg_user_id, имена, если они не нужны для сценария;
- сохранить source traceability через `conversation_id`, но без личных контактов.

Формат документов:

```text
type: scenario_card | conversation_example | negative_pattern | core_policy | eval_case
version: 2026-04-28-prod-replies-v1
source_export: prod_replied_conversations_20260428T125313Z.json
source_conversation_ids: [...]
status: active | review
```

Выходные артефакты:

- `dify_documents/scenarios/*.md`;
- `dify_documents/examples/*.md`;
- `dify_documents/negative_patterns/*.md`;
- `dify_documents/core/*.md`;
- `dify_documents/evals/*.md`;
- `manifest.json`.

Definition of done:

- все документы имеют metadata block;
- все документы имеют стабильное имя;
- нет usernames и tg_user_id;
- есть manifest с sha256 каждого документа.

Validation:

```bash
python scripts/dify_enrichment/build_dify_documents.py \
  --candidates artifacts/dify-enrichment/2026-04-28/scenario_candidates.json \
  --out artifacts/dify-enrichment/2026-04-28/dify_documents \
  --manifest artifacts/dify-enrichment/2026-04-28/manifest.json
```

Stop-and-fix rule:

- если документ не имеет источника или metadata, не заливать его в Dify.

### Milestone 5. Review gate перед заливкой

Задача:

- не заливать кандидаты автоматически без отчета;
- сделать human-readable diff:
  - что будет создано;
  - что будет обновлено;
  - что будет переведено в legacy;
  - какие документы спорные.

Выходные артефакты:

- `review_report.md`;
- `review_report.json`.

Definition of done:

- видно точное количество сценариев, examples, negative patterns, eval cases;
- видно список сценариев с низкой уверенностью;
- есть dry-run план Dify операций.

Validation:

```bash
python scripts/dify_enrichment/prepare_review.py \
  --manifest artifacts/dify-enrichment/2026-04-28/manifest.json \
  --out artifacts/dify-enrichment/2026-04-28/review_report.md
```

Stop-and-fix rule:

- если больше `20%` сценариев имеют низкую confidence, сначала ручной review, потом заливка.

### Milestone 6. Заливка в Railway Dify

Задача:

- залить документы в Railway Dify dataset;
- не удалять старую рабочую базу сразу;
- использовать version prefix `2026-04-28-prod-replies-v1`;
- старые документы переводить в legacy только после successful smoke-test.

Целевая база:

- API base: `https://dify-api-main-staging.up.railway.app/v1`;
- dataset: `TG Outreach Scenarios`;
- dataset id: `2b7a1b14-43ac-4a24-8fb0-1c9374c35993`.

Выходные артефакты:

- `upload_result.json`;
- `dify_document_map.json`;
- `indexing_status.json`.

Definition of done:

- все документы созданы или обновлены;
- Dify вернул document ids;
- indexing status по всем документам: `completed`;
- display status: `available`.

Validation:

```bash
python scripts/dify_enrichment/upload_to_dify.py \
  --manifest artifacts/dify-enrichment/2026-04-28/manifest.json \
  --dify-base-url "$DIFY_API_BASE_URL" \
  --dify-api-key "$DIFY_API_KEY" \
  --dataset-id "$DIFY_DATASET_ID" \
  --out artifacts/dify-enrichment/2026-04-28/upload_result.json
```

Stop-and-fix rule:

- если хотя бы один active scenario не проиндексировался, не считать базу готовой.

### Milestone 7. Retrieval smoke-test

Задача:

- проверить, что Dify достает правильные документы по реальным вопросам;
- проверять не только top-1, но top-3;
- отдельно проверить, что negative patterns достаются на рискованных случаях.

Минимальные тестовые запросы:

- `А мне это зачем?`
- `А компании это зачем?`
- `Это бот?`
- `Почему мне пишет автоматический аккаунт?`
- `Откуда у вас мой контакт?`
- `Что за проект?`
- `Какие гипотезы проверяете?`
- `Это продажа?`
- `Я рекрутер для кастдевов, не для персонала`
- `У нас компания 150 человек`
- `В крупных компаниях не работала`
- `Сейчас нет времени`
- `Вернусь после 15 мая`
- `Давайте завтра в 18:00`
- `Ссылка не открывается`
- `Не перехожу по ссылкам`
- `Я уже выбрала слот`
- `Пришлите сайт или КП`
- `Стоимость консультации 10000`

Выходные артефакты:

- `retrieval_smoke_report.json`;
- `retrieval_smoke_report.md`.

Definition of done:

- минимум `85%` тестов возвращают ожидаемый scenario или example в top-3;
- для bot/link/refusal кейсов в top-3 есть negative pattern или explicit avoid rule;
- нет случаев, где top-1 явно опасен.

Validation:

```bash
python scripts/dify_enrichment/run_retrieval_smoke.py \
  --queries artifacts/dify-enrichment/2026-04-28/eval_queries.json \
  --out artifacts/dify-enrichment/2026-04-28/retrieval_smoke_report.md
```

Stop-and-fix rule:

- если smoke меньше `85%`, не подключать эту базу к n8n.

### Milestone 8. Agent-answer dry run

Задача:

- проверить не только retrieval, но и итоговый ответ агента;
- использовать n8n webhook или локальный mock runner;
- на вход давать последние 10 сообщений и retrieved docs;
- сохранять полный trace: вход, retrieved docs, prompt, ответ, оценка.

Выходные артефакты:

- `agent_dry_run_cases.jsonl`;
- `agent_dry_run_report.md`;
- `bad_outputs_for_review.md`.

Definition of done:

- минимум `30` кейсов прогнаны end-to-end;
- ответы короткие, без приветствий, без выдуманных фактов;
- scheduling кейсы не отправляют ссылку, если человек уже предложил слот;
- refusal кейсы не дожимаются;
- bot кейсы честно раскрывают автоматизацию.

Validation:

```bash
python scripts/dify_enrichment/run_agent_dry_run.py \
  --cases artifacts/dify-enrichment/2026-04-28/eval_cases.jsonl \
  --out artifacts/dify-enrichment/2026-04-28/agent_dry_run_report.md
```

Stop-and-fix rule:

- если агент галлюцинирует продукт, интеграции, клиентов или обещания, база не готова.

### Milestone 9. Версионирование и откат

Задача:

- не терять предыдущую рабочую базу;
- каждую загрузку версионировать;
- иметь быстрый rollback.

Правила:

- все новые документы получают tag/version `2026-04-28-prod-replies-v1`;
- предыдущие документы не удаляются до прохождения smoke и dry run;
- после успешной проверки старые документы можно перевести в legacy;
- если новая база плохая, отключаем документы версии v1 или возвращаемся к предыдущему manifest.

Выходные артефакты:

- `release_notes.md`;
- `rollback_manifest.json`;
- `active_manifest.json`.

Definition of done:

- понятно, какие Dify document ids относятся к текущей активной версии;
- понятно, какие можно удалить/legacy;
- rollback не требует ручного поиска документов в UI.

## Итоговая Definition of Done

База считается нормальной, когда:

- обработаны все `58` диалогов;
- построены episode-level данные;
- создано примерно `25-40` active scenario cards;
- создано `40-80` conversation examples;
- создано `15-30` negative patterns;
- создано `30-50` eval cases;
- все Dify документы доступны в Railway dataset;
- retrieval smoke дает минимум `85%` top-3 попаданий;
- agent dry run не показывает критических ошибок;
- есть manifest и rollback plan.

## Риски

- `58` диалогов мало для полностью автоматического самообучения, поэтому первая версия должна быть semi-automatic с review gate.
- В переписках есть персональные данные, их нельзя бездумно заливать в Dify.
- Старые ответы ассистента могут быть плохими; их нельзя считать truth source.
- Dify retrieval может отдавать похожий, но неправильный сценарий, если сценарии слишком дробные или дублируются.
- Если n8n будет брать только top-1, качество будет хуже; лучше использовать top-3/top-5 и дать LLM выбрать.

## Рекомендованный первый запуск

Сначала сделать offline enrichment без изменения Dify:

1. Inventory.
2. Episode extraction.
3. Scenario candidates.
4. Review report.

Только после этого заливать в Railway Dify.

Это даст контроль: мы увидим, сколько реально сценариев получается из 58 диалогов, какие слабые, какие нужно объединить, и не засорим Railway базу мусором.
