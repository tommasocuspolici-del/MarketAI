-- Migration 021 — Custom Indicators Framework (Blocco C, ROADMAP v5)

CREATE TABLE IF NOT EXISTS custom_indicator_results (
    computed_at   TIMESTAMPTZ NOT NULL,
    indicator_id  VARCHAR     NOT NULL,
    ticker        VARCHAR,
    value         DOUBLE      NOT NULL,
    output_type   VARCHAR     NOT NULL,
    regime_context VARCHAR,
    params_hash   VARCHAR     NOT NULL,
    -- QC-1: quality tracking
    ic_estimate   DOUBLE,
    quality_flag  VARCHAR     DEFAULT 'ok',
    PRIMARY KEY (computed_at, indicator_id, COALESCE(ticker, '__global__'))
);

CREATE TABLE IF NOT EXISTS custom_indicator_backtest (
    indicator_id    VARCHAR NOT NULL,
    backtest_date   DATE    NOT NULL,
    ticker          VARCHAR NOT NULL,
    horizon_days    INTEGER NOT NULL,
    signal_value    DOUBLE,
    forward_return  DOUBLE,
    hit_rate        DOUBLE,
    information_coeff DOUBLE,
    -- QC-4: IC per regime
    ic_in_bull   DOUBLE,
    ic_in_bear   DOUBLE,
    ic_in_stress DOUBLE,
    PRIMARY KEY (indicator_id, backtest_date, ticker, horizon_days)
);

CREATE TABLE IF NOT EXISTS indicator_calibration_runs (
    indicator_id VARCHAR     NOT NULL,
    run_id       VARCHAR     NOT NULL,
    run_at       TIMESTAMPTZ NOT NULL,
    best_params  VARCHAR     NOT NULL,  -- JSON
    best_ic      DOUBLE      NOT NULL,
    n_trials     INTEGER     NOT NULL,
    PRIMARY KEY (indicator_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_custom_results_id
    ON custom_indicator_results (indicator_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_custom_backtest_id
    ON custom_indicator_backtest (indicator_id, backtest_date DESC);
