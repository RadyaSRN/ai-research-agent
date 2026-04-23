# alerts_cost_guard

**Trigger**: Schedule (каждые 15 минут)
**Active by default**: yes

## Назначение

Следит за стоимостью LLM-вызовов (Langfuse metrics) и шлёт Telegram-алерт админу, если цена за 1 час или за 24 часа превысила порог. Дедуп реализован через таблицу `alert_buckets` (`ON CONFLICT DO NOTHING RETURNING`): один алерт на bucket, независимо от того, сколько раз cron его обнаружит.

## Входы

- Внешних входов нет — cron.
- Пороги (USD) и chat_id зашиты в ноды `Set / Format ... msg` и `Send ... alert`.

## Выходы

- Telegram-сообщения админу при превышении порога.
- Строки в `alert_buckets` (`alert_key='cost_hourly|cost_daily'`, `bucket_id=<timestamp>`, `cost_value`, `threshold_value`).

## Что делает по шагам

1. `Schedule Trigger` (15 мин).
2. `Timestamps` — считает границы текущего часового и суточного бакета.
3. Параллельная ветка 1-часовая:
   - `Langfuse cost 1h` — GET `/api/public/metrics/daily` (или аналог) с сужением до 1h.
   - `Sum cost 1h` (Code) — сумма по всем observations.
   - `IF hourly over threshold` — сравнение с порогом.
   - `Claim hourly bucket` — `INSERT INTO alert_buckets ... ON CONFLICT DO NOTHING RETURNING *`; проходит дальше, только если строка реально вставилась.
   - `Format hourly msg` → `Send hourly alert` (Telegram).
4. Ветка 24-часовая — идентично, другой порог и bucket_id (сутки).

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: нет (cron)
- **Credentials в n8n**: `postgres_main`, `telegram_bot`, `langfuse_api` (HTTP Basic с public/secret)
- **Внешние сервисы**: Langfuse metrics API, Telegram Bot API
- **Таблицы БД**: пишет `alert_buckets`

## Примечания

- Критично держать эту активной, чтобы не проспать бесконтрольный расход на LLM.
- `alert_buckets` — простая idempotency-таблица; запись-семафор вставлена через `ON CONFLICT DO NOTHING RETURNING` — отсутствие возвращённой строки означает «уже слали».
