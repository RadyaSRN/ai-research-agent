# daily_digest_for_user

**Trigger**: `executeWorkflow` (вызывается из `digest_scheduler_tick`)
**Active by default**: yes

## Назначение

Формирует и отправляет персональный daily digest: двухуровневая фильтрация (cosine → LLM rerank) по свежим статьям против всех активных идей пользователя, склейка релевантных результатов в Telegram-сообщение и запись истории в `digest_history`.

## Входы

- `user_id` (UUID)

## Выходы

- Одно или несколько Telegram-сообщений пользователю (если найдены релевантные статьи) или короткое "пусто"-сообщение.
- Строки в `idea_paper_matches` (`source='daily_digest'`, `delivered_in_digest=true`).
- Строка в `digest_history` с `paper_ids`, `message_text`, `telegram_message_id`.

## Что делает по шагам

1. `Set` — достаёт `user_id`.
2. `Get candidates` — большой SQL: для каждой активной idea пользователя считает cosine с новыми (недоставленными) статьями из окна N последних дней; LATERAL JOIN возвращает top-K кандидатов на idea.
3. `IF: Has candidates?` — если ничего, переход к `Send info about empty digest`.
4. `Split matches` (Code) — плоский список `{idea, paper}` для batch-прогонки.
5. `Call 'relevance_score'` — для каждой пары запускает LLM rerank.
6. `Record match` — `INSERT INTO idea_paper_matches (...) ON CONFLICT (idea_id, paper_id) DO UPDATE SET llm_relevance_score=..., delivered_in_digest=true, delivered_at=now()`.
7. `IF: Has papers?` — оставляет только пары с `relevance_score ≥ threshold`.
8. `Build digest` (Code) — формирует красивый Markdown: группировка по idea, ссылки на arxiv, score + reasoning.
9. `(Maybe) Split message into smaller ones` — разрезает, если длина > Telegram-лимита 4096.
10. `Send digest` — отправка в Telegram через bot.
11. `Record history` — строка в `digest_history` с `paper_ids` и `telegram_message_id`.

## Зависимости

- **Вызывает воркфлоу**: `relevance_score`
- **Вызывается из**: `digest_scheduler_tick`, `telegram_agent` (команда `/digest`)
- **Credentials в n8n**: `postgres_main`, `telegram_bot`
- **Внешние сервисы**: Telegram Bot API (через `relevance_score` — также OpenRouter + Langfuse)
- **Таблицы БД**: читает `users, projects, ideas, papers, paper_embeddings, idea_paper_matches`; пишет `idea_paper_matches, digest_history`

## Примечания

- `Get candidates` использует LATERAL JOIN с HNSW-индексом — это основной hot-path cosine retrieval.
- Пороги (cosine min, LLM score min, top-K) вшиты в SQL/Code-ноды; при изменении релевантности качать их нужно согласованно.
