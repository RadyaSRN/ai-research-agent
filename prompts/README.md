# prompts/

Source of truth для промптов, которые воркфлоу тянут из Langfuse Prompt Management. Runtime (воркфлоу n8n через ноду `Get system prompt from Langfuse`) продолжает читать из Langfuse; папка `prompts/` нужна, чтобы правки промпта были частью PR, проходили code review и не терялись, если Langfuse-инстанс упадёт / будет пересоздан.

## Формат файла

Один файл = один промпт. Имя файла **строго** совпадает с `promptName` в Langfuse (и с тем, что передано в ноду `Get system prompt from Langfuse` в соответствующем воркфлоу n8n).

Структура файла:

```markdown
---
name: relevance_score          # должно совпадать с filename без .md
type: text                     # text | chat
labels:
  - production                 # при push этот label будет проставлен на новую версию
tags:
  - reranker
  - digest
config:                        # необязательно; если есть, мапится 1-в-1 в Langfuse prompt.config
  model: google/gemini-3-flash-preview
  temperature: 0.0
---

<Тело промпта. Для type=text — просто текст с {{placeholder}} полями.>
```

Для `type: chat` — в frontmatter добавляется поле `messages:` (YAML-массив объектов `{role, content}`), а тело markdown оставляется пустым. У нас сейчас оба промпта типа `text`.

## Наши промпты

| Файл                            | Воркфлоу-потребитель                        | Что делает                                        |
|---|---|---|
| [`relevance_score.md`](relevance_score.md)        | `relevance_score`                 | rubric для LLM-реранкера `(idea, paper)` → скор 0..10 + reasoning |
| [`telegram_agent_system.md`](telegram_agent_system.md) | `telegram_agent`                 | system-prompt главного агента с описанием tools  |

## Синк с Langfuse

Скрипт [`scripts/prompts_sync.py`](../scripts/prompts_sync.py). Зависимости ставим в venv в корне репо (системный `pip` на Debian/Ubuntu блокирует установку по PEP 668):

```bash
python3 -m venv .venv                              # однократно
.venv/bin/pip install -r scripts/requirements.txt  # однократно / при обновлении deps
```

Дальше — три подкоманды:

```bash
.venv/bin/python scripts/prompts_sync.py pull   # Langfuse → prompts/
.venv/bin/python scripts/prompts_sync.py push   # prompts/ → Langfuse (+ label production)
.venv/bin/python scripts/prompts_sync.py check  # diff, exit 1 если разъехалось (для CI)
```

## Типовой workflow разработки

1. Нужно править промпт → отредактировать файл в `prompts/`.
2. Локально прогнать бенчмарк: `python3 bench/run_bench.py --model <...>` — убедиться, что качество не деградирует.
3. Закоммитить, открыть PR.
4. После merge — `scripts/prompts_sync.py push` создаёт новую версию в Langfuse и ставит ей label `production`. Воркфлоу тут же начнут её тянуть на следующем запуске.

## Инициализация после первого клона

Если локальные файлы — заглушки (как при первом клоне), подтянуть актуальное содержимое из Langfuse:

```bash
.venv/bin/python scripts/prompts_sync.py pull
```
