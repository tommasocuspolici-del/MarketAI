-- =============================================================================
-- Migration 012 — Data Quality Alerts
-- Roadmap v3.0 — Settimana 2: Data Quality avanzata
-- Data: 2026-09-01
--
-- REGOLA 27: Ogni modifica schema DuckDB deve avere un migration SQL.
--
-- Tabella: data_quality_alerts
--   Storico degli alert generati da DataQualityAlerter quando un
--   DataQualityReport scende sotto soglia. Usata anche da CrossSourceValidator
--   per registrare discrepanze multi-sorgente.
--
-- Retention: 1 anno (Regola 31 — quality_reports → 1 anno).
-- =============================================================================

CREATE TABLE IF NOT EXISTS data_quality_alerts (
    alert_id      VARCHAR        NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
    series_id     VARCHAR        NOT NULL,  -- identificatore serie (ticker / series_id FRED)
    alert_kind    VARCHAR        NOT NULL,  -- 'quality_below_threshold' | 'cross_source_discrepancy'
    severity      VARCHAR        NOT NULL,  -- 'WARNING' | 'CRITICAL'
    quality_score DOUBLE,                   -- score al momento dell'alert (NULL se cross-source)
    threshold     DOUBLE,                   -- soglia violata
    detail        VARCHAR,                  -- descrizione testuale (max 500 char)
    source_a      VARCHAR,                  -- prima sorgente (per cross-source)
    source_b      VARCHAR,                  -- seconda sorgente (per cross-source)
    metric_name   VARCHAR,                  -- nome metrica (per cross-source: 'price', 'pe_ttm', ...)
    pct_diff      DOUBLE,                   -- discrepanza % (per cross-source)
    is_resolved   BOOLEAN        NOT NULL DEFAULT FALSE,
    resolved_at   TIMESTAMPTZ,
    created_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (alert_id)
);

-- Indice per query UI frequenti: alert recenti per serie
CREATE INDEX IF NOT EXISTS idx_dq_alerts_series_date
    ON data_quality_alerts (series_id, created_at DESC);

-- Indice per deduplication: verifica alert aperti nelle ultime 24h
CREATE INDEX IF NOT EXISTS idx_dq_alerts_kind_series_open
    ON data_quality_alerts (alert_kind, series_id, is_resolved, created_at DESC);
