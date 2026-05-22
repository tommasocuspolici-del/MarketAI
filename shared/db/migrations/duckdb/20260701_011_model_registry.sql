-- Model Registry (Convenzione 33) — Fase C
-- Roadmap Miglioramento v1.0

CREATE TABLE IF NOT EXISTS model_registry (
    model_id           VARCHAR     PRIMARY KEY,
    model_type         VARCHAR     NOT NULL,
    target_metric      VARCHAR     NOT NULL,
    horizon_days       INTEGER     NOT NULL,
    asset_class        VARCHAR,
    hyperparams        JSON,
    dataset_hash       VARCHAR,
    train_start        DATE,
    train_end          DATE,
    val_start          DATE,
    val_end            DATE,
    mse_oos            DOUBLE,
    mae_oos            DOUBLE,
    mape_oos           DOUBLE,
    directional_acc    DOUBLE,
    sharpe_predictive  DOUBLE,
    is_active          BOOLEAN     DEFAULT FALSE,
    is_baseline_beaten BOOLEAN     DEFAULT FALSE,
    registered_at      TIMESTAMPTZ DEFAULT NOW(),
    notes              VARCHAR
);

CREATE TABLE IF NOT EXISTS wfo_results (
    model_id           VARCHAR     NOT NULL,
    fold_n             INTEGER     NOT NULL,
    train_start        DATE,
    train_end          DATE,
    test_start         DATE,
    test_end           DATE,
    mse                DOUBLE,
    mae                DOUBLE,
    directional_acc    DOUBLE,
    sharpe_fold        DOUBLE,
    PRIMARY KEY (model_id, fold_n)
);
