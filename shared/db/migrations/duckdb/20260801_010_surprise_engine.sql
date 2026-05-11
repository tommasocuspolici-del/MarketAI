-- ═══════════════════════════════════════════════════════════════════════════
-- Migration: 20260801_010_surprise_engine
-- Roadmap Analisi/Previsione v1.0 — Blocco C: Economic Surprise Engine
--
-- Tabelle create:
--   · economic_consensus     - Dati consensus + actual per indicatore
--   · sector_surprise_index  - Indice sorpresa aggregato per settore
--   · surprise_signal        - Segnale [-1,1] per CompositeSignalAggregator
--   · surprise_accuracy_log  - Storico accuratezza per autocalibrazione
--
-- Regola 27: ogni modifica schema DuckDB → script SQL in migrations/duckdb/
-- ═══════════════════════════════════════════════════════════════════════════

-- ─── ECONOMIC CONSENSUS ──────────────────────────────────────────────────────
-- Fonte: Econoday/Investing.com scraping o input manuale
CREATE TABLE IF NOT EXISTS economic_consensus (
    release_date       DATE        NOT NULL,
    indicator_code     VARCHAR     NOT NULL,   -- Es. 'NFP', 'CPI_YOY', 'ISM_MFG'
    sector             VARCHAR     NOT NULL,   -- 'labour'|'growth'|'inflation'|'housing'|'trade_external'
    consensus_value    DOUBLE,                 -- Previsione mediana analisti
    actual_value       DOUBLE,                 -- Valore pubblicato
    prior_value        DOUBLE,                 -- Valore del mese precedente
    surprise_raw       DOUBLE,                 -- actual - consensus
    surprise_std       DOUBLE,                 -- σ storica delle sorprese per indicatore
    surprise_z         DOUBLE,                 -- surprise_raw / surprise_std (normalizzato)
    source             VARCHAR,                -- 'econoday'|'bloomberg_manual'|'investing_com'
    PRIMARY KEY (release_date, indicator_code)
);

CREATE INDEX IF NOT EXISTS idx_economic_consensus_sector
    ON economic_consensus (sector, release_date DESC);

CREATE INDEX IF NOT EXISTS idx_economic_consensus_code
    ON economic_consensus (indicator_code, release_date DESC);

-- ─── SECTOR SURPRISE INDEX ───────────────────────────────────────────────────
-- Indice aggregato per settore (media pesata z-score ultimi 3 mesi)
CREATE TABLE IF NOT EXISTS sector_surprise_index (
    snapshot_date      DATE        NOT NULL,
    sector             VARCHAR     NOT NULL,
    surprise_index     DOUBLE,                 -- Media pesata z-score [-3, 3]
    momentum_1m        DOUBLE,                 -- Variazione mensile dell'indice
    momentum_3m        DOUBLE,                 -- Variazione trimestrale
    regime             VARCHAR,                -- 'positive_surprise'|'negative_surprise'|'neutral'
    beat_count         INTEGER,                -- Indicatori che hanno battuto consensus
    miss_count         INTEGER,
    data_points        INTEGER,                -- Numero indicatori aggregati
    PRIMARY KEY (snapshot_date, sector)
);

CREATE INDEX IF NOT EXISTS idx_sector_surprise_snapshot
    ON sector_surprise_index (snapshot_date DESC);

-- ─── SURPRISE SIGNAL ─────────────────────────────────────────────────────────
-- Segnale aggregato per CompositeSignalAggregator v2
CREATE TABLE IF NOT EXISTS surprise_signal (
    generated_at       TIMESTAMPTZ NOT NULL,
    signal_value       DOUBLE,                 -- [-1, 1] per composite
    dominant_sector    VARCHAR,                -- Settore con impatto maggiore
    beat_count         INTEGER,                -- Totale indicatori sopra consensus
    miss_count         INTEGER,
    PRIMARY KEY (generated_at)
);

-- ─── SURPRISE ACCURACY LOG ───────────────────────────────────────────────────
-- Storico accuratezza per autocalibrazione (hit rate direzione consensus)
CREATE TABLE IF NOT EXISTS surprise_accuracy_log (
    indicator_code     VARCHAR     NOT NULL,
    period_start       DATE        NOT NULL,
    period_end         DATE        NOT NULL,
    mean_abs_surprise  DOUBLE,                 -- MAE medio delle sorprese
    hit_rate_direction DOUBLE,                 -- % volte consensus aveva direzione giusta
    PRIMARY KEY (indicator_code, period_start)
);
