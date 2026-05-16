-- Migration 025 — Options Analytics (Blocco D, ROADMAP v5)

CREATE TABLE IF NOT EXISTS options_greeks_snapshots (
    computed_at    TIMESTAMPTZ NOT NULL,
    ticker         VARCHAR     NOT NULL,
    option_type    VARCHAR     NOT NULL,   -- 'call' | 'put'
    strike         DOUBLE      NOT NULL,
    expiry_days    INTEGER     NOT NULL,
    spot           DOUBLE      NOT NULL,
    iv             DOUBLE      NOT NULL,
    price          DOUBLE      NOT NULL,
    delta          DOUBLE,
    gamma          DOUBLE,
    vega           DOUBLE,
    theta          DOUBLE,
    rho            DOUBLE,
    source         VARCHAR     DEFAULT 'mock',   -- 'mock' | 'finnhub'
    PRIMARY KEY (computed_at, ticker, option_type, strike, expiry_days)
);

CREATE TABLE IF NOT EXISTS options_strategies (
    id             VARCHAR     NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL,
    ticker         VARCHAR     NOT NULL,
    strategy_name  VARCHAR     NOT NULL,   -- 'straddle' | 'collar' | 'covered_call' | 'vertical_call_spread' | 'vertical_put_spread'
    spot_at_entry  DOUBLE      NOT NULL,
    net_premium    DOUBLE      NOT NULL,
    max_profit     DOUBLE,
    max_loss       DOUBLE,
    breakeven_1    DOUBLE,
    breakeven_2    DOUBLE,
    legs_json      VARCHAR,                -- JSON array of leg definitions
    notes          VARCHAR,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS options_expected_moves (
    computed_at    TIMESTAMPTZ NOT NULL,
    ticker         VARCHAR     NOT NULL,
    spot           DOUBLE      NOT NULL,
    iv             DOUBLE      NOT NULL,
    expiry_days    INTEGER     NOT NULL,
    move_abs       DOUBLE      NOT NULL,
    move_pct       DOUBLE      NOT NULL,
    upper_1sigma   DOUBLE      NOT NULL,
    lower_1sigma   DOUBLE      NOT NULL,
    upper_2sigma   DOUBLE      NOT NULL,
    lower_2sigma   DOUBLE      NOT NULL,
    PRIMARY KEY (computed_at, ticker, expiry_days)
);

CREATE TABLE IF NOT EXISTS options_iv_surface (
    computed_at    TIMESTAMPTZ NOT NULL,
    ticker         VARCHAR     NOT NULL,
    strike         DOUBLE      NOT NULL,
    expiry_days    INTEGER     NOT NULL,
    iv             DOUBLE      NOT NULL,
    option_type    VARCHAR     NOT NULL,
    source         VARCHAR     DEFAULT 'mock',
    PRIMARY KEY (computed_at, ticker, strike, expiry_days, option_type)
);
