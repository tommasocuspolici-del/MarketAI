-- =============================================================================
-- Migration 011 — Fondamentali: EDGAR (income/balance sheet) + AV (valuation)
-- Roadmap v3.0 — Settimana 1: EDGAR Bulk + Alpha Vantage Premium
-- Data: 2026-09-01
--
-- REGOLA 27: Ogni modifica schema DuckDB deve avere un migration SQL.
--            MAI modificare lo schema manualmente.
--
-- Tabelle create:
--   · fundamentals_edgar     — dati income statement + balance sheet da SEC XBRL
--   · fundamentals_valuation — dati valutativi (P/E, EV/EBITDA, ecc.) da Alpha Vantage
--
-- ATTENZIONE: usa IF NOT EXISTS su ogni CREATE per garantire idempotenza.
-- =============================================================================

-- ─── Tabella 1: fondamentali EDGAR (income + balance sheet) ─────────────────
-- Sorgente: SEC EDGAR XBRL companyfacts API
-- Aggiornamento: domenica 06:00 UTC (job edgar_fundamentals)
-- Retention: 20 anni (Regola 31)
CREATE TABLE IF NOT EXISTS fundamentals_edgar (
    ticker        VARCHAR        NOT NULL,
    report_date   TIMESTAMPTZ    NOT NULL,   -- data fine periodo (period_end)
    period        VARCHAR        NOT NULL,   -- 'Q1'|'Q2'|'Q3'|'Q4'|'FY'
    -- Income Statement
    revenue       DOUBLE,
    gross_profit  DOUBLE,
    ebit          DOUBLE,                   -- Operating Income (Earnings Before Interest & Tax)
    net_income    DOUBLE,
    eps_diluted   DOUBLE,                   -- Earnings Per Share diluito
    -- Balance Sheet
    total_assets  DOUBLE,
    total_debt    DOUBLE,                   -- debito totale (LT + ST)
    equity        DOUBLE,                   -- patrimonio netto (stockholders equity)
    fcf           DOUBLE,                   -- Free Cash Flow = OpCF - CapEx
    -- Metadati
    source        VARCHAR        NOT NULL DEFAULT 'edgar_xbrl',
    fetched_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, report_date, period)
);

-- Indice per query frequenti: dati recenti per ticker
CREATE INDEX IF NOT EXISTS idx_fundamentals_edgar_ticker_date
    ON fundamentals_edgar (ticker, report_date DESC);

-- ─── Tabella 2: fondamentali valutativi Alpha Vantage ───────────────────────
-- Sorgente: Alpha Vantage OVERVIEW + INCOME_STATEMENT + BALANCE_SHEET endpoints
-- Aggiornamento: lunedì 07:30 UTC (job av_fundamentals)
-- Retention: 20 anni (Regola 31)
CREATE TABLE IF NOT EXISTS fundamentals_valuation (
    ticker         VARCHAR        NOT NULL,
    computed_at    TIMESTAMPTZ    NOT NULL,  -- timestamp del calcolo/fetch
    -- Valuation ratios (OVERVIEW endpoint)
    pe_ttm         DOUBLE,                  -- P/E trailing twelve months
    pe_forward     DOUBLE,                  -- P/E forward (analyst estimate)
    pb             DOUBLE,                  -- Price-to-Book
    ps             DOUBLE,                  -- Price-to-Sales
    ev_ebitda      DOUBLE,                  -- Enterprise Value / EBITDA
    dividend_yield DOUBLE,                  -- Dividend Yield (0..1)
    payout_ratio   DOUBLE,                  -- Payout Ratio (0..1)
    beta           DOUBLE,                  -- Beta di mercato
    market_cap     DOUBLE,                  -- Market Capitalization (USD)
    -- Metadati
    source         VARCHAR        NOT NULL DEFAULT 'alpha_vantage',
    fetched_at     TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, computed_at)
);

-- Indice per query frequenti: ultima valutazione per ticker
CREATE INDEX IF NOT EXISTS idx_fundamentals_valuation_ticker_date
    ON fundamentals_valuation (ticker, computed_at DESC);

-- ─── Nota di compatibilità ───────────────────────────────────────────────────
-- fundamentals_edgar coesiste con la tabella legacy `fundamentals` (migration 001)
-- che archivia dati grezzi EdgarFact (non aggregati per periodo).
-- Questa tabella contiene valori già aggregati pronti per la UI.
