-- ═══════════════════════════════════════════════════════════════════════════
-- Migration: 20260801_009_labour_market
-- Roadmap Analisi/Previsione v1.0 — Blocco B: Labour Market Forecasting
--
-- Tabelle create:
--   · jolts_monthly        - Dati JOLTS mensili (FRED)
--   · claims_cycle         - Initial/Continuing Claims + 4wk MA + regime
--   · payroll_sector       - NFP per settore + revisions tracker
--   · labour_regime        - Regime mercato del lavoro aggregato
--   · labour_forecasts     - Previsioni 1M/3M/6M ensemble
--
-- Regola 27: ogni modifica schema DuckDB → script SQL in migrations/duckdb/
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── JOLTS MONTHLY ───────────────────────────────────────────────────────────
-- Fonte: FRED series JTSJOL, JTSHL, JTSQUL, JTSLUL, JTSQUR, JTSJOR
CREATE TABLE IF NOT EXISTS jolts_monthly (
    series_date        DATE        NOT NULL,
    job_openings       DOUBLE,              -- Migliaia di posizioni aperte (SA)
    hires              DOUBLE,              -- Migliaia di assunzioni
    quits              DOUBLE,              -- Migliaia di dimissioni volontarie
    layoffs_discharges DOUBLE,              -- Migliaia di licenziamenti
    quits_rate         DOUBLE,              -- % su occupazione totale (leading indicator)
    openings_rate      DOUBLE,              -- Openings/labor force %
    hires_rate         DOUBLE,
    beveridge_gap      DOUBLE,              -- openings_rate - unemployment_rate
    hires_quits_ratio  DOUBLE,              -- hires / quits: > 1 = mercato tight
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (series_date)
);

CREATE INDEX IF NOT EXISTS idx_jolts_monthly_date
    ON jolts_monthly (series_date DESC);

-- ─── CLAIMS CYCLE ─────────────────────────────────────────────────────────────
-- Fonte: FRED ICSA (weekly SA), CCSA, IURSA
CREATE TABLE IF NOT EXISTS claims_cycle (
    week_ending        DATE        NOT NULL,
    initial_claims     INTEGER,             -- Richieste settimanali (migliaia)
    continuing_claims  INTEGER,             -- Richieste continuative
    insured_unemp_rate DOUBLE,              -- Tasso disoccupazione assicurata %
    claims_4wk_ma      DOUBLE,              -- Media mobile 4 settimane (smoothing)
    claims_yoy_pct     DOUBLE,              -- Variazione anno su anno %
    claims_mom_pct     DOUBLE,              -- Variazione mensile %
    cycle_regime       VARCHAR,             -- 'expansion'|'peak'|'contraction'|'trough'
    signal_strength    DOUBLE,              -- [-1, 1]: -1 = deterioration, +1 = improvement
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (week_ending)
);

CREATE INDEX IF NOT EXISTS idx_claims_cycle_date
    ON claims_cycle (week_ending DESC);

-- ─── PAYROLL SECTOR ──────────────────────────────────────────────────────────
-- Fonte: FRED PAYEMS + serie settoriali
CREATE TABLE IF NOT EXISTS payroll_sector (
    release_date       DATE        NOT NULL,
    sector             VARCHAR     NOT NULL,   -- 'manufacturing'|'services'|'government'|...
    jobs_added_k       DOUBLE,                 -- Migliaia di posti creati/persi
    prev_month_revised DOUBLE,                 -- Revisione mese precedente
    two_month_revision DOUBLE,                 -- Revisione cumulata 2 mesi
    yoy_pct            DOUBLE,                 -- Crescita YoY %
    share_of_total     DOUBLE,                 -- % sul totale NFP
    is_cyclical        BOOLEAN DEFAULT FALSE,  -- True per settori ciclici
    PRIMARY KEY (release_date, sector)
);

CREATE INDEX IF NOT EXISTS idx_payroll_sector_release
    ON payroll_sector (release_date DESC, sector);

-- ─── LABOUR REGIME ───────────────────────────────────────────────────────────
-- Classificazione aggregata del mercato del lavoro
CREATE TABLE IF NOT EXISTS labour_regime (
    snapshot_date      DATE        NOT NULL,
    regime             VARCHAR     NOT NULL,   -- 'tight'|'balanced'|'slack'|'deteriorating'
    composite_score    DOUBLE,                 -- [-1, 1]: +1 = mercato molto forte
    jolts_score        DOUBLE,                 -- Componente JOLTS [-1, 1]
    claims_score       DOUBLE,                 -- Componente Claims [-1, 1]
    payroll_score      DOUBLE,                 -- Componente Payroll [-1, 1]
    confidence         DOUBLE,                 -- [0, 1]: affidabilità classificazione
    PRIMARY KEY (snapshot_date)
);

-- ─── LABOUR FORECASTS ────────────────────────────────────────────────────────
-- Output del LabourForecastEngine
CREATE TABLE IF NOT EXISTS labour_forecasts (
    generated_at       TIMESTAMPTZ NOT NULL,
    horizon            VARCHAR     NOT NULL,   -- '1M'|'3M'|'6M'
    target_metric      VARCHAR     NOT NULL,   -- 'unemployment_rate'|'nfp'|'quits_rate'
    forecast_value     DOUBLE,                 -- Punto centrale
    forecast_lower     DOUBLE,                 -- Percentile 10 (scenario pessimistico)
    forecast_upper     DOUBLE,                 -- Percentile 90 (scenario ottimistico)
    model_used         VARCHAR,                -- Es. 'ensemble_arima0.5_ridge0.5'
    arima_forecast     DOUBLE,                 -- Componente ARIMA
    ridge_forecast     DOUBLE,                 -- Componente Ridge regression
    PRIMARY KEY (generated_at, horizon, target_metric)
);

CREATE INDEX IF NOT EXISTS idx_labour_forecasts_generated
    ON labour_forecasts (generated_at DESC);
