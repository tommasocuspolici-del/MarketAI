-- =============================================================================
-- Migration 018 — Valuation Engine: P/E Ratio Multi-Indicatore
-- ROADMAP_ANALISI_MERCATO_v4 — Blocco 3 (Settimane 6-7)
-- Data: 2026-10-01
--
-- Tabelle:
--   · shiller_cape_historical  — CAPE Shiller dal 1881 (serie storica lunga)
--   · pe_metrics               — PE trailing/forward + ERP (snapshot giornaliero)
--   · valuation_signal         — Segnale composito [-1,+1] per Composite v2
-- =============================================================================

-- ─── Storico CAPE Shiller (1881 → oggi) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS shiller_cape_historical (
    data_date          DATE        NOT NULL,
    sp500_price        DOUBLE,                 -- Prezzo S&P 500 mensile
    eps_10y_real_avg   DOUBLE,                 -- Media CPI-adjusted 10Y
    cape_ratio         DOUBLE,                 -- Price / eps_10y_real_avg
    bond_yield         DOUBLE,                 -- US 10Y yield contemporaneo
    erp_implied        DOUBLE,                 -- Earnings yield - bond yield
    cpi_level          DOUBLE,                 -- CPI level per aggiustamento reale
    source             VARCHAR NOT NULL DEFAULT 'shiller_yale',
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (data_date)
);

CREATE INDEX IF NOT EXISTS idx_shiller_cape_date
    ON shiller_cape_historical (data_date DESC);

-- ─── PE Metrics giornalieri (snapshot calcolato) ───────────────────────────
CREATE TABLE IF NOT EXISTS pe_metrics (
    metric_date        DATE        NOT NULL,
    ticker             VARCHAR     NOT NULL,   -- '^GSPC' | 'SPY' | singolo titolo
    price              DOUBLE,
    -- Metriche P/E
    trailing_pe        DOUBLE,                 -- Price / EPS trailing 4Q
    forward_pe         DOUBLE,                 -- Price / EPS forward 12M (stima)
    shiller_cape       DOUBLE,                 -- Price / mean(real_EPS_10y)
    peg_ratio          DOUBLE,                 -- Forward PE / EPS growth 5Y
    -- Equity Risk Premium
    erp_implied        DOUBLE,                 -- 1/ForwardPE - DGS10
    erp_regime         VARCHAR,                -- 'attractive'|'fair'|'expensive'|'extreme'
    -- Contestualizzazione storica (z-score su finestra 20 anni)
    trailing_pe_zscore DOUBLE,
    forward_pe_zscore  DOUBLE,
    cape_zscore        DOUBLE,
    -- Percentile storico [0, 100]
    trailing_pe_pct    DOUBLE,
    forward_pe_pct     DOUBLE,
    cape_pct           DOUBLE,
    -- EPS inputs usati nel calcolo
    eps_trailing_4q    DOUBLE,
    eps_forward_1y     DOUBLE,
    risk_free_rate     DOUBLE,                 -- DGS10 usato per ERP
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (metric_date, ticker)
);

CREATE INDEX IF NOT EXISTS idx_pe_metrics_ticker_date
    ON pe_metrics (ticker, metric_date DESC);

-- ─── Segnale valuation composito [-1, +1] ─────────────────────────────────
CREATE TABLE IF NOT EXISTS valuation_signal (
    signal_date        DATE        NOT NULL,
    ticker             VARCHAR     NOT NULL,
    valuation_score    DOUBLE,                 -- [-1,+1]: +1=molto sottovalutato
    trailing_pe_signal DOUBLE,                 -- Componente trailing PE
    forward_pe_signal  DOUBLE,                 -- Componente forward PE
    cape_signal        DOUBLE,                 -- Componente CAPE
    erp_signal         DOUBLE,                 -- Componente ERP
    label              VARCHAR,                -- 'deep_value'|'cheap'|'fair_value'|'stretched'|'bubble_warning'
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (signal_date, ticker)
);
