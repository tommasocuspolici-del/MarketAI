-- Migration 020 — Valuation Complete (Fase 6)
-- Compatibile con Migration 010 (valuation_pe.sql) — aggiunge solo colonne mancanti.
-- Regola 33: data_source mai NULL — ogni dato ha fonte documentata.

-- ─── pe_metrics (aggiornata con colonne mancanti) ────────────────────────────
CREATE TABLE IF NOT EXISTS pe_metrics (
    metric_date        DATE        NOT NULL,
    ticker             VARCHAR     NOT NULL,
    price              DOUBLE      NOT NULL,     -- Da PricesRepository (Regola 33)
    eps_trailing_4q    DOUBLE,                   -- EDGAR XBRL reale
    eps_forward_1y     DOUBLE,                   -- AV consensus reale
    trailing_pe        DOUBLE,
    forward_pe         DOUBLE,
    shiller_cape       DOUBLE,
    peg_ratio          DOUBLE,
    erp_implied        DOUBLE,                   -- 1/ForwardPE - DGS10 (FRED)
    erp_regime         VARCHAR,                  -- 'attractive'|'fair'|'expensive'|'extreme'
    trailing_pe_zscore DOUBLE,
    forward_pe_zscore  DOUBLE,
    cape_zscore        DOUBLE,
    trailing_pe_pct    DOUBLE,
    forward_pe_pct     DOUBLE,
    cape_pct           DOUBLE,
    risk_free_rate     DOUBLE,                   -- DGS10/100 — Regola 33
    data_source        VARCHAR     DEFAULT 'edgar+fred',  -- mai NULL — Regola 33
    fetched_at         TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (metric_date, ticker)
);

-- ─── shiller_cape_historical (serie dal 1881) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS shiller_cape_historical (
    data_date          DATE        NOT NULL,
    sp500_price        DOUBLE,
    eps_10y_real_avg   DOUBLE,
    cape_ratio         DOUBLE,
    bond_yield         DOUBLE,
    erp_implied        DOUBLE,
    data_source        VARCHAR     DEFAULT 'yale_shiller',  -- mai NULL — Regola 33
    fetched_at         TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (data_date)
);

CREATE INDEX IF NOT EXISTS idx_cape_date
    ON shiller_cape_historical (data_date DESC);

-- ─── valuation_signal (per Composite Signal v3) ───────────────────────────────
CREATE TABLE IF NOT EXISTS valuation_signal (
    signal_date        DATE        NOT NULL,
    ticker             VARCHAR     NOT NULL,
    valuation_score    DOUBLE,                   -- [-1, +1] per Composite
    trailing_pe_signal DOUBLE,
    forward_pe_signal  DOUBLE,
    cape_signal        DOUBLE,
    erp_signal         DOUBLE,
    label              VARCHAR,                  -- 'cheap'|'fair'|'expensive'|'extreme'
    data_quality       VARCHAR     DEFAULT 'ok', -- 'ok'|'estimated'|'stale'
    computed_at        TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (signal_date, ticker)
);

-- ─── Aggiunta colonne mancanti se tabelle già esistono ───────────────────────
-- DuckDB supporta ALTER TABLE ADD COLUMN IF NOT EXISTS dalla v0.9+

ALTER TABLE pe_metrics ADD COLUMN IF NOT EXISTS risk_free_rate DOUBLE;
ALTER TABLE pe_metrics ADD COLUMN IF NOT EXISTS data_source VARCHAR DEFAULT 'edgar+fred';
ALTER TABLE pe_metrics ADD COLUMN IF NOT EXISTS forward_pe_pct DOUBLE;

-- ─── OHLCV data (tabella generica per prezzi storici e crypto) ───────────────
CREATE TABLE IF NOT EXISTS ohlcv_data (
    ticker      VARCHAR     NOT NULL,
    exchange    VARCHAR     NOT NULL,
    timeframe   VARCHAR     NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      DOUBLE,
    source      VARCHAR,
    currency    VARCHAR     DEFAULT 'USD',
    fetched_at  TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (ticker, exchange, timeframe, ts)
);

CREATE INDEX IF NOT EXISTS idx_ohlcv_ticker_ts
    ON ohlcv_data (ticker, ts DESC);

-- ─── Crypto prices view (creata qui dopo che ohlcv_data esiste) ──────────────
CREATE VIEW IF NOT EXISTS crypto_prices_latest AS
SELECT
    ticker,
    close AS price_usd,
    volume,
    ts::DATE AS price_date,
    source,
    fetched_at
FROM ohlcv_data
WHERE exchange = 'CRYPTO'
  AND timeframe = 'D1'
QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY ts DESC) = 1;
