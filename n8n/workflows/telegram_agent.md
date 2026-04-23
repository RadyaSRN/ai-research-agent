# telegram_agent

**Trigger**: Telegram Trigger (`updates=['message']`)
**Active by default**: yes

## Назначение

Точка входа всего бота. Получает сообщения/команды из Telegram, проверяет пользователя в БД (регистрирует новых), маршрутизирует slash-команды в соответствующие воркфлоу и всё остальное отдаёт LLM-агенту с memory, system-prompt'ом из Langfuse и набором tool-ов, покрывающих полный CRUD over projects/ideas/digest + поиск статей + GitHub MCP.

## Входы

- Обычные Telegram-сообщения (text / commands) — автоматически берутся из update.

## Выходы

- Ответные Telegram-сообщения пользователю.
- Побочные эффекты через tools: вставки в `users/projects/ideas`, смена статусов, настройка расписания, запуск digest'а и т.д.

## Ветви роутинга (`Switch: commands or LLM`)

- `/start` → `Respond to /start` (приветственное сообщение).
- `/help` → `Respond to /help` (список команд).
- `/projects` → `Call 'list_projects'` → `Prepare projects output` → `Send projects output`.
- `/ideas` → `Call 'list_ideas'` → `Prepare ideas output` → `Send ideas output`.
- `/digest` → `Call 'daily_digest_for_user'` (вызов digest on-demand).
- всё остальное → ветка AI Agent.

## Что делает по шагам (основной LLM-путь)

1. `Telegram Trigger` → `Postgres: find user by telegram_chat_id`.
2. `IF user exists`:
   - false → `Insert user` + `Set user context (false)` (онбординг).
   - true → `Set user context (true)`.
3. `Merge` сливает ветки обратно в одну.
4. `Switch: commands or LLM` маршрутизирует по содержимому сообщения.
5. На LLM-ветке — `AI Agent` (langchain agent) с подключённым `OpenRouter Chat Model`, `Postgres Chat Memory` (история диалога в БД), системным промптом из `Get system prompt from Langfuse` и с большим списком tools:
   - `Call 'set_digest_schedule'`, `Call 'get_digest_schedule'`, `Call 'unset_digest_schedule'`
   - `Call 'update_idea_status'`, `Call 'update_project_status'`
   - `Call 'list_ideas'`, `Call 'list_projects'`
   - `Call 'add_idea'`, `Call 'add_project'`
   - `Call 'semantic_search_papers'`, `Call 'arxiv_search'`
   - `GitHub MCP Client` — внешний MCP-клиент к `github-mcp-server` (для поиска репозиториев / кода).
6. `(Maybe) Split message into smaller ones` (Code) — режет ответ агента по Telegram-лимиту 4096.
7. `Send a text message` — отправляет ответ.

## Зависимости

- **Вызывает воркфлоу**: `list_projects`, `list_ideas`, `add_idea`, `add_project`, `update_idea_status`, `update_project_status`, `semantic_search_papers`, `arxiv_search`, `set_digest_schedule`, `get_digest_schedule`, `unset_digest_schedule`, `daily_digest_for_user`
- **Вызывается из**: нет (точка входа)
- **Credentials в n8n**: `postgres_main`, `telegram_bot`, `openrouter_chat_model`, `langfuse_api`, `github_mcp` (MCP-credential к GitHub MCP — если используется)
- **Внешние сервисы**: Telegram, OpenRouter, Langfuse, GitHub MCP
- **Таблицы БД**: читает/пишет `users`; всё остальное — через nested воркфлоу

## Примечания

- System prompt хранится в Langfuse с именем `telegram_agent_system`.
- Для chat memory используется `Postgres Chat Memory` node → автоматически создаёт/читает таблицу `n8n_chat_histories` в Postgres. Миграция managed сама n8n-нодой при первом запуске.
- При смене списка tools важно одновременно обновить системный промпт в Langfuse — иначе агент не узнает о новых возможностях.
