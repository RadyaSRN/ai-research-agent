# arxiv_search

**Trigger**: `executeWorkflow` (tool для LLM-агента)
**Active by default**: yes

## Назначение

On-demand поиск статей на arXiv по произвольному запросу (ключевые слова или `arxiv_id`). Если попадаются новые статьи, их метаданные сохраняются в `papers`, считаются embeddings и пишутся в `paper_embeddings` — чтобы последующий semantic search уже их видел.

## Входы

- `user_id` (UUID) — для логирования/атрибуции
- `query` (text) — текст запроса или Boolean-expression для arXiv API
- `arxiv_id` (text, опционально) — конкретный `id_list` для прямого lookup
- `sort_by` (enum: `relevance | lastUpdatedDate | submittedDate`, default `relevance`)
- `sort_order` (enum: `ascending | descending`, default `descending`)
- `max_results` (int, default 20)

## Выходы

Массив статей с полями `arxiv_id, title, abstract, authors, categories, published_at, url, pdf_url`. Новые статьи в БД помечаются `ingested_via='ondemand_search'`.

## Что делает по шагам

1. `Set` — собирает URL-параметры для arXiv API.
2. `HTTP Request (arxiv)` → XML-ответ.
3. `Parse XML` (Code) — та же логика парсинга Atom, что и в `arxiv_ingestion`.
4. `Insert papers` — `INSERT ... ON CONFLICT (arxiv_id) DO NOTHING RETURNING *` (новые только).
5. `IF: Has new papers?` — для новых запускает embedding-фазу.
6. `Set (text для embedding)` → `HTTP Request (embeddings)` → `Postgres (paper_embeddings)`.
7. `Code in JavaScript` — формирует единый ответ (union of existing + newly inserted).

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `telegram_agent` (tool), `mcp_server` (tool)
- **Credentials в n8n**: `postgres_main`, `openrouter_header_auth`
- **Внешние сервисы**: arXiv API, OpenRouter
- **Таблицы БД**: пишет `papers`, `paper_embeddings`
