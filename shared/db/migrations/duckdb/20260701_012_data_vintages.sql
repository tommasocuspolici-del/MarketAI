-- Data Vintages e Audit Log (Convenzione 35) — Fase A
-- Roadmap Miglioramento v1.0

CREATE TABLE IF NOT EXISTS data_vintages (
    series_id          VARCHAR     NOT NULL,
    observation_date   DATE        NOT NULL,
    vintage_date       DATE        NOT NULL,
    value              DOUBLE      NOT NULL,
    is_revised         BOOLEAN     DEFAULT FALSE,
    revision_count     INTEGER     DEFAULT 0,
    first_published    DATE,
    source             VARCHAR,
    PRIMARY KEY (series_id, observation_date, vintage_date)
);

CREATE TABLE IF NOT EXISTS publication_lag_registry (
    series_id              VARCHAR     PRIMARY KEY,
    typical_lag_days       INTEGER,
    max_lag_days           INTEGER,
    revision_frequency     VARCHAR,
    revision_magnitude_avg DOUBLE,
    source                 VARCHAR,
    last_updated           TIMESTAMPTZ DEFAULT NOW()
);

CREATE SEQUENCE IF NOT EXISTS seq_audit_log START 1;

CREATE TABLE IF NOT EXISTS audit_log (
    log_id           BIGINT      DEFAULT nextval('seq_audit_log'),
    event_ts         TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    operation        VARCHAR     NOT NULL,
    source           VARCHAR,
    endpoint         VARCHAR,
    data_hash_sha256 VARCHAR,
    record_count     INTEGER,
    outcome          VARCHAR,
    error_msg        VARCHAR,
    duration_ms      DOUBLE,
    PRIMARY KEY (log_id)
);
