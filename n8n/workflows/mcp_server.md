# mcp_server

**Trigger**: MCP Server Trigger (`@n8n/n8n-nodes-langchain.mcpTrigger`)
**Active by default**: yes

## Назначение

Экспонирует внешним MCP-клиентам (Claude Desktop, Cursor, любым другим MCP-совместимым агентам) два инструмента из этого воркфлоу-стека: семантический поиск по локальному корпусу `papers` и on-demand поиск на arXiv.

## Входы

- MCP tool-calls от клиента. Парамерты берутся из описания tool в n8n UI; фактически совпадают со входами вызываемых воркфлоу.

## Выходы

- `search_papers` — результаты `semantic_search_papers`
- `arxiv_search` — результаты `arxiv_search`

## Что делает по шагам

1. `MCP Server Trigger` — SSE endpoint с уникальным path (например `f91bcc69-...`).
2. `Call 'semantic_search_papers'` (toolWorkflow) — проксирует локальный семантический поиск.
3. `Call 'arxiv_search'` (toolWorkflow) — проксирует поиск на arXiv.

## Зависимости

- **Вызывает воркфлоу**: `semantic_search_papers`, `arxiv_search`
- **Вызывается из**: внешний MCP-клиент (Claude Desktop / Cursor)
- **Credentials в n8n**: (наследуются от nested воркфлоу: `postgres_main`, `openrouter_header_auth`)
- **Внешние сервисы**: наследуются

## Примечания

- Путь MCP-сервера (часть URL) — UUID в параметрах mcpTrigger. После импорта сгенерируется свой — обновить конфиг MCP-клиентов.
- Дефолтных схем безопасности нет; если хочется приватности — закрыть эндпоинт через Caddy basic-auth или rewrite.
