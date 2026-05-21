-- Migration 028 — Earnings Calendar
-- ROADMAP v11.0 — Fase A1
-- Data: 2026-05-21
--
-- REGOLA 27: Ogni modifica schema DuckDB deve avere un migration SQL.
--
-- Tabella: earnings_calendar
--   Cataloghi utili aziendali scaricati da yfinance.
--   Contiene stime consensus EPS/Revenue, risultati effettivi e sorprese.
--
-- RETENTION: 5 anni (dati fondamentali aziendali).
-- =============================================================================

CREATE TABLE IF NOT EXISTS earnings_calendar (
    ticker              VARCHAR     NOT NULL,
    company_name        VARCHAR,
    report_date         DATE        NOT NULL,
    report_time         VARCHAR,                    -- 'BMO' | 'AMC' | 'TNS' | NULL
    eps_estimate        DOUBLE,
    revenue_estimate    DOUBLE,
    eps_actual          DOUBLE,
    revenue_actual      DOUBLE,
    eps_surprise_pct    DOUBLE,
    revenue_surprise_pct DOUBLE,
    fiscal_period       VARCHAR,                    -- es. 'Q1 2026'
    source              VARCHAR     NOT NULL DEFAULT 'yfinance',
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, report_date)
);

CREATE INDEX IF NOT EXISTS idx_earnings_calendar_date
    ON earnings_calendar (report_date DESC);

CREATE INDEX IF NOT EXISTS idx_earnings_calendar_ticker
    ON earnings_calendar (ticker, report_date DESC);
