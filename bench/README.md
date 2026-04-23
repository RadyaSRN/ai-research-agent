# bench — оффлайн-бенчмарк `relevance_score`

Папка содержит всё необходимое, чтобы:

1. собрать фиксированный датасет `relevance_score_bench` в Langfuse (20 пар идея↔статья);
2. прогнать на нём одну или несколько LLM (любую модель, доступную в OpenRouter);
3. посмотреть результаты в Langfuse → Datasets → `relevance_score_bench` → **Compare runs**.

Для оценки качества используется LLM-as-a-Judge (LAAJ) эвалуатор `relevance_score_judge_experiments`, сконфигурированный в Langfuse на режим **Experiments** с фильтром `Dataset = relevance_score_bench`. Он автоматически скорит каждый новый experiment (dataset run).

## Содержимое папки

| Файл | Назначение |
|---|---|
| `create_dataset.py` | Одноразовая настройка датасета в Langfuse (создаёт `relevance_score_bench`, загружает 20 item'ов из JSON, обогащает данными из Postgres). |
| `run_bench.py` | Главный драйвер. Прогоняет одну модель по всем item'ам датасета, создаёт trace'ы в Langfuse и линкует их к dataset run'у. |
| `final_20_pairs.json` | Снимок курированных пар (idea_id + arxiv_id + rank). Основа датасета. |
| `run_semantic.py` | Вспомогательная утилита: для каждой идеи заново выполняет `semantic_search_papers` и печатает top-10. Используется только при пересборке датасета. |

## Зависимости вне этой папки

### Переменные окружения

Читаются из `.env` в корне репозитория (`<repo-root>/.env`):

- `N8N_HOST` — хост n8n (схема опциональна, при отсутствии подставляется `https://`);
- `LANGFUSE_HOST` — хост Langfuse;
- `LANGFUSE_PUBLIC_KEY` — `pk-lf-...`;
- `LANGFUSE_SECRET_KEY` — `sk-lf-...`.

### n8n-воркфлоу

- **`relevance_score`** — production-воркфлоу, который бенчмаркается. Принимает `idea_id`, `paper_id`, `model`. Если `model` не передан, используется `openai/gpt-5.4-nano` (прод-модель).
- **`bench_relevance_wrapper`** — webhook-обёртка, через которую `run_bench.py` обращается к `relevance_score`. Путь: `POST /webhook/bench-relevance`. Активен по умолчанию.
- **`bench_search_helper`** — webhook-обёртка над `semantic_search_papers`, используется `run_semantic.py` при пересборке датасета. Путь: `POST /webhook/bench-search`. По умолчанию выключен; активируется только на время пересборки.
- **`semantic_search_papers`** — production-воркфлоу семантического поиска. Вызывается из `bench_search_helper`.
- **`arxiv_search`** — используется косвенно, если перед пересборкой датасета требуется догрузить в корпус новые статьи.

### Langfuse-настройки

- Датасет `relevance_score_bench` (создаётся `create_dataset.py`).
- Эвалуатор `relevance_score_judge_experiments`:
  - **Run on**: `Experiments`;
  - **Filter**: `Dataset = relevance_score_bench`;
  - **Sampling**: 100%;
  - **Variable mapping**: `{{output}}` → Object `Trace`, Object Field `Output`;
  - **Run on new experiments**: ON.

Важно: эвалуатор не делает backfill по уже завершённым run'ам. Если он создан позже, чем сделан прогон, скоров по прошлым run'ам не будет — их потребуется пере-прогнать.

## Quick start

Все команды даются относительно корня репозитория и запускаются из него. Требуется Python 3.10+, используется только stdlib — pip-зависимости отсутствуют. Корень репозитория скрипты определяют сами через `Path(__file__).resolve().parent.parent`, так что расположение клона произвольное.

### Первичная настройка (один раз)

```bash
python3 bench/create_dataset.py
```

Скрипт создаёт датасет в Langfuse (если уже существует — пропускается), затем загружает 20 item'ов, подтягивая актуальные `title/description/abstract` из Postgres через `docker compose exec postgres psql`. Требует, чтобы все 20 `arxiv_id` из `final_20_pairs.json` уже присутствовали в таблице `papers` с проставленными embedding'ами.

### Прогон бенчмарка

Один прогон = одна модель:

```bash
python3 bench/run_bench.py --model openai/gpt-5.4-nano
python3 bench/run_bench.py --model anthropic/claude-haiku-4.5
python3 bench/run_bench.py --model google/gemini-3-flash-preview
```

Имя run'а генерируется автоматически: `<model-slug>-<YYYYMMDD>-<4hex>`. Альтернативно задаётся явно:

```bash
python3 bench/run_bench.py --model openai/gpt-5.4-nano --run-name gpt-nano-prod-prompt-v3
```

Для отладки количество item'ов ограничивается флагом `--limit`:

```bash
python3 bench/run_bench.py --model openai/gpt-5.4-nano --limit 3
```

### Просмотр результатов

1. Открыть **Langfuse → Datasets → `relevance_score_bench` → Compare runs**.
2. Выбрать интересующие run'ы (до 3–4 одновременно; при большем количестве интерфейс становится неудобным).
3. Каждая ячейка = один dataset-run-item: отображаются `input`, raw output от модели, latency/cost и **score от `relevance_score_judge_experiments`** (0..1; выше — ближе к "хорошо откалиброван").
4. Вкладка **Charts** даёт агрегаты (mean score, p50/p95 latency, cost).

### Когда запускать повторный прогон

- Изменился промпт `relevance_score` (в Langfuse Prompt Management или в самом воркфлоу).
- Изменена дефолтная прод-модель.
- Появились новые идеи или статьи → требуется пересборка датасета (см. ниже).
- Требуется сравнить новую модель OpenRouter со старыми.

## Пересборка датасета

Выполняется редко; последовательность шагов:

1. При необходимости догрузить статей в корпус через воркфлоу `arxiv_search` (по `arxiv_id` или `query`) — запускается из n8n UI.
2. Обновить `final_20_pairs.json` вручную: либо взять top-5 `semantic_search_papers` для новых идей, либо провести курирование вручную.
3. (Опционально) Проверить через `python3 bench/run_semantic.py` (предварительно активировав `bench_search_helper` в n8n UI), что корпус содержит ожидаемые статьи.
4. Удалить старые item'ы датасета в Langfuse UI (если структура изменилась) или изменить имя датасета в константе `_DATASET_NAME` и сгенерировать заново.
5. `python3 bench/create_dataset.py`.
6. Пере-прогнать `run_bench.py` для всех моделей.
7. Выключить `bench_search_helper` обратно.

## Troubleshooting

| Симптом | Причина и действия |
|---|---|
| `ERROR: missing required env variable: LANGFUSE_HOST` | Не прочитан `.env` в корне репозитория. Проверить, что файл существует (`<repo-root>/.env`) и содержит нужные ключи. |
| `non-JSON response from Langfuse (...)` | Неверные ключи Langfuse либо ответ `401 Unauthorized` пришёл в HTML. Проверить `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`. |
| `curl failed: ... Could not resolve host` | Хост недоступен. `LANGFUSE_HOST` или `N8N_HOST` заданы без схемы — скрипт добавит `https://` автоматически, но DNS должен резолвиться. |
| `no row for idea=... arxiv=...` в `create_dataset.py` | В Postgres отсутствует соответствующая статья. Запустить `arxiv_search` с нужным `arxiv_id` и повторить. |
| В Compare runs отображается `No scores` | Эвалуатор `relevance_score_judge_experiments` не в режиме Experiments или не включён. Проверить настройки (см. секцию "Langfuse-настройки"). Backfill отсутствует — требуются новые run'ы после активации эвалуатора. |
| Отдельный item падает с таймаутом | В `run_bench.py` увеличить `timeout_s` у `call_relevance` (по умолчанию 60 с). Либо запустить с `--limit` и локализовать проблему на конкретном item'е. |

## Решения, зашитые в коде

- **Identifier статьи.** В `papers` хранится `arxiv_id` с суффиксом версии (`2603.28204v2`). В датасет он попадает как `paper_id`, и `relevance_score` принимает ровно такой же ключ.
- **Модель по умолчанию.** `relevance_score` использует `openai/gpt-5.4-nano`, если `model` не передан. За счёт этого бенчмарк явно передаёт модель, а прод (`daily_digest_for_user`) продолжает работать без изменений.
- **Уровень скоров.** LAAJ-эвалуатор пишет скоры на уровне dataset-run-item, а не trace. Compare runs читает именно этот уровень; trace-level скоры туда не поднимаются.
- **stdlib only.** Скрипты используют `curl` через `subprocess` и стандартную библиотеку Python, без `pip install` — запускаются в любой среде с `python3 ≥ 3.10`, `curl` и (для `create_dataset.py`) `docker compose`.
