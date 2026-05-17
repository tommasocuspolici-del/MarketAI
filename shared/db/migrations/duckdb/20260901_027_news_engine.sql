-- Migration 027 — News Engine (Fase 7)
-- Tabelle per il News Engine: articoli, segnale, cluster.
-- Regola 33: campo source mai NULL in tutte le tabelle.

-- ─── Articoli news ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_articles (
    article_id       VARCHAR     NOT NULL,
    url              VARCHAR     NOT NULL,
    title            VARCHAR     NOT NULL,
    source           VARCHAR     NOT NULL,      -- mai NULL — Regola 33
    published_at     TIMESTAMPTZ NOT NULL,
    category         VARCHAR     NOT NULL DEFAULT 'unknown',
    summary          VARCHAR,
    tickers_json     VARCHAR,                   -- JSON array di ticker
    sentiment_score  DOUBLE,                    -- [-1, +1]
    impact_score     DOUBLE      DEFAULT 0.5,   -- [0, 1]
    is_duplicate     BOOLEAN     DEFAULT FALSE,
    cluster_id       VARCHAR,
    fetched_at       TIMESTAMPTZ DEFAULT NOW(),
    data_quality     VARCHAR     DEFAULT 'ok',  -- 'ok'|'low'|'duplicate'
    PRIMARY KEY (article_id)
);

CREATE INDEX IF NOT EXISTS idx_news_published
    ON news_articles (published_at DESC);

CREATE INDEX IF NOT EXISTS idx_news_source
    ON news_articles (source, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_news_category
    ON news_articles (category, published_at DESC);

CREATE INDEX IF NOT EXISTS idx_news_cluster
    ON news_articles (cluster_id);

-- ─── Cluster di eventi ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_clusters (
    cluster_id       VARCHAR     NOT NULL,
    headline         VARCHAR     NOT NULL,
    category         VARCHAR,
    tickers_json     VARCHAR,
    sentiment_score  DOUBLE,
    impact_score     DOUBLE,
    article_count    INTEGER     DEFAULT 1,
    source_count     INTEGER     DEFAULT 1,
    first_seen_at    TIMESTAMPTZ,
    last_updated_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (cluster_id)
);

-- ─── Segnale news aggregato ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS news_signal (
    signal_date      TIMESTAMPTZ NOT NULL,
    score            DOUBLE      NOT NULL,      -- [-1, +1] per Composite Signal v3
    article_count    INTEGER     DEFAULT 0,
    bullish_count    INTEGER     DEFAULT 0,
    bearish_count    INTEGER     DEFAULT 0,
    neutral_count    INTEGER     DEFAULT 0,
    top_tickers_json VARCHAR,
    data_quality     VARCHAR     DEFAULT 'ok',
    computed_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (signal_date)
);
