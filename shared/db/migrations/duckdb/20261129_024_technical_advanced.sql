-- Migration 024 — Technical Analysis Advanced (Blocco F, ROADMAP v5)

CREATE TABLE IF NOT EXISTS mtf_signals (
    computed_at    TIMESTAMPTZ NOT NULL,
    ticker         VARCHAR     NOT NULL,
    confluence     DOUBLE      NOT NULL,
    conviction     VARCHAR     NOT NULL,
    n_agreeing     INTEGER,
    daily_dir      VARCHAR,
    weekly_dir     VARCHAR,
    monthly_dir    VARCHAR,
    ic_estimate    DOUBLE,
    quality_flag   VARCHAR     DEFAULT 'ok',
    PRIMARY KEY (computed_at, ticker)
);

CREATE TABLE IF NOT EXISTS volume_profile_snapshots (
    computed_at    TIMESTAMPTZ NOT NULL,
    ticker         VARCHAR     NOT NULL,
    poc            DOUBLE      NOT NULL,
    vah            DOUBLE      NOT NULL,
    val            DOUBLE      NOT NULL,
    vwap           DOUBLE      NOT NULL,
    current_price  DOUBLE      NOT NULL,
    signal         DOUBLE,
    signal_label   VARCHAR,
    n_bars         INTEGER,
    PRIMARY KEY (computed_at, ticker)
);

CREATE TABLE IF NOT EXISTS cycle_analysis (
    computed_at         TIMESTAMPTZ NOT NULL,
    ticker              VARCHAR     NOT NULL,
    hurst               DOUBLE,
    hurst_regime        VARCHAR,
    dominant_cycle_days INTEGER,
    n_obs               INTEGER,
    PRIMARY KEY (computed_at, ticker)
);

CREATE TABLE IF NOT EXISTS order_flow_snapshots (
    computed_at      TIMESTAMPTZ NOT NULL,
    ticker           VARCHAR     NOT NULL,
    cvd_last         DOUBLE,
    cvd_change_pct   DOUBLE,
    delta_ratio      DOUBLE,
    signal           DOUBLE,
    divergence       BOOLEAN     DEFAULT FALSE,
    n_bars           INTEGER,
    PRIMARY KEY (computed_at, ticker)
);

CREATE INDEX IF NOT EXISTS idx_mtf_ticker
    ON mtf_signals (ticker, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_cycle_ticker
    ON cycle_analysis (ticker, computed_at DESC);
