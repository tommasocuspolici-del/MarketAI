-- ═══════════════════════════════════════════════════════════════════════════
-- Migration: 20260615_007_unified_v2
-- Roadmap Unificata v1.0 — Data Layer completo
--
-- Tabelle create:
--   · vix_signals              - Segnali VIX calcolati (Z-Score, regime)
--   · vix_strategy_outputs     - Output StrategyComposer (timing + sizing)
--   · futures_ohlcv            - OHLCV futures continui con roll_yield + basis
--   · claims_inflation_signals - Cross-indicator Claims/Inflation
--   · yield_curve_snapshots    - Snapshot curva yield + Estrella-Mishkin prob
--   · credit_spread_signals    - HY/IG OAS + TED + NFCI regime
--   · engine_composite_signal  - Score composito aggregato [-1, 1]
--   · regime_reports           - Output HMM regime (già in uso dall'engine)
--
-- Regola 27: ogni modifica schema DuckDB → script SQL in migrations/duckdb/
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── VIX SIGNALS ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vix_signals (
    computed_at         TIMESTAMPTZ NOT NULL,
    vix_level           DOUBLE NOT NULL,        -- Livello VIX corrente
    vix_zscore          DOUBLE NOT NULL,        -- Z-Score rispetto a lookback
    vix_vxv_ratio       DOUBLE,                 -- VIX / VXV (term structure ratio)
    vix_pct_rank        DOUBLE,                 -- Percentile rank su lookback
    spike_detected      BOOLEAN NOT NULL DEFAULT FALSE,
    zscore_signal       VARCHAR,                -- 'buy'|'sell'|'hold'
    regime              VARCHAR,                -- 'calm'|'elevated'|'high_stress'|'panic'
    lookback_days       INTEGER NOT NULL DEFAULT 252,
    PRIMARY KEY (computed_at)
);

CREATE INDEX IF NOT EXISTS idx_vix_signals_ts
    ON vix_signals (computed_at DESC);

-- ─── VIX STRATEGY OUTPUTS ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vix_strategy_outputs (
    computed_at         TIMESTAMPTZ NOT NULL,
    -- Timing signal
    vix_signal          DOUBLE NOT NULL,        -- [0, 1]: 1 = fortissimo buy
    action              VARCHAR NOT NULL,        -- 'BUY'|'HOLD'|'REDUCE'
    -- Sizing signal
    position_size_pct   DOUBLE,                 -- [0, 1] frazione del portafoglio
    -- Macro overlay
    macro_score         DOUBLE,                 -- [-1, 1] da MacroConvictionCalculator
    -- Composite
    composite_score     DOUBLE,                 -- media pesata timing + macro
    confidence          VARCHAR,                -- 'HIGH'|'MEDIUM'|'LOW'
    -- Metadati
    regime_used         VARCHAR,                -- regime HMM usato per adjustment
    threshold_adjusted  DOUBLE,                 -- soglia Z-Score dopo regime adjustment
    notes               VARCHAR,                -- spiegazione narrativa
    PRIMARY KEY (computed_at)
);

CREATE INDEX IF NOT EXISTS idx_vix_strategy_ts
    ON vix_strategy_outputs (computed_at DESC);

-- ─── FUTURES OHLCV ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS futures_ohlcv (
    ticker              VARCHAR NOT NULL,
    contract_month      VARCHAR NOT NULL,        -- 'front'|'second'|'third'
    ts                  TIMESTAMPTZ NOT NULL,
    open                DOUBLE,
    high                DOUBLE,
    low                 DOUBLE,
    close               DOUBLE NOT NULL,
    volume              BIGINT,
    open_interest       BIGINT,                  -- critico per sentiment istituzionale
    roll_yield          DOUBLE,                  -- (front_close / second_close) - 1
    basis               DOUBLE,                  -- futures_price - spot_etf_price
    term_structure      VARCHAR,                 -- 'backwardation'|'contango'|'flat'
    source              VARCHAR NOT NULL DEFAULT 'yfinance_futures',
    inserted_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, contract_month, ts)
);

CREATE INDEX IF NOT EXISTS idx_futures_ticker_ts
    ON futures_ohlcv (ticker, ts DESC);

CREATE INDEX IF NOT EXISTS idx_futures_ts
    ON futures_ohlcv (ts DESC);

-- ─── CLAIMS INFLATION SIGNALS ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS claims_inflation_signals (
    computed_at             TIMESTAMPTZ PRIMARY KEY,
    icsa_4wk_ma             DOUBLE,              -- Initial Claims 4-week MA
    icsa_yoy_change_pct     DOUBLE,              -- Variazione YoY claims
    cpi_yoy                 DOUBLE,              -- CPI YoY %
    stagflation_signal      BOOLEAN,             -- claims ↑ + CPI > 3%
    goldilocks_signal       BOOLEAN,             -- claims basse + CPI < 3.5%
    overheating_signal      BOOLEAN,             -- claims molto basse + CPI > 4%
    recession_watch         BOOLEAN,             -- claims ↑↑ + CPI < 2.5%
    regime_label            VARCHAR,             -- 'goldilocks'|'stagflation'|'overheating'|'recession'|'neutral'
    regime_score            DOUBLE               -- contributo numerico a macro_score [-1, 1]
);

CREATE INDEX IF NOT EXISTS idx_claims_ts
    ON claims_inflation_signals (computed_at DESC);

-- ─── YIELD CURVE SNAPSHOTS ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS yield_curve_snapshots (
    snapshot_date           DATE PRIMARY KEY,
    y_3m                    DOUBLE,              -- DGS3MO
    y_2y                    DOUBLE,              -- DGS2
    y_5y                    DOUBLE,              -- DGS5
    y_10y                   DOUBLE,              -- DGS10
    y_30y                   DOUBLE,              -- DGS30
    spread_10y_2y           DOUBLE,              -- T10Y2Y
    spread_10y_3m           DOUBLE,              -- T10Y3M (Estrella-Mishkin)
    breakeven_10y           DOUBLE,              -- T10YIE — TIPS breakeven
    fed_funds               DOUBLE,              -- FEDFUNDS
    inversion_signal        BOOLEAN,             -- spread_10y_2y < 0
    recession_prob_12m      DOUBLE,              -- Modello Estrella-Mishkin [0, 1]
    curve_regime            VARCHAR              -- 'normal'|'flat'|'inverted'|'steep'
);

CREATE INDEX IF NOT EXISTS idx_yield_curve_date
    ON yield_curve_snapshots (snapshot_date DESC);

-- ─── CREDIT SPREAD SIGNALS ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS credit_spread_signals (
    computed_at             TIMESTAMPTZ PRIMARY KEY,
    hy_oas                  DOUBLE,              -- ICE BofA HY OAS (bps)
    ig_oas                  DOUBLE,              -- ICE BofA IG OAS (bps)
    hy_ig_ratio             DOUBLE,              -- HY/IG ratio (spread relativo)
    ted_spread              DOUBLE,              -- TED Spread (bps)
    nfci                    DOUBLE,              -- Chicago Fed Financial Conditions
    stress_level            VARCHAR,             -- 'low'|'moderate'|'elevated'|'crisis'
    stress_score            DOUBLE               -- contributo numerico [-1, 1]
);

CREATE INDEX IF NOT EXISTS idx_credit_ts
    ON credit_spread_signals (computed_at DESC);

-- ─── ENGINE COMPOSITE SIGNAL ────────────────────────────────────────────────
-- Input per K1 Market Overview: score composito giornaliero
CREATE TABLE IF NOT EXISTS engine_composite_signal (
    computed_at             TIMESTAMPTZ PRIMARY KEY,
    -- Componenti (tutti in [-1, 1])
    vix_component           DOUBLE,
    macro_component         DOUBLE,
    yield_curve_component   DOUBLE,
    credit_component        DOUBLE,
    claims_component        DOUBLE,
    -- Output
    composite_score         DOUBLE NOT NULL,     -- [-1, 1] somma pesata
    recommended_action      VARCHAR NOT NULL,     -- 'BUY'|'HOLD'|'REDUCE'
    confidence              VARCHAR NOT NULL,     -- 'HIGH'|'MEDIUM'|'LOW'
    component_breakdown_json VARCHAR,            -- JSON per trasparenza UI
    -- Metadata
    weights_used_json       VARCHAR,             -- Pesi usati in questo compute
    regime                  VARCHAR,             -- Regime HMM al momento del calcolo
    credit_stress           VARCHAR,             -- Livello stress credito
    claims_regime           VARCHAR,             -- Regime claims/inflation
    yield_curve_regime      VARCHAR             -- Regime curva yield
);

CREATE INDEX IF NOT EXISTS idx_composite_ts
    ON engine_composite_signal (computed_at DESC);

-- ─── REGIME REPORTS (per HMM - compatibile con modulo già esistente) ────────
-- Questa tabella potrebbe già esistere; CREATE TABLE IF NOT EXISTS è idempotente
CREATE TABLE IF NOT EXISTS regime_reports (
    computed_at             TIMESTAMPTZ PRIMARY KEY,
    regime                  VARCHAR NOT NULL,    -- 'bull'|'bear'|'transition'|'stress'
    regime_probability      DOUBLE,              -- Probabilità del regime corrente
    regime_duration_days    INTEGER,             -- Giorni nel regime corrente
    previous_regime         VARCHAR,
    transition_signal       BOOLEAN DEFAULT FALSE,
    tickers_analyzed        INTEGER,
    method                  VARCHAR DEFAULT 'hmm'
);

CREATE INDEX IF NOT EXISTS idx_regime_ts
    ON regime_reports (computed_at DESC);

-- ─── INDEX AGGIUNTIVO SU macro_series PER FREQUENZA ─────────────────────────
-- Migliora le query per serie con frequenza specifica
CREATE INDEX IF NOT EXISTS idx_macro_series_freq
    ON macro_series (series_id, ts DESC);
