-- =============================================================================
-- Migration 014 — User Indicators (DSL indicatori personalizzati)
-- Roadmap v3.0 — Settimana 5: DSL utente
-- Data: 2026-09-01
--
-- REGOLA 27: Ogni modifica schema DuckDB deve avere un migration SQL.
-- REGOLA 31: Indicatori utente → 10 anni (dati personali configurazione).
--
-- Tabella: user_indicators
--   Archivia le espressioni DSL salvate dall'utente, validate da DSLEvaluator.
--   Ogni indicatore può essere filtrato per ticker specifico o applicato a tutti.
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_indicators (
    indicator_id   VARCHAR      NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    name           VARCHAR      NOT NULL,          -- nome leggibile (es. "RSI Signal")
    expression     VARCHAR      NOT NULL,          -- DSL expression validata
    description    VARCHAR,                        -- note opzionali utente
    ticker_filter  VARCHAR,                        -- NULL = tutti i ticker
    chart_type     VARCHAR      NOT NULL DEFAULT 'line', -- 'line' | 'bar' | 'area'
    overlay        BOOLEAN      NOT NULL DEFAULT FALSE,  -- TRUE = sovrapposto al candlestick
    is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (indicator_id)
);

-- Indice per listing veloce (UI ordina per created_at DESC)
CREATE INDEX IF NOT EXISTS idx_user_indicators_active
    ON user_indicators (is_active, created_at DESC);
