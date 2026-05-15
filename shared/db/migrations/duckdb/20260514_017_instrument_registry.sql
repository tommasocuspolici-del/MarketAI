-- =============================================================================
-- Migration 017 — InstrumentRegistry: mapping instrument_id → ticker reale
-- ROADMAP_CODE_QUALITY_v1.0 — Blocco B, Settimana 4
-- Data: 2026-05-14
--
-- REGOLA 27: Ogni modifica schema DuckDB deve avere un migration SQL.
--            MAI modificare lo schema manualmente.
--
-- Problema risolto (P3 — Critica):
--   _INSTRUMENT_ID_TO_REAL_TICKER era un dict hardcoded in etoro_importer.py.
--   Il mapping viene spostato su DB per permettere aggiornamenti senza toccare
--   il codice e per supportare mapping risolti automaticamente via API.
--
-- Tabelle create:
--   · instrument_registry  — mapping instrument_id → ticker Yahoo Finance
--
-- Priorità lookup (dalla più alla meno fidato):
--   1. user_override  (impostato dall'utente nella UI)
--   2. manual         (seed da roadmap o inserimento verificato)
--   3. api_auto       (risolto automaticamente via /instruments endpoint)
--
-- ATTENZIONE: usa IF NOT EXISTS su ogni CREATE per garantire idempotenza.
-- =============================================================================

CREATE TABLE IF NOT EXISTS instrument_registry (
    instrument_id     INTEGER      NOT NULL,
    real_ticker       VARCHAR      NOT NULL,
    display_name      VARCHAR,
    native_currency   VARCHAR      NOT NULL DEFAULT 'USD',
    exchange          VARCHAR,
    isin              VARCHAR,
    asset_class_id    INTEGER,
    source            VARCHAR      NOT NULL,
    confidence        FLOAT        NOT NULL DEFAULT 1.0,
    last_verified_at  TIMESTAMPTZ,
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (instrument_id)
);

CREATE INDEX IF NOT EXISTS idx_instrument_registry_ticker
    ON instrument_registry (real_ticker);

CREATE INDEX IF NOT EXISTS idx_instrument_registry_isin
    ON instrument_registry (isin);

-- Seed: mappature storiche precedentemente hardcoded in etoro_importer.py.
-- Source = 'manual': inserite a mano, alta fiducia (confidence = 1.0).
-- ON CONFLICT DO NOTHING: idempotente, non sovrascrive mapping esistenti.
INSERT INTO instrument_registry
    (instrument_id, real_ticker, display_name, native_currency, exchange, isin, source, confidence)
VALUES
    (3040,  'SWDA.L',  'iShares Core MSCI World UCITS ETF',         'GBX', 'LSE',   'IE00B4L5Y983', 'manual', 1.0),
    (3434,  'CSPX.L',  'iShares Core S&P 500 UCITS ETF',            'GBX', 'LSE',   'IE00B5BMR087', 'manual', 1.0),
    (15435, 'EIMI.L',  'iShares Core MSCI EM IMI UCITS ETF',        'GBX', 'LSE',   'IE00BKM4GZ66', 'manual', 1.0),
    (3394,  'EUN5.DE', 'iShares EUR Corp Bond UCITS ETF',            'EUR', 'XETRA', 'IE00B3F81R35', 'manual', 1.0),
    (10569, 'IBCN.DE', 'iShares EUR Govt Bond 3-7yr UCITS ETF',     'EUR', 'XETRA', 'IE00B3VTML14', 'manual', 1.0)
ON CONFLICT (instrument_id) DO NOTHING;
