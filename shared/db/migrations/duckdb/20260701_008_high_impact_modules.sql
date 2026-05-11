-- shared/db/migrations/duckdb/20260701_008_high_impact_modules.sql

-- ─── Modulo 1: Volume Analysis ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS volume_signals (
    ticker          VARCHAR NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    obv             DOUBLE,              -- On Balance Volume cumulativo
    cmf_20          DOUBLE,              -- Chaikin Money Flow 20gg [-1, 1]
    vwap            DOUBLE,              -- Volume Weighted Avg Price
    amihud_ratio    DOUBLE,              -- |return| / volume (illiquidità)
    amihud_10d_ma   DOUBLE,              -- MA 10gg dell'Amihud ratio
    volume_zscore   DOUBLE,              -- Z-Score volume vs media 20gg
    PRIMARY KEY (ticker, ts)
);

-- ─── Modulo 2: Divergence Detector ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS divergence_signals (
    ticker          VARCHAR NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL,
    divergence_type VARCHAR NOT NULL,    -- 'bullish_rsi'|'bearish_rsi'|
                                         -- 'bullish_macd'|'bearish_macd'
    indicator       VARCHAR NOT NULL,    -- 'RSI'|'MACD'
    price_trend     VARCHAR NOT NULL,    -- 'higher_high'|'lower_low'
    indicator_trend VARCHAR NOT NULL,    -- 'lower_high'|'higher_low'
    strength        FLOAT,               -- [0, 1]: quanto è netta la divergenza
    lookback_bars   INTEGER,             -- quante barre copre la divergenza
    is_confirmed    BOOLEAN DEFAULT FALSE,
    PRIMARY KEY (ticker, detected_at, divergence_type)
);

-- ─── Modulo 3: CVaR Fat-Tail ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS risk_metrics (
    ticker          VARCHAR NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL,
    var_95_normal   DOUBLE,              -- VaR 95% con distribuzione normale
    var_95_tstudent DOUBLE,              -- VaR 95% con t-Student (fat-tail)
    cvar_95         DOUBLE,              -- CVaR 95% (Expected Shortfall)
    var_99_tstudent DOUBLE,              -- VaR 99% con t-Student
    cvar_99         DOUBLE,              -- CVaR 99%
    tail_df         DOUBLE,              -- gradi di libertà t-Student stimati
    skewness        DOUBLE,
    kurtosis        DOUBLE,
    PRIMARY KEY (ticker, computed_at)
);

-- ─── Modulo 4: Risk Contribution ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolio_risk_report (
    computed_at         TIMESTAMPTZ NOT NULL,
    profile_id          VARCHAR NOT NULL,
    portfolio_vol_annual DOUBLE,
    portfolio_cvar_95   DOUBLE,
    component_json      VARCHAR,         -- JSON: {ticker: risk_contribution_pct}
    hhi_concentration   DOUBLE,          -- Herfindahl–Hirschman Index [0, 1]
    largest_contributor VARCHAR,         -- ticker con maggiore risk contribution
    largest_contrib_pct DOUBLE,
    PRIMARY KEY (computed_at, profile_id)
);

-- ─── Modulo 5: Vol Surface ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vol_surface_snapshots (
    snapshot_at     TIMESTAMPTZ NOT NULL,
    vix_9d          DOUBLE,              -- VIX9D (9 giorni)
    vix_1m          DOUBLE,              -- VIX (30 giorni, standard)
    vix_3m          DOUBLE,              -- VIX3M (90 giorni)
    vix_6m          DOUBLE,              -- VIX6M (180 giorni)
    skew_index      DOUBLE,              -- CBOE SKEW
    term_slope_1m_3m DOUBLE,             -- vix_3m - vix_1m
    term_slope_3m_6m DOUBLE,             -- vix_6m - vix_3m
    contango_pct    DOUBLE,              -- (vix_3m / vix_1m - 1) * 100
    surface_regime  VARCHAR,             -- 'steep_contango'|'flat'|
                                         -- 'backwardation'|'inverted'
    PRIMARY KEY (snapshot_at)
);

-- ─── Modulo 6: Real Yield ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS real_yield_signals (
    computed_at         TIMESTAMPTZ NOT NULL,
    nominal_10y         DOUBLE,          -- DGS10 (%)
    breakeven_10y       DOUBLE,          -- T10YIE — inflation expectations (%)
    real_yield_10y      DOUBLE,          -- nominal - breakeven (%)
    real_yield_trend    VARCHAR,         -- 'rising'|'falling'|'stable'
    real_yield_zscore   DOUBLE,          -- Z-Score 252gg
    gold_implied_signal VARCHAR,         -- 'bearish_gold'|'neutral'|'bullish_gold'
    equity_pe_pressure  VARCHAR,         -- 'compressing'|'stable'|'expanding'
    PRIMARY KEY (computed_at)
);

-- ─── Rebalancing Engine ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rebalancing_reports (
    report_id       VARCHAR NOT NULL,    -- UUID
    computed_at     TIMESTAMPTZ NOT NULL,
    profile_id      VARCHAR NOT NULL,
    method          VARCHAR NOT NULL,    -- 'markowitz'|'hrp'|'risk_parity'|'equal_weight'
    current_vol     DOUBLE,
    target_vol      DOUBLE,
    current_hhi     DOUBLE,
    expected_hhi    DOUBLE,
    total_trades    INTEGER,
    total_turnover_pct DOUBLE,           -- % portafoglio che cambia
    estimated_tax_impact_eur DOUBLE,     -- stima impatto fiscale
    trades_json     VARCHAR,             -- JSON array dei trade suggeriti
    weights_current_json VARCHAR,        -- JSON: {ticker: weight_current}
    weights_target_json  VARCHAR,        -- JSON: {ticker: weight_target}
    PRIMARY KEY (report_id)
);

CREATE INDEX IF NOT EXISTS idx_rebalancing_profile
    ON rebalancing_reports (profile_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_vol_signals_ticker
    ON volume_signals (ticker, ts DESC);

CREATE INDEX IF NOT EXISTS idx_divergence_recent
    ON divergence_signals (detected_at DESC, is_confirmed);
