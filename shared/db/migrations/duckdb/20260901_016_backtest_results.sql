-- =============================================================================
-- Migration 016 — Backtest Results (Roadmap v3.0 Settimana 9)
-- Data: 2026-09-01
--
-- REGOLA 27: Ogni modifica schema DuckDB deve avere un migration SQL.
-- REGOLA 31: backtest_results → 2 anni (Regola 31 esplicita).
--
-- Tabella: backtest_results
--   Archivia i risultati di ogni run BacktestRunner (single, walk-forward,
--   stress). Include le performance metrics per confronto tra strategie.
--
-- run_type: 'single' | 'walkforward' | 'stress'
-- scenario: NULL per run non-stress; nome scenario per stress test.
-- =============================================================================

-- Drop ALL indexes on backtest_results (DuckDB ALTER TABLE richiede nessuna dipendenza)
DROP INDEX IF EXISTS idx_backtest_strategy;
DROP INDEX IF EXISTS idx_backtest_strategy_ticker;
DROP INDEX IF EXISTS idx_backtest_run_type_scenario;
-- Aggiunge colonne mancanti
ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS run_type VARCHAR;
ALTER TABLE backtest_results ADD COLUMN IF NOT EXISTS scenario VARCHAR;
UPDATE backtest_results SET run_type = 'single' WHERE run_type IS NULL;

CREATE TABLE IF NOT EXISTS backtest_results (
    run_id          VARCHAR      NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    strategy_name   VARCHAR      NOT NULL,
    ticker          VARCHAR      NOT NULL,
    run_type        VARCHAR      NOT NULL,       -- 'single' | 'walkforward' | 'stress'
    scenario        VARCHAR,                      -- NULL | 'recession' | 'inflation_shock' | ecc.
    -- Performance metrics (da PerformanceReport)
    sharpe_ratio    DOUBLE,
    max_drawdown    DOUBLE,                       -- valore negativo (es. -0.15 = -15%)
    total_return    DOUBLE,                       -- es. 0.23 = +23%
    win_rate        DOUBLE,                       -- [0, 1]
    calmar_ratio    DOUBLE,
    n_trades        INTEGER,
    fees_total      DOUBLE,
    initial_cash    DOUBLE,
    -- Configurazione (JSON per flessibilità futura)
    config_json     VARCHAR,
    -- Metadati
    run_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id)
);

-- Ricerca per strategia + ticker (query UI backtesting)
CREATE INDEX IF NOT EXISTS idx_backtest_strategy_ticker
    ON backtest_results (strategy_name, ticker, run_at DESC);

-- Ricerca per tipo run (confronto stress scenarios)
CREATE INDEX IF NOT EXISTS idx_backtest_run_type_scenario
    ON backtest_results (run_type, scenario, run_at DESC);
