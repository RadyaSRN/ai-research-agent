# relevance_score

**Trigger**: `executeWorkflow` (вызывается из `daily_digest_for_user`, `bench_relevance_wrapper`)
**Active by default**: yes

## Назначение

LLM-reranker для пары (idea, paper): вытаскивает полные метаданные из БД, подгружает system-prompt из Langfuse, прогоняет Basic LLM Chain через OpenRouter с structured output и возвращает `relevance_score` (0–10) + `reasoning` + `key_concepts_matched`. Ядро онлайн-матчинга и бенчмарка.

## Входы

- `idea_id` (UUID)
- `paper_id` (UUID или arxiv_id — см. примечание)
- `model` (OpenRouter model id, например `openai/gpt-5.4-nano`)
- `langfuse_trace_id` (hex32, опционально) — для merge с трейсом, созданным извне (используется в `bench_relevance_wrapper`)

## Выходы

JSON-объект:

```json
{
  "success": true,
  "idea_id": "...",
  "paper_id": "...",
  "idea_title": "...",
  "idea_description": "...",
  "paper_title": "...",
  "paper_abstract": "...",
  "relevance_score": 7,
  "reasoning": "...",
  "key_concepts_matched": ["..."]
}
```

## Что делает по шагам

1. `Set` — нормализует входные параметры.
2. `Get idea and paper data` — `SELECT ... FROM ideas i JOIN papers p ON p.arxiv_id=... WHERE i.id=...` (полные строки обеих сущностей).
3. `Get system prompt from Langfuse` — Langfuse node тянет production-версию prompt `relevance_score`.
4. `Compile prompt` — подставляет поля idea/paper в шаблон.
5. `Basic LLM Chain` + `OpenRouter Chat Model` + `Structured Output Parser` — делает LLM-вызов с JSON-схемой ответа.
6. `Return` — формирует итоговый JSON.

## Зависимости

- **Вызывает воркфлоу**: нет
- **Вызывается из**: `daily_digest_for_user`, `bench_relevance_wrapper`
- **Credentials в n8n**: `postgres_main`, `openrouter_chat_model` (OpenRouter Chat Model credential), `langfuse_api` (HTTP Basic Auth — public/secret keys)
- **Внешние сервисы**: Langfuse (для промпта), OpenRouter (для chat completion)
- **Таблицы БД**: читает `ideas`, `papers`

## Примечания

- Поле `langfuse_trace_id` прокидывается в run-data воркфлоу под именем, которое ждёт `n8n-langfuse-shipper` (см. `LANGFUSE_TRACE_ID_FIELD_NAME` в `docker-compose.yml` → `shipper`). Это позволяет merge'ить OTLP-трейс из shipper'а с трейсом, заранее созданным внешним скриптом (бенчмарком).
- Промпт хранится в Langfuse — версия `production` активна в данный момент. Менять промпт без бампа версии опасно: tracing history перестанет соответствовать реальному поведению.
