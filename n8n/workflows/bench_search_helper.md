# bench_search_helper

**Trigger**: Webhook `POST /webhook/bench-search`
**Active by default**: no (включается только на время пересборки бенч-датасета)

## Назначение

HTTP-вход для `bench/run_semantic.py`: принимает `{query, top_k}`, прокидывает в `semantic_search_papers` и возвращает ответ nested-воркфлоу как есть. Нужен, потому что `semantic_search_papers` — это `executeWorkflowTrigger` и снаружи по HTTP напрямую не доступен.

## Входы

POST JSON body:

- `query` (text) — произвольная фраза/концепция на естественном языке
- `top_k` (int, default 5)

## Выходы

Ответ `semantic_search_papers` проксируется как есть: массив `{arxiv_id, title, abstract, authors, categories, published_at, url, cosine_similarity}` в порядке убывания релевантности (обёрнутый в payload nested-воркфлоу).

## Что делает по шагам

1. `Webhook` — принимает POST.
2. `Prepare` (Code) — извлекает `query` и `top_k` из body, подставляет `top_k = 5` по умолчанию.
3. `Call semantic_search` (Execute Workflow) — вызывает `semantic_search_papers` с подготовленными inputs.

## Зависимости

- **Вызывает воркфлоу**: `semantic_search_papers`
- **Вызывается из**: нет (HTTP webhook, дёргается извне из `bench/run_semantic.py`)
- **Credentials в n8n**: нет (вызов Execute Workflow — внутренний)
- **Внешние сервисы**: нет напрямую; все OpenRouter и Postgres вызовы идут через nested `semantic_search_papers`

## Примечания

- Активируется только на время пересборки бенч-датасета (`bench/run_semantic.py`); в остальное время держится выключенным, чтобы не плодить бесполезную точку входа.
- См. раздел "Пересборка датасета" в `bench/README.md` для сценария использования.
