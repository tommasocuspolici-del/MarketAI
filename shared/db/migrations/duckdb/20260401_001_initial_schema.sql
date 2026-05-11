-- ═══════════════════════════════════════════════════════════════════════════
-- Migration: 20260401_001_initial_schema
-- DuckDB initial schema for Market Analysis AI v6.0
-- ═══════════════════════════════════════════════════════════════════════════
-- Tables created:
--   · prices_ohlcv          - OHLCV bars (daily + intraday)
--   · macro_series          - Time-series macro indicators (FRED, ECB, BLS)
--   · fundamentals          - SEC EDGAR fundamentals (XBRL-derived)
--   · sentiment_observations- Sentiment scores from multiple sources
--   · data_quality_reports  - DataQualityReport per series (Rule 26)
--   · backtest_results      - Persistent backtest output (Rule 23)
--   · stress_scenarios      - Historical + synthetic stress scenarios
--   · correlations          - Rolling + regime-conditional correlation matrices
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── PRICES (OHLCV) ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS prices_ohlcv (
    ticker        VARCHAR NOT NULL,
    exchange      VARCHAR NOT NULL,
    timeframe     VARCHAR NOT NULL,       -- '1d', '1h', etc.
    ts            TIMESTAMPTZ NOT NULL,
    open          DOUBLE NOT NULL,
    high          DOUBLE NOT NULL,
    low           DOUBLE NOT NULL,
    close         DOUBLE NOT NULL,
    volume        BIGINT NOT NULL,
    adj_close     DOUBLE,
    currency      VARCHAR NOT NULL DEFAULT 'USD',
    source        VARCHAR NOT NULL,
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, exchange, timeframe, ts)
);

CREATE INDEX IF NOT EXISTS idx_prices_ticker_ts
    ON prices_ohlcv(ticker, ts);
CREATE INDEX IF NOT EXISTS idx_prices_ts
    ON prices_ohlcv(ts);

-- ─── MACRO SERIES ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS macro_series (
    series_id     VARCHAR NOT NULL,       -- FRED / ECB / BLS id
    ts            TIMESTAMPTZ NOT NULL,
    value         DOUBLE,                 -- NULL ammesso per mancati rilasci
    source        VARCHAR NOT NULL,       -- 'fred', 'ecb', 'bls', ...
    unit          VARCHAR,
    frequency     VARCHAR,                -- 'D', 'W', 'M', 'Q', 'Y'
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (series_id, ts)
);

CREATE INDEX IF NOT EXISTS idx_macro_series_id_ts
    ON macro_series(series_id, ts);

-- ─── FUNDAMENTALS (SEC EDGAR / annual + quarterly) ─────────────────────────
CREATE TABLE IF NOT EXISTS fundamentals (
    ticker        VARCHAR NOT NULL,
    cik           VARCHAR,                -- Central Index Key SEC
    metric        VARCHAR NOT NULL,       -- 'Revenue', 'NetIncome', ...
    period_end    DATE NOT NULL,
    period_type   VARCHAR NOT NULL,       -- 'Q1','Q2','Q3','Q4','FY'
    value         DOUBLE,
    currency      VARCHAR,
    filing_date   DATE,
    form_type     VARCHAR,                -- '10-K', '10-Q', ...
    source        VARCHAR NOT NULL DEFAULT 'sec_edgar',
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, metric, period_end, period_type)
);

CREATE INDEX IF NOT EXISTS idx_fundamentals_ticker
    ON fundamentals(ticker, period_end);

-- ─── SENTIMENT OBSERVATIONS ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentiment_observations (
    source        VARCHAR NOT NULL,       -- 'cnn_fng','aaii','put_call',...
    asset         VARCHAR NOT NULL,       -- 'SPY','BTC','market' (aggregato)
    ts            TIMESTAMPTZ NOT NULL,
    score         DOUBLE NOT NULL,        -- normalizzato in [-1, 1]
    raw_value     DOUBLE,                 -- valore grezzo pre-normalizzazione
    metadata      VARCHAR,                -- JSON string con dettagli
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source, asset, ts)
);

CREATE INDEX IF NOT EXISTS idx_sentiment_asset_ts
    ON sentiment_observations(asset, ts);

-- ─── DATA QUALITY REPORTS (Rule 26) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS data_quality_reports (
    series_id         VARCHAR NOT NULL,
    series_kind       VARCHAR NOT NULL,   -- 'prices', 'macro', 'fundamentals'
    evaluated_at      TIMESTAMPTZ NOT NULL,
    quality_score     DOUBLE NOT NULL,    -- [0.0, 1.0]
    gaps_count        INTEGER NOT NULL DEFAULT 0,
    gaps_pct          DOUBLE NOT NULL DEFAULT 0.0,
    outliers_count    INTEGER NOT NULL DEFAULT 0,
    outliers_pct      DOUBLE NOT NULL DEFAULT 0.0,
    stale_days        INTEGER NOT NULL DEFAULT 0,
    total_rows        INTEGER NOT NULL,
    first_ts          TIMESTAMPTZ,
    last_ts           TIMESTAMPTZ,
    notes             VARCHAR,            -- messaggi diagnostici
    PRIMARY KEY (series_id, evaluated_at)
);

CREATE INDEX IF NOT EXISTS idx_quality_series_id
    ON data_quality_reports(series_id, evaluated_at DESC);

-- ─── BACKTEST RESULTS (Rule 23) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS backtest_results (
    backtest_id       VARCHAR PRIMARY KEY,
    strategy_name     VARCHAR NOT NULL,
    ticker            VARCHAR NOT NULL,
    timeframe         VARCHAR NOT NULL,
    start_ts          TIMESTAMPTZ NOT NULL,
    end_ts            TIMESTAMPTZ NOT NULL,
    fees              DOUBLE NOT NULL,
    slippage          DOUBLE NOT NULL,
    total_return      DOUBLE NOT NULL,
    sharpe_ratio      DOUBLE,
    sortino_ratio     DOUBLE,
    max_drawdown      DOUBLE,
    win_rate          DOUBLE,
    profit_factor     DOUBLE,
    n_trades          INTEGER NOT NULL,
    params_json       VARCHAR,            -- parametri strategia in JSON
    run_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_strategy
    ON backtest_results(strategy_name, run_at DESC);

-- ─── STRESS SCENARIOS (Rule 24) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS stress_scenarios (
    scenario_id       VARCHAR PRIMARY KEY,
    scenario_type     VARCHAR NOT NULL,   -- 'historical' | 'synthetic'
    name              VARCHAR NOT NULL,
    description       VARCHAR,
    equity_shock_pct  DOUBLE NOT NULL,
    bond_shock_pct    DOUBLE NOT NULL,
    fx_shock_pct      DOUBLE,
    vol_multiplier    DOUBLE NOT NULL DEFAULT 1.0,
    probability       DOUBLE,             -- NULL per scenari storici
    generated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    market_context    VARCHAR             -- JSON snapshot del contesto
);

-- ─── CORRELATIONS (DCC-GARCH + regime) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS correlations (
    asset_a           VARCHAR NOT NULL,
    asset_b           VARCHAR NOT NULL,
    ts                TIMESTAMPTZ NOT NULL,
    window_days       INTEGER NOT NULL,   -- 30, 90, 252
    correlation       DOUBLE NOT NULL,    -- [-1, 1]
    regime            VARCHAR,            -- 'bull'|'bear'|'transition'|'stress'
    method            VARCHAR NOT NULL,   -- 'pearson','dcc_garch','kendall'
    inserted_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (asset_a, asset_b, ts, window_days, method)
);

CREATE INDEX IF NOT EXISTS idx_correlations_pair_ts
    ON correlations(asset_a, asset_b, ts);
