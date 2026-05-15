-- =============================================================================
-- Migration 019 — Correlation Engine v2
-- ROADMAP_ANALISI_MERCATO_v4 — Blocco 4 (Settimane 8-9)
-- Data: 2026-10-15
--
-- Tabelle:
--   · dcc_garch_matrix    — Correlazioni DCC/EWMA per coppia asset (snapshot)
--   · lead_lag_signals    — Risultati Granger causality test
--   · cross_asset_regime  — Regime cross-asset + diversification score
-- =============================================================================

-- ─── Matrici DCC/EWMA (snapshot settimanale) ─────────────────────────────
CREATE TABLE IF NOT EXISTS dcc_garch_matrix (
    snapshot_date      DATE        NOT NULL,
    asset_a            VARCHAR     NOT NULL,
    asset_b            VARCHAR     NOT NULL,
    dcc_correlation    DOUBLE,                 -- DCC-GARCH se disponibile
    ewma_correlation   DOUBLE,                 -- EWMA enhanced (sempre disponibile)
    static_correlation DOUBLE,                 -- Pearson 252gg
    regime_label       VARCHAR,                -- 'bull'|'bear'|'stress'|'transition'
    correlation_regime VARCHAR,                -- 'high_corr'|'normal'|'decorrelated'|'negative'
    decay_lambda       DOUBLE,                 -- Lambda EWMA ottimale (MLE)
    PRIMARY KEY (snapshot_date, asset_a, asset_b)
);

CREATE INDEX IF NOT EXISTS idx_dcc_garch_date
    ON dcc_garch_matrix (snapshot_date DESC);

-- ─── Lead-lag analysis (Granger causality) ───────────────────────────────
CREATE TABLE IF NOT EXISTS lead_lag_signals (
    analysis_date      DATE        NOT NULL,
    leader_asset       VARCHAR     NOT NULL,
    follower_asset     VARCHAR     NOT NULL,
    optimal_lag_days   INTEGER,                -- Lag ottimale in giorni trading [1-60]
    granger_f_stat     DOUBLE,                 -- F-statistica test Granger
    granger_pvalue     DOUBLE,                 -- p-value (< 0.05 = causalità)
    cross_corr_peak    DOUBLE,                 -- Picco cross-correlazione al lag ottimale
    is_significant     BOOLEAN,                -- True se pvalue < 0.05 AND |corr| > 0.3
    lead_signal        VARCHAR,                -- 'bullish_lead'|'bearish_lead'|'neutral'
    computed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (analysis_date, leader_asset, follower_asset)
);

-- ─── Regime cross-asset (overview settimanale) ────────────────────────────
CREATE TABLE IF NOT EXISTS cross_asset_regime (
    regime_date           DATE        NOT NULL,
    avg_equity_bond_corr  DOUBLE,              -- Stock-bond corr media (risk parity key)
    avg_equity_gold_corr  DOUBLE,
    avg_equity_fx_corr    DOUBLE,
    credit_equity_corr    DOUBLE,              -- HY vs equity
    vix_correlation_regime VARCHAR,            -- 'crisis_coupling'|'normal'|'divergence'
    diversification_score DOUBLE,              -- [0,1]: 1=max diversificato
    correlation_signal    DOUBLE,              -- [-1,1]: per Composite Signal
    computed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (regime_date)
);
