# set_digest_schedule

**Trigger**: `executeWorkflow`
**Active by default**: yes

## Назначение

Создаёт или обновляет расписание daily-digest для пользователя: сохраняет `send_time` (локальное время) и `timezone` (IANA), рассчитывает `next_run_at` в UTC. Tool-ручка для LLM-агента.

## Входы

- `user_id` (UUID)
- `send_time` (TIME, формат `HH:MM` или `HH:MM:SS`)
- `timezone` (IANA, например `Europe/Moscow`)

## Выходы

- `{success: true, next_run_at, send_time, timezone}`

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `telegram_agent` (tool)
- **Credentials в n8n**: `postgres_main`
- **Таблицы БД**: пишет `digest_schedules` (UPSERT по `user_id`)

## Примечания

`next_run_at` пересчитывается Postgres-выражением из `send_time + timezone`; если время уже прошло сегодня, выбирается завтра.
