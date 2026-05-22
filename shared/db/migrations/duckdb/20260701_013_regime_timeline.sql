-- Macro Regime Timeline (HMM v2) — Fase B
-- Roadmap Miglioramento v1.0

CREATE TABLE IF NOT EXISTS macro_regime_timeline (
    snapshot_date      DATE        NOT NULL,
    regime_label       VARCHAR     NOT NULL,
    prob_expansion     DOUBLE,
    prob_slowdown      DOUBLE,
    prob_contraction   DOUBLE,
    prob_recovery      DOUBLE,
    regime_confidence  DOUBLE,
    model_version      VARCHAR,
    PRIMARY KEY (snapshot_date)
);

CREATE TABLE IF NOT EXISTS conditional_returns (
    asset_class         VARCHAR     NOT NULL,
    regime_label        VARCHAR     NOT NULL,
    expected_return_1m  DOUBLE,
    expected_return_3m  DOUBLE,
    expected_return_6m  DOUBLE,
    volatility_1m       DOUBLE,
    sharpe_1m           DOUBLE,
    observation_count   INTEGER,
    last_updated        TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (asset_class, regime_label)
);
