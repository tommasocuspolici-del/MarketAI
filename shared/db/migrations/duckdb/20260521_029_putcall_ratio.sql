-- Migration 029 — Put/Call Ratio & Options Skew
-- ROADMAP v11.0 — Fase A2
-- Data: 2026-05-21
--
-- REGOLA 27: Ogni modifica schema DuckDB deve avere un migration SQL.
--
-- Tabella: putcall_ratio_daily
--   Put/Call ratio giornaliero e IV skew derivati da yfinance/CBOE/Finnhub.
--   Aggiorna anche options_iv_surface con dati reali (source != 'mock').
--
-- RETENTION: 3 anni.
-- =============================================================================

CREATE TABLE IF NOT EXISTS putcall_ratio_daily (
    ticker          VARCHAR     NOT NULL,
    date            DATE        NOT NULL,
    put_call_ratio  DOUBLE,                     -- put_volume / call_volume
    put_volume      BIGINT,
    call_volume     BIGINT,
    oi_put          BIGINT,                     -- open interest put
    oi_call         BIGINT,                     -- open interest call
    iv_skew_25d     DOUBLE,                     -- IV(put 25-delta) - IV(call 25-delta)
    iv_atm          DOUBLE,                     -- IV at-the-money
    source          VARCHAR     NOT NULL,       -- 'yfinance_derived' | 'cboe' | 'finnhub'
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, date, source)
);

CREATE INDEX IF NOT EXISTS idx_putcall_ratio_date
    ON putcall_ratio_daily (date DESC);

CREATE INDEX IF NOT EXISTS idx_putcall_ratio_ticker_date
    ON putcall_ratio_daily (ticker, date DESC);
