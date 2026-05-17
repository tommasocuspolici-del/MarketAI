-- Migration 026 — Cache Layer Foundation (Fase 5)
-- Tabelle di supporto per Regola 34 (cache-first pattern).
-- Compatibile con schema unificato v2 (Migration 007).

-- ─── Crypto prices (CoinGecko) ───────────────────────────────────────────────
-- Nota: la view crypto_prices_latest viene creata nella migrazione 20260801_020
-- dopo che ohlcv_data è garantita esistere (creata da migration 008+).

-- ─── Data source health log ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_source_health (
    check_id        VARCHAR     NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    source_id       VARCHAR     NOT NULL,
    category        VARCHAR     NOT NULL,
    status          VARCHAR     NOT NULL,   -- 'ok'|'degraded'|'down'|'stale'
    ttl_key         VARCHAR,
    ttl_remaining_s DOUBLE,
    last_fetch_at   TIMESTAMPTZ,
    error_message   VARCHAR,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (check_id)
);

CREATE INDEX IF NOT EXISTS idx_dsh_source_checked
    ON data_source_health (source_id, checked_at DESC);

-- ─── Cache metadata (tracking TTL per ogni chiave/sorgente) ─────────────────
CREATE TABLE IF NOT EXISTS cache_metadata (
    cache_key       VARCHAR     NOT NULL,
    category        VARCHAR     NOT NULL,
    ttl_key         VARCHAR     NOT NULL,
    ttl_seconds     INTEGER     NOT NULL,
    last_refresh_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    refresh_count   BIGINT      DEFAULT 0,
    source          VARCHAR,
    is_stale        BOOLEAN     DEFAULT FALSE,
    PRIMARY KEY (cache_key, category)
);

-- ─── Note sulle views per nuove sorgenti ─────────────────────────────────────
-- Le views macro_imf_latest, macro_ecb_latest, macro_oecd_latest vengono create
-- in migration 20260901_027_news_engine.sql dopo che macro_data è garantita
-- presente in tutti gli ambienti (inclusi test isolati).
