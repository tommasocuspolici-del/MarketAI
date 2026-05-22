-- Risk Extended Tables — Fase D
-- Roadmap Miglioramento v1.0

CREATE TABLE IF NOT EXISTS portfolio_risk_metrics (
    snapshot_date      DATE        NOT NULL,
    portfolio_id       VARCHAR     NOT NULL,
    var_95             DOUBLE,
    var_99             DOUBLE,
    cvar_95            DOUBLE,
    cvar_99            DOUBLE,
    cvar_expansion     DOUBLE,
    cvar_slowdown      DOUBLE,
    cvar_contraction   DOUBLE,
    max_drawdown_1y    DOUBLE,
    ulcer_index        DOUBLE,
    liquidity_days_90  DOUBLE,
    hhi_concentration  DOUBLE,
    PRIMARY KEY (snapshot_date, portfolio_id)
);

CREATE TABLE IF NOT EXISTS position_risk_contribution (
    snapshot_date      DATE        NOT NULL,
    portfolio_id       VARCHAR     NOT NULL,
    ticker             VARCHAR     NOT NULL,
    marginal_var       DOUBLE,
    component_var      DOUBLE,
    pct_risk           DOUBLE,
    adtv_30d           DOUBLE,
    days_to_liquidate  DOUBLE,
    PRIMARY KEY (snapshot_date, portfolio_id, ticker)
);
