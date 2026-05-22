-- Signal Quality Framework (Convenzione 37) — Fase B
-- Roadmap Miglioramento v1.0

CREATE TABLE IF NOT EXISTS signal_scorecard (
    signal_id          VARCHAR     NOT NULL,
    snapshot_date      DATE        NOT NULL,
    horizon_days       INTEGER     NOT NULL,
    ic_mean            DOUBLE,
    ic_std             DOUBLE,
    ic_tstat           DOUBLE,
    ic_ir              DOUBLE,
    hit_rate           DOUBLE,
    sharpe_ls          DOUBLE,
    alpha_decay_hl     INTEGER,
    is_stale           BOOLEAN     DEFAULT FALSE,
    staleness_days     INTEGER     DEFAULT 0,
    is_significant     BOOLEAN,
    weight_current     DOUBLE,
    PRIMARY KEY (signal_id, snapshot_date, horizon_days)
);

CREATE TABLE IF NOT EXISTS composite_weights_history (
    snapshot_date       DATE        NOT NULL,
    signal_id           VARCHAR     NOT NULL,
    weight              DOUBLE      NOT NULL,
    optimization_method VARCHAR,
    PRIMARY KEY (snapshot_date, signal_id)
);
