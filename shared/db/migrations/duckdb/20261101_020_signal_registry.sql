-- Migration 020 — Signal Bus Registry (Blocco B, ROADMAP v5)
-- Creates tables for signal snapshots, IC history, and signal dependencies.
-- All tables follow the "IF NOT EXISTS" pattern for idempotent re-runs.

-- ── Signal snapshots (latest value per signal per timestamp) ──────────────
CREATE TABLE IF NOT EXISTS signal_snapshots (
    snapshot_ts         TIMESTAMPTZ NOT NULL,
    signal_name         VARCHAR     NOT NULL,
    signal_value        DOUBLE      NOT NULL,
    confidence          DOUBLE      NOT NULL,
    source_module       VARCHAR     NOT NULL,
    regime_label        VARCHAR,
    -- QC-1: quality tracking
    ic_estimate         DOUBLE,
    quality_flag        VARCHAR     DEFAULT 'ok',
    weight_in_composite DOUBLE,
    metadata            VARCHAR,    -- JSON string
    PRIMARY KEY (snapshot_ts, signal_name)
);

-- ── IC tracking longitudinale per segnale (QC-2) ─────────────────────────
CREATE TABLE IF NOT EXISTS signal_ic_history (
    computed_at         DATE        NOT NULL,
    signal_name         VARCHAR     NOT NULL,
    ic_rolling_3m       DOUBLE,
    ic_rolling_6m       DOUBLE,
    forward_return_5d   DOUBLE,
    quality_flag        VARCHAR,
    weight_multiplier   DOUBLE,
    PRIMARY KEY (computed_at, signal_name)
);

-- ── Signal dependency graph ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signal_dependencies (
    signal_name     VARCHAR NOT NULL,
    depends_on      VARCHAR NOT NULL,
    dependency_type VARCHAR DEFAULT 'required',
    PRIMARY KEY (signal_name, depends_on)
);

-- ── Indexes ───────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_signal_snapshots_name
    ON signal_snapshots (signal_name, snapshot_ts DESC);

CREATE INDEX IF NOT EXISTS idx_signal_ic_history_name
    ON signal_ic_history (signal_name, computed_at DESC);
