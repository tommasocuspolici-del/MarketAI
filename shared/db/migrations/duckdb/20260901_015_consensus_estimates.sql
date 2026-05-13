-- =============================================================================
-- Migration 015 — Consensus Estimates (staging per ConsensusLoader)
-- Roadmap v3.0 — Settimana 6: Economic Surprise Engine v2
-- Data: 2026-09-01
--
-- REGOLA 27: Ogni modifica schema DuckDB deve avere un migration SQL.
--
-- Tabella: consensus_estimates
--   Staging area per le stime consensus prima che vengano merge con gli
--   actual values in economic_consensus. Separata per tracciabilità della
--   fonte (yaml_manual vs fred_derived vs mock) e per supportare revisioni.
--
-- RELAZIONE CON economic_consensus (migration 010):
--   consensus_estimates → (join actuals) → economic_consensus
--   La join avviene in ConsensusLoader.build_for_calculator().
--
-- RETENTION: 2 anni (dati di configurazione utente, non storico prezzi).
-- =============================================================================

CREATE TABLE IF NOT EXISTS consensus_estimates (
    estimate_id    VARCHAR      NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    indicator_code VARCHAR      NOT NULL,          -- 'NFP', 'CPI_YOY', 'ISM_MFG', ...
    release_date   DATE         NOT NULL,           -- data prevista del rilascio
    consensus_value DOUBLE,                         -- stima mediana analisti
    source         VARCHAR      NOT NULL,           -- 'yaml_manual' | 'fred_derived' | 'mock'
    loaded_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (indicator_code, release_date, source)
);

-- Indice per join rapida con economic_consensus
CREATE INDEX IF NOT EXISTS idx_consensus_est_code_date
    ON consensus_estimates (indicator_code, release_date DESC);

-- Indice per reporting per fonte
CREATE INDEX IF NOT EXISTS idx_consensus_est_source
    ON consensus_estimates (source, loaded_at DESC);
