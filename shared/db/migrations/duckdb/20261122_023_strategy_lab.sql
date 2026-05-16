-- Migration 023 — Strategy Lab v2 (Blocco E, ROADMAP v5)

CREATE TABLE IF NOT EXISTS strategy_registry (
    strategy_id   VARCHAR     NOT NULL,
    name          VARCHAR     NOT NULL,
    description   VARCHAR     DEFAULT '',
    params        VARCHAR     DEFAULT '{}',  -- JSON
    is_active     BOOLEAN     DEFAULT FALSE,
    is_validated  BOOLEAN     DEFAULT FALSE,
    sharpe_oos    DOUBLE,
    n_folds       INTEGER     DEFAULT 0,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    validated_at  TIMESTAMPTZ,
    version       INTEGER     DEFAULT 1,
    PRIMARY KEY (strategy_id, version)
);

CREATE TABLE IF NOT EXISTS strategy_backtest_results (
    strategy_id   VARCHAR     NOT NULL,
    ticker        VARCHAR     NOT NULL,
    regime        VARCHAR     NOT NULL,   -- 'bull'|'bear'|'stress'|'transition'|'overall'
    run_at        TIMESTAMPTZ NOT NULL,
    n_days        INTEGER,
    sharpe        DOUBLE,
    total_return  DOUBLE,
    max_drawdown  DOUBLE,
    win_rate      DOUBLE,
    n_trades      INTEGER,
    PRIMARY KEY (strategy_id, ticker, regime, run_at)
);

CREATE TABLE IF NOT EXISTS strategy_walk_forward_log (
    strategy_id       VARCHAR     NOT NULL,
    run_at            TIMESTAMPTZ NOT NULL,
    n_folds           INTEGER     NOT NULL,
    sharpe_oos_mean   DOUBLE      NOT NULL,
    sharpe_oos_std    DOUBLE,
    sharpe_oos_min    DOUBLE,
    is_validated      BOOLEAN     NOT NULL,
    validation_note   VARCHAR,
    PRIMARY KEY (strategy_id, run_at)
);

CREATE INDEX IF NOT EXISTS idx_strategy_registry_active
    ON strategy_registry (is_active, is_validated);

CREATE INDEX IF NOT EXISTS idx_backtest_results_strategy
    ON strategy_backtest_results (strategy_id, run_at DESC);
