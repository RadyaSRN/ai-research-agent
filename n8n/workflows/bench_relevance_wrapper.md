# bench_relevance_wrapper

**Trigger**: Webhook `POST /webhook/bench-relevance`
**Active by default**: yes

## Назначение

HTTP-вход для бенчмарка (`bench/run_bench.py`): принимает `{idea_id, paper_id, model, trace_id}`, достаёт из тела `trace_id`, прокидывает его в вызываемый `relevance_score` под именем `langfuse_trace_id` — чтобы OTLP-трейс, собираемый `n8n-langfuse-shipper`, слился с трейсом, заранее созданным скриптом напрямую в Langfuse API.

## Входы

POST JSON body:

- `idea_id` (UUID)
- `paper_id` (UUID)
- `model` (OpenRouter model id, default `openai/gpt-5.4-nano`)
- `trace_id` (hex32) — внешне сгенерированный Langfuse trace id

## Выходы

Ответ `relevance_score` проксируется как есть: `{success, idea_id, paper_id, relevance_score, reasoning, key_concepts_matched, ...}`.

## Что делает по шагам

1. `Webhook` — принимает POST.
2. `Prepare` (Code) — `body.trace_id → langfuse_trace_id`, подставляет default для `model`.
3. `Call relevance_score` (Execute Workflow) — явно передаёт все поля, включая `langfuse_trace_id`, в inputs nested-воркфлоу.

## Зависимости

- **Вызывает воркфлоу**: `relevance_score`
- **Вызывается из**: нет (HTTP webhook, дергается извне из `bench/run_bench.py`)
- **Credentials в n8n**: нет (вызов Execute Workflow — внутренний)
- **Внешние сервисы**: нет напрямую; все LLM-вызовы идут через nested `relevance_score`

## Примечания

- Критично, чтобы схема `relevance_score`'s `When Executed by Another Workflow` включала поле `langfuse_trace_id` в inputs — иначе значение не пролетит и shipper не сможет склеить трейсы.
- Полная картина race-condition-фикса (preflight trace-create в bench-скрипте + `LANGFUSE_TRACE_ID_FIELD_NAME` в shipper'е) описана в `bench/README.md`.
