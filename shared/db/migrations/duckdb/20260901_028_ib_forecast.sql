-- Migration 028 — IB Forecast Engine (Fase 8)
-- Tabelle per previsioni Investment Bank e consensus.
-- Regola 33: data_source mai NULL — ogni previsione ha fonte documentata.

-- ─── Report IB scaricati ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ib_reports (
    report_id        VARCHAR     NOT NULL,
    source           VARCHAR     NOT NULL,      -- mai NULL — Regola 33 (es. 'goldman', 'fed_sep')
    report_type      VARCHAR     NOT NULL,      -- 'outlook'|'sep'|'weo'|'rss'
    title            VARCHAR,
    raw_text         VARCHAR,
    published_at     TIMESTAMPTZ,
    fetched_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (report_id)
);

-- ─── Previsioni estratte ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ib_forecasts (
    forecast_id      VARCHAR     NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    report_id        VARCHAR     NOT NULL,
    source           VARCHAR     NOT NULL,      -- mai NULL — Regola 33
    indicator        VARCHAR     NOT NULL,      -- 'GDP'|'CPI'|'FEDFUNDS'|'SP500'|...
    horizon          VARCHAR     NOT NULL,      -- '2024'|'2025'|'Q1_2025'|'12M'
    value            DOUBLE,                    -- Valore numerico (es. 2.5 per GDP 2.5%)
    value_range_low  DOUBLE,
    value_range_high DOUBLE,
    unit             VARCHAR     DEFAULT 'percent',
    extraction_method VARCHAR    DEFAULT 'regex',  -- 'regex'|'llm'|'api'
    confidence       DOUBLE      DEFAULT 0.7,   -- [0, 1]
    fetched_at       TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (forecast_id)
);

CREATE INDEX IF NOT EXISTS idx_ib_forecasts_indicator
    ON ib_forecasts (indicator, horizon);

CREATE INDEX IF NOT EXISTS idx_ib_forecasts_source
    ON ib_forecasts (source, fetched_at DESC);

-- ─── Consensus aggregato ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ib_consensus (
    consensus_id     VARCHAR     NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    indicator        VARCHAR     NOT NULL,
    horizon          VARCHAR     NOT NULL,
    consensus_value  DOUBLE,
    consensus_low    DOUBLE,
    consensus_high   DOUBLE,
    source_count     INTEGER     DEFAULT 0,
    method           VARCHAR     DEFAULT 'median',
    data_quality     VARCHAR     DEFAULT 'ok',
    computed_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (consensus_id),
    UNIQUE (indicator, horizon)
);

-- ─── Segnale IB per Composite Signal v3 ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS ib_signal (
    signal_date      TIMESTAMPTZ NOT NULL,
    score            DOUBLE      NOT NULL,      -- [-1, +1]
    gdp_signal       DOUBLE,
    inflation_signal DOUBLE,
    rates_signal     DOUBLE,
    equity_signal    DOUBLE,
    source_count     INTEGER     DEFAULT 0,
    data_quality     VARCHAR     DEFAULT 'ok',
    computed_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (signal_date)
);

-- ─── Valuation complete (Fase 6) — aggiunge tabelle mancanti ─────────────────
CREATE TABLE IF NOT EXISTS valuation_signal (
    signal_date      DATE        NOT NULL,
    ticker           VARCHAR     NOT NULL,
    valuation_score  DOUBLE,
    trailing_pe_signal DOUBLE,
    forward_pe_signal  DOUBLE,
    cape_signal        DOUBLE,
    erp_signal         DOUBLE,
    label              VARCHAR,
    data_quality       VARCHAR    DEFAULT 'ok',
    computed_at        TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (signal_date, ticker)
);
