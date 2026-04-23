# arxiv_ingestion

**Trigger**: Schedule (cron: каждый день в 09:10)
**Active by default**: yes

## Назначение

Ежедневный ingestion свежих arXiv-препринтов по категориям `cs.LG`, `cs.CL`, `cs.CV`, `cs.AI`. Забирает статьи, опубликованные за последние ~24 часа (submittedDate-окно), дедуплицирует по `arxiv_id`, сохраняет метаданные в `papers` и тут же считает embeddings для новых записей.

## Входы

- Внешних входов нет — триггер по расписанию.
- Параметры окна дат формируются в первом `Set` от `new Date()` в UTC.

## Выходы

- Новые строки в `papers` (поля `arxiv_id, title, abstract, authors, categories, published_at, url, pdf_url, ingested_via='scheduled'`).
- Новые строки в `paper_embeddings` (1536-dim embedding на `title + abstract`).
- Побочных эффектов за пределами БД нет.

## Что делает по шагам

1. Schedule Trigger → таймстемпы.
2. `HTTP Request` на `https://export.arxiv.org/api/query` с `search_query=(cat:cs.LG OR cat:cs.CL OR cat:cs.CV OR cat:cs.AI) AND submittedDate:"<from> TO <to>"`, `max_results=1000`.
3. `Parse XML` (Code) — аккуратный парсинг Atom-фида (namespaces, entry-блоки) в массив плоских объектов.
4. `Postgres (papers)` — `INSERT ... ON CONFLICT (arxiv_id) DO NOTHING RETURNING *`. Только реально вставленные строки проходят дальше.
5. `IF (вставилась ли новая строка)` — пропускает пустые итемы.
6. `Set (text для embedding)` — склейка `title + abstract`.
7. `HTTP Request (embeddings)` — OpenRouter `openai/text-embedding-3-small`.
8. `IF got embedding` — проверка ненулевого ответа.
9. `Postgres (paper_embeddings)` — `INSERT ... ON CONFLICT (paper_id) DO NOTHING`.

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: нет (автономный cron)
- **Credentials в n8n**: `postgres_main`, `openrouter_header_auth`
- **Внешние сервисы**: arXiv Atom API, OpenRouter embeddings
- **Таблицы БД**: пишет `papers`, `paper_embeddings`

## Примечания

- arXiv API не требует API-ключа, но капризен по rate-limit; в `embeddings_backfill` есть страховочный ретрай для пропущенных embeddings.
- Окно submittedDate формируется в UTC; при смене серверной TZ результаты не поменяются.
