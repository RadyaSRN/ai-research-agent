# bench — оффлайн-бенчмарк `relevance_score`

Эта папка содержит всё необходимое, чтобы:

1. собрать фиксированный датасет `relevance_score_bench` в Langfuse (20 пар идея↔статья);
2. прогнать на нём один или несколько LLM (любую модель, доступную в OpenRouter);
3. посмотреть результаты в Langfuse → Datasets → `relevance_score_bench` → **Compare runs**.

Для оценки качества используется LLM-as-a-Judge эвалуатор `relevance_score_judge_traces`, сконфигурированный в Langfuse на режим **Experiments** с фильтром `Dataset = relevance_score_bench`. Он автоматически скорит каждый новый experiment (dataset run).

## Что лежит в папке

| Файл | Назначение |
|---|---|
| `create_dataset.py` | Одноразовая настройка датасета в Langfuse (создаёт `relevance_score_bench`, подгружает 20 item'ов из JSON, обогащает данными из Postgres). |
| `run_bench.py` | Главный драйвер. Прогоняет одну модель по всем item'ам датасета, создаёт trace'ы в Langfuse и линкует их к dataset run'у. |
| `final_20_pairs.json` | Снимок курированных пар (idea_id + arxiv_id + rank). Основа датасета. |
| `run_semantic.py` | Вспомогательная утилита: для каждой идеи ре-выполняет `semantic_search_papers` и печатает top-10. Нужна только при пересборке датасета. |

## Зависимости вне этой папки

### Переменные окружения

Читаются из `.env` в корне репозитория (`<repo-root>/.env`):

- `N8N_HOST` — хост n8n (без схемы допустим, будет добавлен `https://`);
- `LANGFUSE_HOST` — хост Langfuse;
- `LANGFUSE_PUBLIC_KEY` — `pk-lf-...`;
- `LANGFUSE_SECRET_KEY` — `sk-lf-...`.

### n8n-воркфлоу, которые должны быть активны

- **`relevance_score`** — рабочий воркфлоу, который мы бенчмаркаем. Принимает `idea_id`, `paper_id`, `model`. Если `model` не передан, по умолчанию использует `openai/gpt-5.4-nano` (прод-модель).
- **`bench_relevance_wrapper`** — webhook-обёртка, через которую `run_bench.py` стучится в `relevance_score`. Путь webhook'а: `POST /webhook/bench-relevance`.
- **`semantic_search_papers`** + **`bench_search_helper`** — нужны только если планируешь пересобирать датасет через `run_semantic.py`. Путь webhook'а второго: `POST /webhook/bench-search`.
- **`arxiv_search`** — используется косвенно, если нужно подгрузить в корпус новые статьи перед пересборкой датасета.

### Langfuse-настройки

- Датасет `relevance_score_bench` (создаётся `create_dataset.py`).
- Эвалуатор `relevance_score_judge_traces`:
  - **Run on**: `Experiments`;
  - **Filter**: `Dataset = relevance_score_bench`;
  - **Sampling**: 100%;
  - **Variable mapping**: `{{output}}` → Object `Trace`, Object Field `Output`;
  - **Run on new experiments**: ON.

Важно: эвалуатор **не делает backfill** по уже завершённым run'ам. Если его создали позже, чем сделали прогон, по прошлым run'ам скоров не будет — их нужно пере-прогнать заново.

## Quick start

Все команды в документации даются относительно корня репозитория и запускаются **из него**. Python 3.10+, только stdlib, никаких pip-зависимостей не нужно. Корень репозитория скрипты находят сами через `Path(__file__).resolve().parent.parent`, поэтому клонировать можно куда угодно.

### Первичная настройка (один раз)

```bash
python3 bench/create_dataset.py
```

Скрипт создаст датасет в Langfuse (игнорируется, если уже есть), потом зальёт 20 item'ов, подтягивая свежие `title/description/abstract` из Postgres через `docker compose exec postgres psql`. Требует, чтобы все 20 `arxiv_id` из `final_20_pairs.json` уже лежали в таблице `papers` с проставленными embedding'ами.

### Прогон бенчмарка

Один прогон = одна модель:

```bash
python3 bench/run_bench.py --model openai/gpt-5.4-nano
python3 bench/run_bench.py --model anthropic/claude-haiku-4.5
python3 bench/run_bench.py --model google/gemini-3-flash-preview
```

Имя run'а генерируется автоматически: `<model-slug>-<YYYYMMDD>-<4hex>`. Можно задать вручную:

```bash
python3 bench/run_bench.py --model openai/gpt-5.4-nano --run-name gpt-nano-prod-prompt-v3
```

Для быстрой отладки — обрезать по количеству item'ов:

```bash
python3 bench/run_bench.py --model openai/gpt-5.4-nano --limit 3
```

### Как смотреть результаты

1. Открыть **Langfuse → Datasets → `relevance_score_bench` → Compare runs**.
2. Выбрать интересующие run'ы (до 3-4 одновременно, интерфейс становится неудобным при бóльшем количестве).
3. Каждая ячейка = один dataset-run-item: виден `input`, raw output от модели, latency/cost и **score от `relevance_score_judge_traces`** (0..1; выше — ближе к "хорошо откалиброван").
4. Вкладка **Charts** даст агрегаты (mean score, p50/p95 latency, cost).

### Когда пере-прогонять

- Поменялся промпт `relevance_score` (в Langfuse Prompt Management или в самом воркфлоу).
- Меняется дефолтная прод-модель.
- Появились новые идеи или статьи → пересобрать датасет (см. ниже).
- Хочется сравнить новую модель OpenRouter со старыми.

## Пересборка датасета

Делается редко; шаги вкратце:

1. При необходимости докинуть статей в корпус через воркфлоу `arxiv_search` (по `arxiv_id` или `query`).
2. Руками обновить `final_20_pairs.json` — либо взять top-5 `semantic_search_papers` для новых идей, либо курировать вручную.
3. (Опционально) Проверить через `python3 bench/run_semantic.py`, что корпус содержит ожидаемые статьи.
4. Удалить старые item'ы датасета в Langfuse UI (если структура поменялась) или менять имя датасета в константе `_DATASET_NAME` и перегенерировать.
5. `python3 bench/create_dataset.py`.
6. Пере-прогнать `run_bench.py` для всех моделей.

## Troubleshooting

| Симптом | Причина и что делать |
|---|---|
| `ERROR: missing required env variable: LANGFUSE_HOST` | Не прочитан `.env` в корне репозитория. Убедись, что файл существует (`<repo-root>/.env`) и в нём есть нужные ключи. |
| `non-JSON response from Langfuse (...)` | Неверные ключи Langfuse, либо ответ `401 Unauthorized` пришёл в HTML. Проверить `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`. |
| `curl failed: ... Could not resolve host` | Хост недоступен. `LANGFUSE_HOST` или `N8N_HOST` прописаны без схемы — скрипт сам добавит `https://`, но DNS должен резолвиться. |
| `no row for idea=... arxiv=...` в `create_dataset.py` | В Postgres нет соответствующей статьи. Прогнать `arxiv_search` с нужным `arxiv_id` и повторить. |
| В Compare runs пишет `No scores` | Эвалуатор `relevance_score_judge_traces` не в режиме Experiments или не включён. Проверить настройки (см. секцию "Langfuse-настройки"). Учти: backfill-а нет — нужны НОВЫЕ run'ы после активации эвалуатора. |
| Один item падает с таймаутом | В `run_bench.py` увеличить `timeout_s` у `call_relevance` (по умолчанию 60 с). Либо запускать с `--limit` и разбираться с конкретным item'ом. |

## Решения, зашитые в коде

- **Identifier статьи.** В `papers` хранится `arxiv_id` с суффиксом версии (`2603.28204v2`). В датасет кладём его как `paper_id`, и `relevance_score` воркфлоу принимает ровно такой же ключ.
- **Модель по умолчанию.** `relevance_score` использует `openai/gpt-5.4-nano`, если `model` не передан. Это позволяет бенчмарку явно передавать модель, а проду (`daily_digest`) продолжать работать без изменений.
- **Где скоры.** LAAJ-эвалуатор пишет скоры на уровне dataset-run-item, а не trace. Compare runs берёт именно этот уровень; trace-level скоры туда не бабл-апятся.
- **stdlib only.** Скрипты используют `curl` через `subprocess` и стандартную библиотеку Python, никаких `pip install` — можно запускать где угодно, где есть `python3 ≥ 3.10`, `curl` и (для `create_dataset.py`) `docker compose`.
