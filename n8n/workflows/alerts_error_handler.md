# alerts_error_handler

**Trigger**: Error Trigger (n8n global error workflow)
**Active by default**: yes

## Назначение

Глобальный error handler. Привязывается в `Settings → Error Workflow` к остальным воркфлоу (или в конкретных воркфлоу через `Settings → Error Workflow`), чтобы любой необработанный exception улетал в Telegram админу с деталями: имя воркфлоу, execution_id, ссылка в UI, stacktrace (короткий).

## Входы

- Приходит стандартный payload от n8n Error Trigger: `execution.id`, `execution.url`, `workflow.name`, `error.message`, `error.stack`, ....

## Выходы

- Одно Telegram-сообщение админу.

## Что делает по шагам

1. `Error Trigger` ловит падение.
2. `Set` — собирает короткое сообщение (с обрезкой stacktrace по длине).
3. `Send alert about failed workflow` — Telegram sendMessage админу.

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: Как Error Workflow — из любого воркфлоу, в настройках которого он указан.
- **Credentials в n8n**: `telegram_bot`
- **Внешние сервисы**: Telegram Bot API

## Примечания

Прикрепить этот воркфлоу как error workflow ко всем production-воркфлоу через `Workflow Settings → Error Workflow`. Без этого воркфлоу падения будут молчать.
