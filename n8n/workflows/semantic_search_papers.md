# semantic_search_papers

**Trigger**: `executeWorkflow` (tool для LLM-агента)
**Active by default**: yes

## Назначение

Семантический поиск по корпусу `papers` с помощью pgvector: считает embedding от входящего текстового запроса, делает HNSW-поиск по косинусу и возвращает top-K релевантных статей с их метаданными.

## Входы

- `query` (text) — произвольная фраза/концепция на естественном языке
- `top_k` (int, default 5)

## Выходы

Массив `{arxiv_id, title, abstract, authors, categories, published_at, url, cosine_similarity}` в порядке убывания релевантности.

## Что делает по шагам

1. `Set` — нормализует `query` и `top_k`.
2. `HTTP Request (embeddings)` — OpenRouter считает embedding запроса (`openai/text-embedding-3-small`).
3. `Code in JavaScript` — сериализует vector в pgvector-литерал.
4. `Vector Search` — `SELECT ... FROM papers p JOIN paper_embeddings pe ... ORDER BY pe.embedding <=> $1 LIMIT $top_k`.

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `telegram_agent` (tool), `mcp_server` (tool)
- **Credentials в n8n**: `postgres_main`, `openrouter_header_auth`
- **Внешние сервисы**: OpenRouter embeddings
- **Таблицы БД**: читает `papers`, `paper_embeddings`

## Примечания

Пользуется HNSW-индексом `idx_paper_embeddings_hnsw` из `postgres/schema.sql`. Для холодного старта с пустой БД работает, но возвращает пустой массив.
