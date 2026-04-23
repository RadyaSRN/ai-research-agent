-- ============================================================================
-- Research Agent — Database Schema
-- ============================================================================
-- Полная схема для персонального research companion.
-- Накатывается одной командой:
--   docker compose exec -T postgres psql -U postgres -d app < postgres/schema.sql
-- ============================================================================

-- Расширения
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ============================================================================
-- USERS
-- ============================================================================
-- Пользователи бота. Один user = один telegram chat_id.
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    telegram_chat_id BIGINT UNIQUE NOT NULL,
    first_name       TEXT,
    last_name        TEXT,
    username         TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE users IS 'Пользователи бота. Один user = один Telegram chat.';
COMMENT ON COLUMN users.telegram_chat_id IS 'chat.id из Telegram, уникальный и стабильный';


-- ============================================================================
-- PROJECTS
-- ============================================================================
-- Исследовательские проекты пользователя.
-- Один user имеет произвольное число проектов.
-- У каждого проекта есть свой embedding для broad retrieval.
-- ============================================================================

CREATE TABLE IF NOT EXISTS projects (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title                   TEXT NOT NULL,
    description             TEXT NOT NULL,
    keywords                TEXT[] NOT NULL DEFAULT '{}',
    status                  TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'paused', 'archived')),
    embedding               vector(1536),
    embedding_model_version TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE projects IS 'Research projects; каждый user имеет произвольное число';
COMMENT ON COLUMN projects.embedding IS 'Embedding от title + description + keywords; обновляется при любом изменении этих полей';
COMMENT ON COLUMN projects.embedding_model_version IS 'Строка вида openai-text-embedding-3-small-v1 для будущей миграции моделей';

CREATE INDEX IF NOT EXISTS idx_projects_user_status 
    ON projects(user_id, status);

CREATE INDEX IF NOT EXISTS idx_projects_embedding 
    ON projects USING hnsw (embedding vector_cosine_ops);


-- ============================================================================
-- IDEAS
-- ============================================================================
-- Гипотезы/идеи внутри проекта.
-- Каждая идея принадлежит ровно одному проекту.
-- user_id денормализован для быстрых запросов "все idea этого user'а".
-- ============================================================================

CREATE TABLE IF NOT EXISTS ideas (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    project_id              UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title                   TEXT NOT NULL,
    description             TEXT NOT NULL,
    keywords                TEXT[] NOT NULL DEFAULT '{}',
    status                  TEXT NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active', 'paused', 'done', 'dropped')),
    example_papers          JSONB NOT NULL DEFAULT '[]'::jsonb,
    embedding               vector(1536),
    embedding_model_version TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE ideas IS 'Конкретные гипотезы внутри проектов';
COMMENT ON COLUMN ideas.user_id IS 'Денормализация: дублируется из projects.user_id для быстрых запросов';
COMMENT ON COLUMN ideas.example_papers IS 'JSONB массив arxiv_id, которые user считает типично релевантными этой идее (для exemplar-based retrieval в v2)';
COMMENT ON COLUMN ideas.embedding IS 'Embedding от title + description + keywords';

CREATE INDEX IF NOT EXISTS idx_ideas_project 
    ON ideas(project_id);

CREATE INDEX IF NOT EXISTS idx_ideas_user_status 
    ON ideas(user_id, status);

CREATE INDEX IF NOT EXISTS idx_ideas_embedding 
    ON ideas USING hnsw (embedding vector_cosine_ops);


-- ============================================================================
-- PAPERS
-- ============================================================================
-- Общий корпус всех статей, которые система когда-либо видела.
-- Не привязан к пользователям — один корпус на всех.
-- Наполняется тремя путями: scheduled ingestion, onboarding scan, ondemand search.
-- ============================================================================

CREATE TABLE IF NOT EXISTS papers (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    arxiv_id       TEXT UNIQUE NOT NULL,
    title          TEXT NOT NULL,
    abstract       TEXT NOT NULL,
    authors        TEXT[] NOT NULL DEFAULT '{}',
    categories     TEXT[] NOT NULL DEFAULT '{}',
    published_at   TIMESTAMPTZ,
    updated_at_arxiv TIMESTAMPTZ,
    url            TEXT,
    pdf_url        TEXT,
    ingested_via   TEXT NOT NULL DEFAULT 'scheduled'
                   CHECK (ingested_via IN ('scheduled', 'onboarding_scan', 'ondemand_search', 'manual')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE papers IS 'Общий корпус статей; дедуп по arxiv_id';
COMMENT ON COLUMN papers.arxiv_id IS 'Например 2604.09528v1; включает version suffix';
COMMENT ON COLUMN papers.published_at IS 'Дата submission на arxiv (из Atom feed)';
COMMENT ON COLUMN papers.created_at IS 'Когда мы впервые увидели эту статью';
COMMENT ON COLUMN papers.ingested_via IS 'Какой путь добавил статью: scheduled ingestion, onboarding scan, on-demand search в чате';

CREATE INDEX IF NOT EXISTS idx_papers_published_desc 
    ON papers(published_at DESC);

CREATE INDEX IF NOT EXISTS idx_papers_created_desc 
    ON papers(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_papers_categories 
    ON papers USING GIN (categories);


-- ============================================================================
-- PAPER_EMBEDDINGS
-- ============================================================================
-- Отдельная таблица для эмбеддингов статей.
-- Отделена от papers, чтобы можно было перегенерировать embeddings 
-- (например, при переходе на Voyage) без переливки основных метаданных.
-- ============================================================================

CREATE TABLE IF NOT EXISTS paper_embeddings (
    paper_id                UUID PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    embedding               vector(1536) NOT NULL,
    embedding_model_version TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE paper_embeddings IS 'Embeddings статей, отделены от papers для гибкости при смене модели';
COMMENT ON COLUMN paper_embeddings.embedding IS 'Embedding от title + abstract, размерность 1536';

CREATE INDEX IF NOT EXISTS idx_paper_embeddings_hnsw 
    ON paper_embeddings USING hnsw (embedding vector_cosine_ops);


-- ============================================================================
-- IDEA_PAPER_MATCHES
-- ============================================================================
-- Сопоставления «статья релевантна идее».
-- Создаётся в двух местах:
--   1. Во время daily-digest — после двухуровневой фильтрации.
--   2. Во время onboarding scan — когда user создаёт новую idea.
-- ============================================================================

CREATE TABLE IF NOT EXISTS idea_paper_matches (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    idea_id             UUID NOT NULL REFERENCES ideas(id) ON DELETE CASCADE,
    paper_id            UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    cosine_similarity   FLOAT,
    llm_relevance_score FLOAT,
    llm_reasoning       TEXT,
    delivered_in_digest BOOLEAN NOT NULL DEFAULT false,
    delivered_at        TIMESTAMPTZ,
    source              TEXT NOT NULL DEFAULT 'daily_digest'
                        CHECK (source IN ('daily_digest', 'onboarding_scan', 'chat_search')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (idea_id, paper_id)
);

COMMENT ON TABLE idea_paper_matches IS 'Матчинг статей к идеям с двухуровневым scoring (cosine + LLM)';
COMMENT ON COLUMN idea_paper_matches.cosine_similarity IS 'Первичный score от pgvector (0-1, больше = ближе)';
COMMENT ON COLUMN idea_paper_matches.llm_relevance_score IS 'Вторичный score от LLM reranker (0-10)';
COMMENT ON COLUMN idea_paper_matches.delivered_in_digest IS 'Попала ли статья в отправленный дайджест пользователю';

CREATE INDEX IF NOT EXISTS idx_matches_idea 
    ON idea_paper_matches(idea_id);

CREATE INDEX IF NOT EXISTS idx_matches_paper 
    ON idea_paper_matches(paper_id);

CREATE INDEX IF NOT EXISTS idx_matches_undelivered 
    ON idea_paper_matches(idea_id, delivered_in_digest) 
    WHERE delivered_in_digest = false;


-- ============================================================================
-- DIGEST_HISTORY
-- ============================================================================
-- История отправленных дайджестов.
-- ============================================================================

CREATE TABLE IF NOT EXISTS digest_history (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    digest_date         DATE NOT NULL,
    project_ids         UUID[] NOT NULL DEFAULT '{}',
    paper_ids           UUID[] NOT NULL DEFAULT '{}',
    message_text        TEXT,
    telegram_message_id BIGINT,
    sent_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE digest_history IS 'История отправленных ежедневных дайджестов';
COMMENT ON COLUMN digest_history.telegram_message_id IS 'ID Telegram-сообщения, чтобы обновлять его при feedback-нажатиях';

CREATE INDEX IF NOT EXISTS idx_digest_history_user_date 
    ON digest_history(user_id, digest_date DESC);


-- ============================================================================
-- FEEDBACK
-- ============================================================================
-- Реакции пользователя на статьи в дайджесте / в чате.
-- ============================================================================

CREATE TABLE IF NOT EXISTS feedback (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    paper_id   UUID REFERENCES papers(id) ON DELETE CASCADE,
    idea_id    UUID REFERENCES ideas(id) ON DELETE SET NULL,
    reaction   TEXT NOT NULL CHECK (reaction IN ('thumbs_up', 'thumbs_down')),
    context    TEXT NOT NULL CHECK (context IN ('digest', 'chat', 'onboarding')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE feedback IS 'Реакции пользователя на статьи; источник онлайн-метрик качества';

CREATE INDEX IF NOT EXISTS idx_feedback_user 
    ON feedback(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_paper 
    ON feedback(paper_id);


-- ============================================================================
-- AUTO-UPDATE TRIGGERS для updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_projects_updated_at ON projects;
CREATE TRIGGER update_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_ideas_updated_at ON ideas;
CREATE TRIGGER update_ideas_updated_at
    BEFORE UPDATE ON ideas
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- ============================================================================
-- DIGEST_SCHEDULES
-- ============================================================================
-- Расписания дайджестов. Один user = одна запись.
-- ============================================================================

CREATE TABLE IF NOT EXISTS digest_schedules (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    is_enabled  BOOLEAN NOT NULL DEFAULT TRUE,
    send_time   TIME NOT NULL,
    timezone    TEXT NOT NULL DEFAULT 'Europe/Moscow',
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id)
);

COMMENT ON TABLE digest_schedules IS 'Расписания daily digest; один user — одна запись';
COMMENT ON COLUMN digest_schedules.send_time IS 'Локальное время отправки (без даты)';
COMMENT ON COLUMN digest_schedules.timezone IS 'IANA timezone для вычисления next_run_at';
COMMENT ON COLUMN digest_schedules.next_run_at IS 'Следующий запуск в UTC; пересчитывается при каждом set';

CREATE INDEX IF NOT EXISTS idx_digest_schedules_next_run
    ON digest_schedules (next_run_at)
    WHERE is_enabled = TRUE;

DROP TRIGGER IF EXISTS set_timestamp_digest_schedules ON digest_schedules;
CREATE TRIGGER set_timestamp_digest_schedules
    BEFORE UPDATE ON digest_schedules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- ============================================================================
-- PAPER_METRICS
-- ============================================================================
-- Метрики статей.
-- ============================================================================

CREATE TABLE IF NOT EXISTS paper_metrics (
    paper_id                   UUID PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    citation_count             INT,
    reference_count            INT,
    fields_of_study            TEXT[],
    venue                      TEXT,
    year                       INT,
    open_access_pdf_url        TEXT,
    doi                        TEXT,
    source                     TEXT NOT NULL DEFAULT 'openalex',
    found                      BOOLEAN NOT NULL DEFAULT true,
    fetched_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    stale_after                TIMESTAMPTZ NOT NULL DEFAULT now() + INTERVAL '7 days'
);

CREATE INDEX IF NOT EXISTS idx_paper_metrics_stale ON paper_metrics(stale_after);


-- ============================================================================
-- ALERT_BUCKETS
-- ============================================================================
-- Дедуп-таблица для алертинга. Каждая (alert_key, bucket_id) пара записывается
-- максимум один раз, что позволяет слать алерт один раз в пределах временного
-- бакета (час / день). Вставка через ON CONFLICT DO NOTHING RETURNING —
-- если строка вернулась, это первый алерт в бакете; если пустая — уже слали.
-- ============================================================================

CREATE TABLE IF NOT EXISTS alert_buckets (
    alert_key        TEXT         NOT NULL,
    bucket_id        TEXT         NOT NULL,
    fired_at         TIMESTAMPTZ  NOT NULL DEFAULT now(),
    cost_value       NUMERIC,
    threshold_value  NUMERIC,
    PRIMARY KEY (alert_key, bucket_id)
);

CREATE INDEX IF NOT EXISTS idx_alert_buckets_fired_at ON alert_buckets(fired_at DESC);
