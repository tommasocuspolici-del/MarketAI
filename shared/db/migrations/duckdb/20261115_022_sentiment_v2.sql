-- Migration 022 — Sentiment Engine v2 (Blocco A, ROADMAP v5)

-- Entity-level sentiment (per ticker/source)
CREATE TABLE IF NOT EXISTS sentiment_entity (
    snapshot_date  DATE        NOT NULL,
    ticker         VARCHAR     NOT NULL,
    source         VARCHAR     NOT NULL,
    entity_score   DOUBLE      NOT NULL,
    confidence     DOUBLE      NOT NULL,
    article_count  INTEGER     DEFAULT 1,
    -- QC-1: IC tracking
    ic_estimate    DOUBLE,
    quality_flag   VARCHAR     DEFAULT 'ok',
    model_version  VARCHAR     DEFAULT 'finbert-tone',
    fetched_at     TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (snapshot_date, ticker, source)
);

-- Sentiment velocity (first derivative)
CREATE TABLE IF NOT EXISTS sentiment_velocity (
    snapshot_date DATE        NOT NULL,
    ticker        VARCHAR     NOT NULL DEFAULT '__market__',
    velocity_1d   DOUBLE,
    velocity_5d   DOUBLE,
    velocity_20d  DOUBLE,
    acceleration  DOUBLE,
    regime        VARCHAR,
    fetched_at    TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (snapshot_date, ticker)
);

-- Deduplicated news event clusters
CREATE TABLE IF NOT EXISTS news_event_clusters (
    cluster_date       DATE    NOT NULL,
    cluster_id         VARCHAR NOT NULL,
    theme              VARCHAR NOT NULL,
    article_count      INTEGER NOT NULL,
    deduplicated_count INTEGER,
    avg_sentiment      DOUBLE  NOT NULL,
    top_keywords       VARCHAR NOT NULL,
    tickers_affected   VARCHAR,
    PRIMARY KEY (cluster_date, cluster_id)
);

-- Source credibility (updated weekly via IC tracking)
CREATE TABLE IF NOT EXISTS sentiment_source_credibility (
    source         VARCHAR NOT NULL,
    period_start   DATE    NOT NULL,
    period_end     DATE    NOT NULL,
    accuracy_score DOUBLE  NOT NULL,
    weight_assigned DOUBLE NOT NULL,
    sample_size    INTEGER NOT NULL,
    PRIMARY KEY (source, period_start)
);

-- IC log: sentiment signal quality over time (QC-2)
CREATE TABLE IF NOT EXISTS sentiment_ic_log (
    log_date       DATE    NOT NULL,
    signal_name    VARCHAR NOT NULL,
    ic_3m          DOUBLE,
    ic_6m          DOUBLE,
    quality_flag   VARCHAR DEFAULT 'ok',
    n_observations INTEGER,
    PRIMARY KEY (log_date, signal_name)
);

-- Index for fast entity lookups
CREATE INDEX IF NOT EXISTS idx_sentiment_entity_ticker
    ON sentiment_entity (ticker, snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_sentiment_velocity_ticker
    ON sentiment_velocity (ticker, snapshot_date DESC);
