# Test Plan — Railway Deployment

## Smoke checks (после каждого деплоя)

| Проверка | Как проверить | Pass |
|---|---|---|
| Frontend грузится | Открыть `https://tg-outreach-production.up.railway.app` | UI виден |
| API отвечает | `curl https://...railway.app/api/accounts` → JSON | 200, не 502 |
| Worker стартовал | Логи worker-сервиса → нет hanging > 60с | Строки с account connect |
| Аккаунты в UI | Вкладка Accounts → список аккаунтов, статусы | Отображаются |
| Auto-reply | Написать в TG аккаунту → получить ответ AI | Ответ пришёл |

## Negative cases
| Сценарий | Ожидание |
|---|---|
| Мёртвый прокси у аккаунта | Таймаут 30с, статус `degraded`, не зависает |
| Worker недоступен | Web-сервис возвращает 503, не крашится |
| Неверный OpenAI ключ | Auto-reply не отвечает, ошибка в логах |

## Release gates
- [ ] Web deployment successful в Railway dashboard
- [ ] Worker deployment successful в Railway dashboard
- [ ] Нет ERROR уровня в web-логах при старте
- [ ] Нет hanging в worker-логах при старте
- [ ] Frontend открывается по production URL
