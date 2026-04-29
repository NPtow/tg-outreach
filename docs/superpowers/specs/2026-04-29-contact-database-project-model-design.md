# ТЗ: проектная база контактов с общей защищенной базой

Дата: 2026-04-29  
Ветка: `feature/tg-outreach-2.0`  
Статус: design/spec, без реализации

## 1. Цель

Перестроить работу с контактами так, чтобы приложение стало не просто CSV-списком для рассылки, а управляемой базой людей для разных проектов, кампаний и агентских пайплайнов.

Ключевая продуктовая логика:

- У каждого проекта должна быть своя рабочая база контактов.
- Общая база должна хранить все известные контакты как backup/vault и не должна терять информацию.
- Данные нельзя физически удалять из общей базы.
- Контакт можно использовать в разных проектах, но проектные статусы, сегменты, заметки и результаты кампаний не должны смешиваться.
- Агентские пайплайны должны получать не только username, но и нормальную карточку контакта, историю касаний и накопленную информацию.

## 2. Текущее состояние

Сейчас контакты устроены слишком плоско:

- `Contact` хранит `project_id`, `username`, `display_name`, `company`, `role`, `custom_note`, `tags`, `batch_id`.
- `ContactBatch` хранит один импорт CSV.
- При создании кампании контакты фактически копируются в `CampaignTarget` через текстовый список.
- `CampaignTarget` хранит свои копии `username`, `display_name`, `company`, `role`, `custom_note`, но не связан с исходным `Contact`.
- У контакта нет нормального lifecycle: неизвестно, был ли он уже обработан, отвечал ли, устарел ли, почему исключен, в каких проектах использовался.
- Удаление батча/контактов сейчас может физически удалить данные.

Главная проблема: система не накапливает знание о людях и не умеет надежно переиспользовать контакты между проектами.

## 3. Целевая модель

Нужны три уровня данных.

### 3.1. `GlobalContact`

Глобальная вечная карточка человека. Это backup/vault.

Назначение:

- хранить идентичность человека;
- хранить все известные источники и алиасы;
- защищать данные от потери;
- находить дубли;
- предупреждать, если контакт уже использовался раньше.

Минимальные поля:

- `id`
- `tg_user_id`
- `tg_username_normalized`
- `display_name`
- `first_name`
- `last_name`
- `company`
- `role`
- `bio`
- `linkedin_url`
- `email`
- `phone`
- `source_type`
- `source_label`
- `source_url`
- `identity_confidence`
- `data_quality`
- `global_status`
- `created_at`
- `updated_at`
- `archived_at`

Статусы `global_status`:

- `active`
- `needs_review`
- `duplicate`
- `stale`
- `do_not_contact`
- `archived`

Физического удаления из `GlobalContact` быть не должно.

### 3.2. `ProjectContact`

Рабочая версия контакта внутри конкретного проекта.

Назначение:

- хранить проектную релевантность;
- хранить сегменты и фильтры;
- отделять проектные заметки от глобальной истории;
- управлять тем, участвует ли контакт в проекте.

Минимальные поля:

- `id`
- `project_id`
- `global_contact_id`
- `project_display_name`
- `project_company`
- `project_role`
- `project_note`
- `persona`
- `tags`
- `fit_status`
- `contact_status`
- `last_contacted_at`
- `last_replied_at`
- `last_campaign_id`
- `created_at`
- `updated_at`
- `hidden_at`

Статусы `fit_status`:

- `unknown`
- `target`
- `low_fit`
- `excluded`

Статусы `contact_status`:

- `new`
- `ready`
- `queued`
- `contacted`
- `replied`
- `interested`
- `booked`
- `no_reply`
- `stale`
- `do_not_contact`
- `hidden`

Важно: `ProjectContact` можно скрыть из проекта, но это не удаляет `GlobalContact`.

### 3.3. `CampaignLead`

Контакт внутри конкретной кампании.

Назначение:

- фиксировать снимок контакта на момент запуска кампании;
- хранить статус рассылки;
- не ломать историю, если карточка контакта позже изменилась;
- отдавать агенту контекст конкретной кампании.

Текущий `CampaignTarget` нужно эволюционно расширить, не ломая старую логику.

Добавить поля:

- `global_contact_id`
- `project_contact_id`
- `snapshot_json`
- `reply_status`
- `last_inbound_at`
- `last_outbound_at`
- `conversation_id`
- `excluded_reason`
- `updated_at`

Расширить статусы:

- `pending`
- `queued`
- `sent`
- `replied`
- `interested`
- `booked`
- `no_reply`
- `failed`
- `skipped`
- `excluded`

## 4. Дополнительные сущности

### 4.1. `ContactImportBatch`

Можно оставить текущий `ContactBatch`, но изменить смысл: это источник импорта, а не владелец контактов.

Новые поля:

- `status`: `active | archived`
- `source_file_name`
- `import_summary_json`
- `created_by`
- `archived_at`

Удаление батча в UI должно архивировать батч, а не удалять контакты.

### 4.2. `ContactEvent`

История всех важных событий по контакту.

Поля:

- `id`
- `global_contact_id`
- `project_contact_id`
- `campaign_id`
- `conversation_id`
- `event_type`
- `payload_json`
- `created_at`

Примеры `event_type`:

- `imported`
- `merged_duplicate`
- `added_to_project`
- `selected_for_campaign`
- `message_sent`
- `message_replied`
- `classified_interested`
- `meeting_booked`
- `marked_no_reply`
- `marked_stale`
- `marked_do_not_contact`
- `manual_note_added`
- `agent_summary_updated`

### 4.3. `ContactIntelligence`

Накопленная агентская память по человеку внутри проекта.

Поля:

- `id`
- `project_contact_id`
- `summary`
- `known_facts_json`
- `objections_json`
- `last_intent`
- `next_best_action`
- `confidence`
- `updated_by`
- `updated_at`

Правило: LLM не должен напрямую менять произвольные поля контакта. Он может предлагать structured update, а backend применяет только разрешенные изменения.

## 5. Правила хранения и удаления

Главное правило: физическое удаление запрещено для всего, что может понадобиться для истории, дедупликации или восстановления.

Разрешено:

- скрыть контакт из проекта;
- архивировать импорт;
- пометить контакт как `stale`;
- пометить контакт как `duplicate`;
- пометить контакт как `do_not_contact`;
- исключить контакт из кампании;
- удалить черновик кампании, если по нему не было отправок.

Запрещено:

- удалять `GlobalContact`;
- удалять историю событий;
- удалять conversation/message history;
- удалять campaign lead, если по нему была отправка;
- удалять batch вместе с контактами.

Для UI кнопка `Удалить` должна быть переименована:

- для контакта: `Скрыть из проекта`;
- для батча: `Архивировать импорт`;
- для глобального blacklist: `Не писать этому контакту`.

## 6. Дедупликация

При импорте система должна сначала искать существующий `GlobalContact`.

Приоритеты идентификации:

1. `tg_user_id`, если известен.
2. Нормализованный Telegram username.
3. LinkedIn URL, если есть.
4. Email, если есть.
5. Ручное объединение через `needs_review`, если совпадение неуверенное.

Нормализация Telegram username:

- убрать `@`;
- привести к lowercase;
- убрать пробелы;
- хранить исходное отображение отдельно, если нужно.

Если найден дубль:

- не создавать новый `GlobalContact`;
- создать или обновить `ProjectContact`;
- добавить `ContactEvent: imported`;
- сохранить новый источник в историю.

## 7. UX контактов

Целевая страница `Contacts` должна перестать быть списком батчей как основным экраном.

### 7.1. Основные вкладки

1. `Project Contacts`

Рабочая база текущего проекта. Основной экран.

2. `Segments`

Сохраненные фильтры для кампаний.

3. `Imports`

История CSV/ручных импортов. Нужна для контроля источников, но не как главный способ работы.

4. `Needs Review`

Дубли, плохие данные, пустые имена, спорная релевантность.

5. `Global Vault`

Общая база. По умолчанию read-only, с возможностью добавить контакт в текущий проект.

### 7.2. Основная таблица проекта

Колонки первой версии:

- Contact
- Username
- Company / Role
- Segment / Tags
- Fit
- Status
- Last touch
- Campaign history
- Data quality

Фильтры первой версии:

- search
- status
- fit
- tags
- company
- role
- source/import batch
- contacted / not contacted
- replied / no reply
- stale
- do not contact
- used in another project

### 7.3. Карточка контакта

При клике открывается drawer/modal.

Секции:

- Identity: username, имя, компания, роль, контакты.
- Project profile: сегмент, fit, project note, status.
- Outreach history: кампании, отправки, ответы, встречи.
- Agent memory: summary, known facts, objections, next action.
- Sources: откуда контакт появился.
- Safety: do-not-contact, duplicate, stale.

История из других проектов:

- по умолчанию показывать предупреждение: `Этот контакт уже использовался в другом проекте`.
- полную историю открывать вручную отдельной кнопкой.
- это снижает риск смешивания контекста разных проектов.

## 8. Связь с кампаниями

Создание кампании должно работать не через вставку текстового списка, а через выбор сегмента или контактов.

Новый flow:

1. Пользователь выбирает проект.
2. Открывает кампанию.
3. Выбирает saved segment или вручную отмечает контакты.
4. Система показывает preview:
   - всего контактов;
   - исключено из-за `do_not_contact`;
   - уже использовались в этом проекте;
   - уже использовались в другом проекте;
   - нет username;
   - низкое качество данных.
5. При создании кампании система создает `CampaignLead`/расширенный `CampaignTarget`.
6. В `snapshot_json` сохраняется карточка контакта на момент старта.
7. После отправки и ответов статусы обновляют `CampaignLead`, `ProjectContact`, `ContactEvent`, `ContactIntelligence`.

## 9. Связь с агентским пайплайном

Auto-reply/n8n/Dify pipeline должен получать нормальный `contact_card`.

Минимальный payload:

```json
{
  "contact": {
    "global_contact_id": 1,
    "project_contact_id": 10,
    "username": "example",
    "display_name": "Иван",
    "company": "Company",
    "role": "HRD",
    "persona": "hrd",
    "tags": ["target", "hr"],
    "project_note": "нашли в HR-чате",
    "known_facts": [],
    "objections": [],
    "last_intent": "trust_question",
    "next_best_action": "answer_short_and_offer_call",
    "campaign_history": [
      {
        "campaign_id": 5,
        "status": "sent",
        "sent_at": "2026-04-29T10:00:00Z"
      }
    ]
  }
}
```

Агент может:

- использовать карточку для персонализации;
- не повторять уже сказанные аргументы;
- учитывать возражения;
- предлагать обновления памяти.

Агент не может:

- сам удалять контакт;
- сам ставить `do_not_contact` без backend policy;
- сам менять глобальную идентичность контакта;
- смешивать историю разных проектов без явного разрешения.

## 10. API

Новые или измененные endpoints:

- `GET /api/contacts/project`
- `GET /api/contacts/global`
- `GET /api/contacts/{project_contact_id}`
- `POST /api/contacts/import`
- `POST /api/contacts/{global_contact_id}/add-to-project`
- `PATCH /api/contacts/project/{project_contact_id}`
- `POST /api/contacts/project/{project_contact_id}/hide`
- `POST /api/contacts/project/{project_contact_id}/mark-stale`
- `POST /api/contacts/project/{project_contact_id}/do-not-contact`
- `GET /api/contacts/project/{project_contact_id}/events`
- `GET /api/contacts/segments`
- `POST /api/contacts/segments`
- `POST /api/campaigns/from-segment`

Совместимость:

- старые `/api/contacts/` и `/api/contacts/batches/` можно временно оставить;
- старый импорт должен создавать новые сущности под капотом;
- старый `CampaignTarget` должен продолжить работать, пока UI не переведен полностью.

## 11. Миграция данных

Миграция должна быть мягкой и обратимой на уровне данных.

Этапы:

1. Создать новые таблицы без удаления старых.
2. Для каждого текущего `Contact` создать или найти `GlobalContact`.
3. Для каждого текущего `Contact` создать `ProjectContact`.
4. Сохранить связь со старым `contact.id` в служебном поле или migration map.
5. Для каждого `CampaignTarget` попробовать связать `global_contact_id` и `project_contact_id` по username и project/campaign.
6. Старые поля `username`, `display_name`, `company`, `role`, `custom_note` оставить как snapshot/compat.
7. Физические delete endpoints заменить на archive/hide.

Перед миграцией:

- сделать backup Railway DB;
- прогнать dry-run локально;
- вывести отчет:
  - сколько contacts;
  - сколько global_contacts создано;
  - сколько дублей объединено;
  - сколько contacts требует review;
  - сколько campaign_targets удалось связать.

## 12. Этапы реализации

### Этап 1. Data foundation

Сделать новые модели, миграцию и backend-сервисы:

- `GlobalContact`
- `ProjectContact`
- `ContactEvent`
- `ContactIntelligence`
- расширение `CampaignTarget`
- soft-delete/archive logic
- dedupe service

Результат: данные безопасно хранятся в новой модели, старый UI еще может работать.

### Этап 2. Import and dedupe

Перевести импорт:

- CSV импорт создает global + project contacts;
- batch архивируется, но не удаляет контакты;
- дубли не создаются повторно;
- спорные дубли попадают в `Needs Review`.

Результат: новые импорты уже не ломают базу.

### Этап 3. Contacts UX

Переделать страницу контактов:

- основной экран project contacts;
- imports как вторичная вкладка;
- global vault read-only;
- drawer контакта;
- базовые фильтры;
- hide/archive вместо delete.

Результат: пользователь работает с базой, а не с CSV-батчами.

### Этап 4. Campaign selection

Переделать выбор аудитории кампании:

- выбор контактов из project contacts;
- выбор segment;
- preview исключений;
- создание campaign leads со snapshot.

Результат: кампания больше не теряет связь с исходными контактами.

### Этап 5. Feedback loop

Связать отправки, ответы и агентские решения с базой:

- при отправке обновлять `CampaignLead` и `ProjectContact`;
- при ответе писать `ContactEvent`;
- при классификации ответа обновлять `ContactIntelligence`;
- при no reply после заданного срока ставить `no_reply` или `stale`.

Результат: база сама становится умнее после каждой кампании.

### Этап 6. Agent payload

Расширить payload для n8n/Dify:

- добавить `contact_card`;
- добавить campaign history;
- добавить known facts/objections;
- добавить запрет на повторение старых аргументов.

Результат: агент отвечает персональнее и меньше повторяется.

## 13. Тестирование

Минимальные backend tests:

- импорт нового контакта создает `GlobalContact` и `ProjectContact`;
- повторный импорт username не создает дубль `GlobalContact`;
- один global contact может быть в двух проектах;
- скрытие контакта в проекте не удаляет global contact;
- архивирование batch не удаляет contacts;
- создание кампании из project contacts сохраняет snapshot;
- do-not-contact исключает контакт из кампании;
- campaign reply обновляет lead/project contact/event.

Минимальные UI checks:

- можно импортировать CSV;
- можно увидеть контакт в проектной базе;
- можно открыть карточку контакта;
- можно скрыть контакт из проекта;
- можно увидеть global vault;
- можно создать кампанию из выбранных контактов;
- preview показывает исключения.

Миграционные проверки:

- количество исходных contacts не потеряно;
- все старые contacts имеют project contact;
- все campaign targets остались доступны;
- физические delete операции больше не удаляют исторические данные.

## 14. Rollout

Порядок безопасного внедрения:

1. Реализовать и протестировать локально.
2. Прогнать миграцию на локальной копии данных.
3. Поднять на staging branch/Railway 2.0.
4. Синкнуть копию контактов на staging.
5. Прогнать импорт, кампанию и auto-reply на тестовом проекте.
6. Проверить, что production не тронут.
7. После подтверждения перенести в production отдельным деплоем.

## 15. Acceptance criteria

Фича считается готовой, если:

- у проекта есть своя рабочая база контактов;
- общая база хранит все контакты и не удаляется;
- один контакт можно переиспользовать между проектами;
- проектные статусы не смешиваются между проектами;
- батчи можно архивировать без потери контактов;
- кампания создается из project contacts/segments, а не только из сырого текста;
- campaign lead связан с contact и хранит snapshot;
- auto-reply получает contact card;
- после ответов база обновляет статус и историю;
- delete в UI больше не делает физическое удаление ценных данных.

## 16. Не входит в первую реализацию

- полноценный внешний CRM;
- сложный lead scoring;
- автоматическое обогащение из LinkedIn/внешних источников;
- визуальный graph связей контактов;
- массовая AI-нормализация всех старых контактов;
- автоматическое слияние рискованных дублей без ручного review.

## 17. Главный принцип

Контакты должны быть устроены как долговременный актив.

Проект управляет рабочей выборкой. Общая база защищает память системы. Кампания фиксирует конкретное касание. Агент использует эту память, но не имеет права разрушать или произвольно переписывать базу.
