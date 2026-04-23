# digest_scheduler_tick

**Trigger**: Schedule (каждую минуту)
**Active by default**: yes

## Назначение

Планировщик персональных дайджестов. Раз в минуту находит в `digest_schedules` пользователей с `is_enabled=true AND next_run_at <= now()`, последовательно дергает `daily_digest_for_user` и пересчитывает `next_run_at` на следующий день в той же локальной таймзоне.

## Входы

- Внешних входов нет — cron каждую минуту.

## Выходы

- Вызовы `daily_digest_for_user` для каждого due-пользователя.
- Обновление `digest_schedules.last_run_at = now(), next_run_at = <next>`.

## Что делает по шагам

1. `Schedule Trigger` (1 минута).
2. `Get due schedules` — `SELECT user_id, send_time, timezone FROM digest_schedules WHERE is_enabled=true AND next_run_at<=now()`.
3. `IF: Has users?`
4. `Call 'daily_digest_for_user'` — для каждого юзера запускает digest flow.
5. `Update next_run_at` — пересчёт `next_run_at` на `(today|tomorrow) + send_time` в локальной TZ.

## Зависимости

- **Вызывает воркфлоу**: `daily_digest_for_user`
- **Вызывается из**: нет (cron)
- **Credentials в n8n**: `postgres_main`
- **Таблицы БД**: читает/пишет `digest_schedules`

## Примечания

Минутный cron позволяет поддерживать произвольное локальное время отправки (`HH:MM` с точностью до минуты) без заведения отдельного воркфлоу на каждого пользователя.
