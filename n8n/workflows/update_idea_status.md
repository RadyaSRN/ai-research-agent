# update_idea_status

**Trigger**: `executeWorkflow`
**Active by default**: yes

## Назначение

Меняет поле `status` у идеи (`active` / `paused` / `done` / `dropped`). Tool-ручка для LLM-агента. Проверяет принадлежность идеи пользователю (`user_id`), чтобы исключить кросс-юзерные правки.

## Входы

- `user_id` (UUID)
- `idea_id` (UUID)
- `new_status` (enum: `active | paused | done | dropped`)

## Выходы

- При успехе: `{success: true, idea_id, new_status}`
- При ненайденной/чужой идее: `{success: false, error: "not found"}`

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `telegram_agent` (tool)
- **Credentials в n8n**: `postgres_main`
- **Таблицы БД**: пишет `ideas`

## Примечания

CHECK constraint в схеме ограничивает набор допустимых статусов — агенту обязательно нужно передавать строго одно из четырёх значений.
