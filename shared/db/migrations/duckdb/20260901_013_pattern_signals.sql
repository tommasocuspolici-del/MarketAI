-- =============================================================================
-- Migration 013 — Pattern Signals (riconoscimento automatico pattern grafici)
-- Roadmap v3.0 — Settimana 3: Pattern Recognition
-- Data: 2026-09-01
--
-- REGOLA 27: Ogni modifica schema DuckDB deve avere un migration SQL.
-- REGOLA 31: Retention sentiment → 3 anni. I pattern sono sentiment-like.
--
-- Tabella: pattern_signals
--   Archivia i pattern grafici rilevati da PatternDetector su serie OHLCV.
--   Usata dalla pagina K2 (Equity) per mostrare badge pattern sul chart.
-- =============================================================================

CREATE TABLE IF NOT EXISTS pattern_signals (
    signal_id      VARCHAR        NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    ticker         VARCHAR        NOT NULL,
    pattern_type   VARCHAR        NOT NULL, -- 'head_and_shoulders' | 'double_top' | ecc.
    signal_dir     VARCHAR        NOT NULL, -- 'bullish' | 'bearish' | 'neutral'
    confidence     DOUBLE         NOT NULL, -- [0.0, 1.0]
    start_date     TIMESTAMPTZ    NOT NULL,
    end_date       TIMESTAMPTZ    NOT NULL,
    start_idx      INTEGER        NOT NULL,
    end_idx        INTEGER        NOT NULL,
    -- Livelli chiave (JSON: neckline, target, breakout, ecc.)
    key_levels_json VARCHAR,
    description    VARCHAR,
    detected_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    -- Stato: ACTIVE = non ancora breakout, TRIGGERED = breakout confermato, EXPIRED = scaduto
    status         VARCHAR        NOT NULL DEFAULT 'ACTIVE',
    PRIMARY KEY (signal_id)
);

-- Ricerca rapida per ticker + data (query UI)
CREATE INDEX IF NOT EXISTS idx_pattern_signals_ticker_date
    ON pattern_signals (ticker, detected_at DESC);

-- Ricerca per tipo pattern (analytics)
CREATE INDEX IF NOT EXISTS idx_pattern_signals_type_confidence
    ON pattern_signals (pattern_type, confidence DESC);
