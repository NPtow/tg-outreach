# Test plan: Railway Dify knowledge enrichment

Дата: 2026-04-28

## Цель тестирования

Проверить, что база в Railway Dify помогает агенту отвечать лучше, а не просто содержит больше текста.

## Уровни проверки

### 1. Source integrity

Проверяем:

- оба export файла читаются;
- полный экспорт содержит `58` conversations;
- summary содержит `58` items;
- у каждого conversation есть id, messages, stats;
- роли сообщений распознаны как `assistant` / `user`.

Команда:

```bash
python scripts/dify_enrichment/analyze_export.py \
  --full /Users/NIKITA/Desktop/JJFR/artifacts/prod-conversations/prod_replied_conversations_20260428T125313Z.json \
  --summary /Users/NIKITA/Desktop/JJFR/artifacts/prod-conversations/prod_replied_conversations_20260428T125313Z_summary.json \
  --out artifacts/dify-enrichment/2026-04-28
```

Acceptance:

- обработано ровно `58` диалогов;
- errors: `0`;
- нет пустых message arrays.

### 2. Episode extraction

Проверяем:

- из диалогов выделены отдельные эпизоды;
- один эпизод содержит конкретную ситуацию, а не весь диалог;
- история ограничена релевантными последними сообщениями;
- первое outreach сообщение не загрязняет все сценарии.

Acceptance:

- примерно `80-140` episodes;
- каждый episode имеет `stage`, `last_user_message`, `assistant_reply`, `source_conversation_id`;
- нет дублей с одинаковым `last_user_message + assistant_reply`.

### 3. Classification quality

Проверяем:

- каждый эпизод попадает в одну из групп;
- сценарии не дублируют друг друга;
- weak/unclear cases помечены как review, а не active.

Acceptance:

- минимум `90%` эпизодов классифицированы;
- active scenarios имеют confidence не ниже agreed threshold;
- дубли слиты.

### 4. Privacy and safety

Проверяем:

- Dify documents не содержат tg_username;
- Dify documents не содержат tg_user_id;
- имена людей удалены или заменены, если они не нужны для смысла;
- нет секретов, API ключей, токенов, внутренних URL кроме разрешенных source labels.

Команда:

```bash
python scripts/dify_enrichment/check_privacy.py \
  --docs artifacts/dify-enrichment/2026-04-28/dify_documents
```

Acceptance:

- privacy scanner returns `0` critical findings.

### 5. Dify upload/indexing

Проверяем:

- документы созданы или обновлены в Railway Dify;
- каждому документу соответствует Dify document id;
- indexing completed;
- display_status available.

Acceptance:

- upload failed: `0`;
- indexing failed: `0`;
- все active документы available.

### 6. Retrieval smoke

Проверяем top-3 retrieval на реальных вопросах:

- `А мне это зачем?`
- `А компании это зачем?`
- `Это бот?`
- `Откуда у вас мой контакт?`
- `Что за проект?`
- `Какие гипотезы проверяете?`
- `Это продажа?`
- `Я рекрутер для кастдевов. Не для персонала`
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

Acceptance:

- минимум `85%` запросов имеют правильный scenario/example в top-3;
- bot/link/refusal кейсы возвращают avoid rule или negative pattern;
- нет критически неправильного top-1 для high-risk кейсов.

### 7. Agent dry run

Проверяем итоговый ответ агента с retrieved docs.

Cases:

- qualification question;
- trust question;
- bot question;
- scheduling with concrete slots;
- link problem;
- refusal;
- paid consultation;
- website/commercial request;
- already booked slot;
- short courtesy closing.

Acceptance:

- ответ без приветствия;
- 1-3 предложения, если не требуется длинный ответ;
- нет выдуманных фактов;
- нет обещания готового продукта;
- нет дожима после отказа;
- нет повторной ссылки после проблемы со ссылкой;
- если собеседник предложил слот, агент не переключается на Calendly без причины.

### 8. Regression gate

Проверяем, что новая база не ломает уже работающие сценарии:

- текущие 15 активных сценариев либо сохранены, либо осознанно заменены;
- старые рабочие retrieval smoke queries продолжают проходить;
- n8n может получить Dify answer/retrieval без 400.

Known Dify API detail:

- если передается custom `retrieval_model`, нужно указывать `reranking_enable`;
- иначе Dify возвращает `400 invalid_param`.

Acceptance:

- no 400 from Dify retrieve;
- top-3 retrieval работает с n8n payload.

## Release gate

Можно считать базу готовой к подключению в n8n, если:

- source integrity passed;
- privacy check passed;
- Dify indexing passed;
- retrieval smoke >= `85%`;
- agent dry run не показывает critical failures;
- есть `active_manifest.json` и `rollback_manifest.json`.

## Последний локальный прогон

Дата: 2026-04-28.

Команды:

```bash
python3 -m scripts.dify_enrichment.analyze_export --full /Users/NIKITA/Desktop/JJFR/artifacts/prod-conversations/prod_replied_conversations_20260428T125313Z.json --summary /Users/NIKITA/Desktop/JJFR/artifacts/prod-conversations/prod_replied_conversations_20260428T125313Z_summary.json --out artifacts/dify-enrichment/2026-04-28
python3 -m scripts.dify_enrichment.extract_episodes --full /Users/NIKITA/Desktop/JJFR/artifacts/prod-conversations/prod_replied_conversations_20260428T125313Z.json --inventory artifacts/dify-enrichment/2026-04-28/conversation_inventory.json --out artifacts/dify-enrichment/2026-04-28/episodes.jsonl
python3 -m scripts.dify_enrichment.classify_episodes --episodes artifacts/dify-enrichment/2026-04-28/episodes.jsonl --out artifacts/dify-enrichment/2026-04-28/scenario_candidates.json
python3 -m scripts.dify_enrichment.build_dify_documents --candidates artifacts/dify-enrichment/2026-04-28/scenario_candidates.json --episodes artifacts/dify-enrichment/2026-04-28/episodes.jsonl --out artifacts/dify-enrichment/2026-04-28/dify_documents --manifest artifacts/dify-enrichment/2026-04-28/manifest.json
python3 -m scripts.dify_enrichment.prepare_review --manifest artifacts/dify-enrichment/2026-04-28/manifest.json --candidates artifacts/dify-enrichment/2026-04-28/scenario_candidates.json --out artifacts/dify-enrichment/2026-04-28/review_report.md
python3 -m scripts.dify_enrichment.check_privacy --docs artifacts/dify-enrichment/2026-04-28/dify_documents --out artifacts/dify-enrichment/2026-04-28/privacy_report.json
```

Результат:

- conversations: `58`;
- episodes: `122`;
- unknown episodes: `0`;
- scenario cards: `25`;
- conversation examples: `69`;
- negative patterns: `6`;
- eval cases: `45`;
- generated Dify docs: `149`;
- privacy critical findings: `0`;
- scenarios requiring review: `7`.

Regression:

```bash
python3 tests/test_dify_enrichment.py
python3 -m compileall -q scripts/dify_enrichment
```

Обе проверки прошли.

## Что не проверяем в этом этапе

- Полную production отправку сообщений в Telegram.
- Автоматическое создание встреч в календаре.
- Полный eval harness с LLM judge.

Эти проверки нужны позже, когда n8n flow будет стабилен.
