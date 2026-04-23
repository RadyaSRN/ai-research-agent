# update_project_status

**Trigger**: `executeWorkflow`
**Active by default**: yes

## Назначение

Меняет поле `status` у проекта (`active` / `paused` / `archived`). Tool-ручка для LLM-агента, аналогична `update_idea_status`, но для таблицы `projects`.

## Входы

- `user_id` (UUID)
- `project_id` (UUID)
- `new_status` (enum: `active | paused | archived`)

## Выходы

- Успех: `{success: true, project_id, new_status}`
- Ненайденный/чужой проект: `{success: false, error: "not found"}`

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `telegram_agent` (tool)
- **Credentials в n8n**: `postgres_main`
- **Таблицы БД**: пишет `projects`
