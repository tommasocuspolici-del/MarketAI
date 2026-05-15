# MarketAI — Roadmap Analisi Mercato v4
## Labour Market Data · Signal Quality · P/E Ratio · Correlation Engine v2
### Versione 4.0 — Maggio 2026
> Estende: ROADMAP_v6.0 · ROADMAP_UNIFICATA_v2.0 · ROADMAP_ANALISI_PREVISIONE_v1.0  
> Segue le 32 convenzioni obbligatorie v6.0  
> Baseline: **v7.2.0 (131 test passing)**  
> Obiettivo: trasformare MarketAI in uno strumento di **vantaggio informativo professionale**

---

## VISIONE STRATEGICA

Questa roadmap porta MarketAI dal livello "piattaforma analitica avanzata" al livello  
**"strumento di calcolo professionale da investment bank"**, su quattro assi:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  ASSE 1 — LABOUR MARKET ENGINE                                                  │
│  Dati reali JOLTS/BLS/Claims → DB → Engine → Segnali predittivi di ciclo       │
│                                                                                  │
│  ASSE 2 — SIGNAL QUALITY ENGINE                                                 │
│  Composite Signal v2 · Economic Surprise · 7 componenti pesati · validazione   │
│                                                                                  │
│  ASSE 3 — VALUATION ENGINE (P/E RATIO MULTI-INDICATORE)                        │
│  Trailing · Forward · Shiller CAPE · ERP · Multi-indicator dashboard            │
│                                                                                  │
│  ASSE 4 — CORRELATION ENGINE v2                                                 │
│  DCC-GARCH reale · Regime-conditioned · Lead-lag operativo · Cross-asset        │
└─────────────────────────────────────────────────────────────────────────────────┘
```

**Filosofia di progettazione (ispirata a sistemi Bloomberg / Goldman / JPMorgan):**
- I segnali non descrivono il presente: **anticipano il futuro** (lead indicators)
- Ogni metrica è sempre contestualizzata (regime attuale, z-score storico, percentile)
- Nessun indicatore esiste in isolamento: tutto confluisce in un **Composite View**
- I modelli di correlazione devono essere **regime-conditioned** (non statici)
- Il P/E ratio ha senso solo confrontato con tassi, ERP e ciclo degli utili

---

## MAPPA DELLE DIPENDENZE

```
┌──────────────────────────────────────────────────────────────────────┐
│                    BASELINE: v7.2.0 (131 test)                       │
│  DuckDB · SQLite · Sentiment Engine · Backtesting · StressTesting    │
│  CorrelationAnalyzer (DCC-GARCH-lite) · FRED fetcher · yfinance      │
│  SEC EDGAR fetcher · EtoroImporter · InvestorProfile bridge          │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
         ┌───────────────────┼───────────────────┬──────────────────┐
         ▼                   ▼                   ▼                  ▼
  ┌────────────┐    ┌─────────────────┐  ┌──────────────┐  ┌──────────────┐
  │  BLOCCO 1  │    │    BLOCCO 2     │  │  BLOCCO 3    │  │  BLOCCO 4    │
  │  Labour    │    │  Signal Quality │  │  Valuation   │  │ Correlation  │
  │  Market    │    │  + Composite v2 │  │  Engine P/E  │  │  Engine v2   │
  │  Data+DB   │    │  + Surprise Eng │  │              │  │  DCC-GARCH   │
  │  Sett. 1-3 │    │  Sett. 4-5     │  │  Sett. 6-7   │  │  Sett. 8-9  │
  └──────┬─────┘    └───────┬─────────┘  └──────┬───────┘  └──────┬───────┘
         │                  │                    │                  │
         └──────────────────┴────────────────────┴──────────────────┘
                                        │
                              ┌─────────▼──────────┐
                              │    BLOCCO 5         │
                              │  UI Integration +   │
                              │  Dashboard Upgrade  │
                              │  Sett. 10-11        │
                              └─────────┬───────────┘
                                        │
                              ┌─────────▼──────────┐
                              │    BLOCCO 6         │
                              │  Test · Hardening   │
                              │  Benchmark · CI     │
                              │  Sett. 12           │
                              └────────────────────┘
```

**Regola di sequenza:**  
I blocchi 1-4 sono **parallelizzabili** in sessioni separate (non hanno dipendenze circolari).  
Il blocco 5 richiede che almeno blocco 1 e blocco 3 siano al 90%.  
Il blocco 6 richiede che tutti i blocchi precedenti abbiano superato i rispettivi DoD.

---

## STRUTTURA DIRECTORY — NUOVI MODULI

```
market_ai/
│
├── engine/
│   ├── analytics/
│   │   ├── labour_market/                    ★ BLOCCO 1 — Implementazione ANALISI_PREVISIONE_v1
│   │   │   ├── __init__.py
│   │   │   ├── schemas.py                    # Pandera schemas: JOLTS, Claims, Payroll, Regime
│   │   │   ├── jolts_fetcher.py              # FRED fetch: JOLTS mensile (12 serie FRED)
│   │   │   ├── claims_fetcher.py             # FRED fetch: IC, CC, insured_rate settimanale
│   │   │   ├── payroll_fetcher.py            # BLS/FRED fetch: NFP totale + 12 settori
│   │   │   ├── jolts_analyzer.py             # Beveridge curve, quits rate segnali
│   │   │   ├── claims_cycle_detector.py      # 4wk MA + regime expansion/contraction/peak
│   │   │   ├── payroll_decomposer.py         # Cyclical vs defensive, revisions tracker
│   │   │   ├── labour_regime_classifier.py   # Regime: tight/balanced/slack/deteriorating
│   │   │   └── labour_forecast_engine.py     # ARIMA+Ridge forecast 1M/3M/6M orizzonte
│   │   │
│   │   ├── valuation/                        ★ BLOCCO 3 — NUOVO
│   │   │   ├── __init__.py
│   │   │   ├── schemas.py                    # Pandera schemas: EPS, PE, CAPE, ERP
│   │   │   ├── earnings_fetcher.py           # SEC EDGAR: EPS trailing 4Q, YoY growth
│   │   │   ├── forward_estimates_fetcher.py  # Alpha Vantage/FRED: forward EPS consensus
│   │   │   ├── shiller_cape_fetcher.py       # Shiller CAPE via URL pubblico + FRED CAPE
│   │   │   ├── pe_calculator.py             # Trailing PE, Forward PE, Shiller CAPE
│   │   │   ├── equity_risk_premium.py       # ERP = Earnings Yield - Risk-Free Rate
│   │   │   ├── pe_context_builder.py        # Percentile storico + regime label
│   │   │   └── valuation_signal_generator.py # Segnale [-1,1]: cheap/fair/expensive
│   │   │
│   │   ├── surprise_engine/                  ★ BLOCCO 2 — da ANALISI_PREVISIONE_v1
│   │   │   ├── __init__.py
│   │   │   ├── schemas.py
│   │   │   ├── consensus_loader.py           # Investing.com scraping + manual YAML fallback
│   │   │   ├── surprise_calculator.py        # z-score: (actual - consensus) / σ_storica
│   │   │   ├── sector_surprise_aggregator.py # 4 settori: labour/growth/inflation/housing
│   │   │   ├── surprise_momentum.py          # Trend sorprese: EMA di z-score
│   │   │   └── surprise_signal_generator.py  # Segnale [-1,1] per Composite
│   │   │
│   │   ├── correlation/                      ★ BLOCCO 4 — UPGRADE MAJOR
│   │   │   ├── __init__.py
│   │   │   ├── analyzer.py                   # ESISTENTE — esteso (non riscritto)
│   │   │   ├── regime_detector.py            # ESISTENTE — integrato con DCC-GARCH
│   │   │   ├── dcc_garch.py                  # NUOVO: DCC-GARCH via arch library (feature-flagged)
│   │   │   ├── dcc_ewma_enhanced.py          # NUOVO: EWMA enhanced con decay ottimale
│   │   │   ├── lead_lag_analyzer.py          # NUOVO: Granger causality + cross-corr avanzata
│   │   │   ├── cross_asset_matrix.py         # NUOVO: matrice cross-asset regime-conditioned
│   │   │   └── correlation_signal_generator.py # NUOVO: segnale da regime correlazioni
│   │   │
│   │   └── technical/                        ★ BLOCCO 2 — ottimizzazioni signal
│   │       ├── volume_analyzer.py            # OBV, CMF, VWAP vettorizzati
│   │       └── divergence_detector.py        # RSI/MACD divergenze
│   │
│   └── alpha_generation/
│       └── composite_signal_v2.py            ★ BLOCCO 2 — 7 componenti pesati
│
├── shared/
│   └── db/
│       └── migrations/
│           └── duckdb/
│               ├── 20260701_008_labour_market.sql      ★ BLOCCO 1
│               ├── 20260701_009_surprise_engine.sql    ★ BLOCCO 2
│               ├── 20260715_010_valuation_pe.sql       ★ BLOCCO 3
│               └── 20260715_011_correlation_v2.sql     ★ BLOCCO 4
│
├── presentation/
│   └── dashboard_engine/
│       └── pages/
│           ├── M3_Labour_Market.py           ★ BLOCCO 5 (era placeholder)
│           ├── M5_Economic_Surprise.py       ★ BLOCCO 5 (nuova)
│           ├── M6_Valuation_PE.py            ★ BLOCCO 5 (nuova)
│           ├── Q9_Labour_Forecasting.py      ★ BLOCCO 5 (nuova)
│           ├── Q10_Surprise_Heatmap.py       ★ BLOCCO 5 (nuova)
│           └── E8_Correlations.py            ★ BLOCCO 5 (upgrade)
│
├── tests/
│   ├── engine/
│   │   ├── test_labour_market/               ★ BLOCCO 6
│   │   ├── test_valuation/                   ★ BLOCCO 6
│   │   ├── test_surprise_engine/             ★ BLOCCO 6
│   │   └── test_correlation_v2/              ★ BLOCCO 6
│   └── integration/
│       ├── test_composite_signal_v2.py       ★ BLOCCO 6
│       └── test_valuation_pipeline.py        ★ BLOCCO 6
│
└── config/
    ├── labour_market.yaml                    ★ BLOCCO 1
    ├── surprise_engine.yaml                  ★ BLOCCO 2
    ├── valuation.yaml                        ★ BLOCCO 3
    ├── correlation_v2.yaml                   ★ BLOCCO 4
    └── feature_flags.yaml                    # Aggiornato
```

---

## MIGRATIONS DUCKDB — NUOVE TABELLE

### Migration 008 — Labour Market (BLOCCO 1)

```sql
-- shared/db/migrations/duckdb/20260701_008_labour_market.sql

-- Dati JOLTS mensili (FRED: JTSJOL, JTSQUL, JTSHIL, JTSLAL, JTSLDL)
CREATE TABLE IF NOT EXISTS jolts_monthly (
    series_date        DATE        NOT NULL,
    job_openings       DOUBLE,      -- Migliaia, destagionalizzato (JTSJOL)
    hires              DOUBLE,      -- (JTSHIL)
    quits              DOUBLE,      -- (JTSQUL)
    layoffs_discharges DOUBLE,      -- (JTSLAL + JTSLEL)
    quits_rate         DOUBLE,      -- % su occupazione totale (JTSQUR)
    openings_rate      DOUBLE,      -- % (JTSJOR)
    hires_rate         DOUBLE,      -- % (JTSHIR)
    layoffs_rate       DOUBLE,      -- % (JTSLDR)
    beveridge_gap      DOUBLE,      -- openings_rate - unemployment_rate
    beveridge_regime   VARCHAR,     -- 'tight' | 'normal' | 'slack' (classificazione)
    fetched_at         TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (series_date)
);

-- Claims settimanali con MA e regime
CREATE TABLE IF NOT EXISTS claims_cycle (
    week_ending        DATE        NOT NULL,
    initial_claims     INTEGER,     -- Migliaia (ICSA)
    continuing_claims  INTEGER,     -- Migliaia (CCSA)
    insured_unemp_rate DOUBLE,      -- (IURSA) %
    claims_4wk_ma      DOUBLE,      -- Media mobile 4 settimane
    claims_yoy_pct     DOUBLE,      -- Variazione anno su anno %
    claims_26wk_trend  DOUBLE,      -- Pendenza regressione lineare 26 settimane
    cycle_regime       VARCHAR,     -- 'expansion'|'peak'|'contraction'|'trough'
    signal_strength    DOUBLE,      -- [-1, 1]: -1 = labour molto debole
    signal_confidence  DOUBLE,      -- [0, 1]: confidence del regime
    fetched_at         TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (week_ending)
);

-- NFP per settore + revisioni
CREATE TABLE IF NOT EXISTS payroll_sector (
    release_date       DATE        NOT NULL,
    sector             VARCHAR     NOT NULL,  -- 'total_nonfarm'|'manufacturing'|'services'|...
    jobs_added_k       DOUBLE,      -- Migliaia posti netti aggiunti
    prev_month_revised DOUBLE,      -- Revisione mese precedente
    two_month_revision DOUBLE,      -- Revisione cumulativa 2 mesi
    yoy_pct            DOUBLE,      -- Crescita anno su anno %
    share_of_total     DOUBLE,      -- % su total nonfarm
    is_cyclical        BOOLEAN,     -- True: manufacturing, construction, retail
    PRIMARY KEY (release_date, sector)
);

-- Regime mercato del lavoro (classificazione sintetica)
CREATE TABLE IF NOT EXISTS labour_regime (
    assessment_date    DATE        NOT NULL,
    regime             VARCHAR     NOT NULL,  -- 'tight'|'balanced'|'slack'|'deteriorating'
    regime_score       DOUBLE,     -- [-1, 1]: +1 = labour markets ultra-tight
    jolts_signal       DOUBLE,     -- Contributo JOLTS al regime score
    claims_signal      DOUBLE,     -- Contributo Claims al regime score
    payroll_signal     DOUBLE,     -- Contributo Payroll al regime score
    unrate_signal      DOUBLE,     -- Contributo disoccupazione al regime score
    regime_duration_weeks INTEGER, -- Settimane consecutive nello stesso regime
    recession_prob_6m  DOUBLE,     -- Probabilità recessione a 6 mesi (modello probit)
    data_sources_count INTEGER,    -- Quante fonti disponibili (data quality proxy)
    fetched_at         TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (assessment_date)
);

-- Forecasting orizzonte 1M/3M/6M
CREATE TABLE IF NOT EXISTS labour_forecast (
    forecast_date      DATE        NOT NULL,  -- Data di produzione del forecast
    target_variable    VARCHAR     NOT NULL,  -- 'UNRATE'|'NFP'|'JOLTS_OPENINGS'|'CLAIMS_4WK'
    horizon_months     INTEGER     NOT NULL,  -- 1, 3, 6
    predicted_value    DOUBLE      NOT NULL,
    ci_lower_90        DOUBLE,     -- Intervallo confidenza 90% lower
    ci_upper_90        DOUBLE,     -- Intervallo confidenza 90% upper
    model_used         VARCHAR,    -- 'ARIMA'|'RIDGE'|'ENSEMBLE'
    rmse_oos           DOUBLE,     -- RMSE out-of-sample walk-forward
    PRIMARY KEY (forecast_date, target_variable, horizon_months)
);
```

### Migration 009 — Economic Surprise Engine (BLOCCO 2)

```sql
-- shared/db/migrations/duckdb/20260701_009_surprise_engine.sql

-- Dati consensus + actual per indicatore
CREATE TABLE IF NOT EXISTS economic_surprise (
    release_date       DATE        NOT NULL,
    indicator_code     VARCHAR     NOT NULL,  -- 'NFP'|'CPI_YOY'|'JOLTS'|'ISM_MFG'|...
    sector             VARCHAR     NOT NULL,  -- 'labour'|'growth'|'inflation'|'housing'|'sentiment'
    actual_value       DOUBLE,
    consensus_value    DOUBLE,
    prior_value        DOUBLE,
    surprise_raw       DOUBLE,     -- actual - consensus
    sigma_historical   DOUBLE,     -- σ storica della serie (rolling 36 mesi)
    z_score            DOUBLE,     -- surprise_raw / sigma_historical
    data_source        VARCHAR,    -- 'investing_com'|'manual_yaml'|'bloomberg_fallback'
    release_at         TIMESTAMPTZ,
    PRIMARY KEY (release_date, indicator_code)
);

-- Aggregazione sorprese per settore (EMA pesata)
CREATE TABLE IF NOT EXISTS surprise_sector_score (
    score_date         DATE        NOT NULL,
    sector             VARCHAR     NOT NULL,
    score_ema          DOUBLE,     -- EMA 3 mesi dei z-score del settore
    score_momentum     DOUBLE,     -- Δ score_ema su 4 settimane (accelerazione)
    direction          VARCHAR,    -- 'improving'|'deteriorating'|'stable'
    indicators_count   INTEGER,    -- N indicatori in quel settore
    PRIMARY KEY (score_date, sector)
);

-- Segnale aggregato Economic Surprise Index (ESI)
CREATE TABLE IF NOT EXISTS economic_surprise_index (
    index_date         DATE        NOT NULL,
    esi_composite      DOUBLE,     -- [-1, 1]: media pesata settori
    esi_signal         DOUBLE,     -- Segnale per Composite: esi_composite normalizzato
    labour_weight      DOUBLE DEFAULT 0.30,
    growth_weight      DOUBLE DEFAULT 0.30,
    inflation_weight   DOUBLE DEFAULT 0.25,
    housing_weight     DOUBLE DEFAULT 0.15,
    PRIMARY KEY (index_date)
);
```

### Migration 010 — Valuation P/E (BLOCCO 3)

```sql
-- shared/db/migrations/duckdb/20260715_010_valuation_pe.sql

-- EPS trailing (rolling 4Q) e forward da stime
CREATE TABLE IF NOT EXISTS earnings_data (
    ticker             VARCHAR     NOT NULL,   -- 'SPY'|'QQQ'|'^GSPC'|...
    period_end         DATE        NOT NULL,
    eps_trailing_4q    DOUBLE,     -- Somma ultimi 4 quarter EPS diluiti
    eps_forward_1y     DOUBLE,     -- Stima consenso analysts prossimi 12M
    eps_growth_yoy     DOUBLE,     -- Crescita EPS anno su anno %
    eps_revision_3m    DOUBLE,     -- Revisione al rialzo/ribasso stime ultiml 90gg
    revenue_growth_yoy DOUBLE,
    operating_margin   DOUBLE,
    data_source        VARCHAR,    -- 'sec_edgar'|'alpha_vantage'|'fred'
    fetched_at         TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (ticker, period_end)
);

-- Metriche P/E calcolate (snapshot giornaliero)
CREATE TABLE IF NOT EXISTS pe_metrics (
    metric_date        DATE        NOT NULL,
    ticker             VARCHAR     NOT NULL,
    price              DOUBLE      NOT NULL,
    trailing_pe        DOUBLE,     -- Price / EPS trailing 4Q
    forward_pe         DOUBLE,     -- Price / EPS forward 12M
    shiller_cape       DOUBLE,     -- Price / EPS reale media 10 anni
    peg_ratio          DOUBLE,     -- Forward PE / EPS growth rate (5Y)
    -- Contestualizzazione storica (z-score e percentile rolling 20 anni)
    trailing_pe_zscore DOUBLE,     -- (PE - mean_20y) / std_20y
    forward_pe_zscore  DOUBLE,
    cape_zscore        DOUBLE,
    trailing_pe_pct    DOUBLE,     -- Percentile storico [0,100]
    forward_pe_pct     DOUBLE,
    cape_pct           DOUBLE,
    -- Equity Risk Premium
    erp_implied        DOUBLE,     -- Earnings Yield (1/ForwardPE) - DGS10
    erp_regime         VARCHAR,    -- 'attractive'|'fair'|'expensive'|'extreme'
    fetched_at         TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (metric_date, ticker)
);

-- Storico CAPE Shiller (serie lunga: 1881-oggi)
CREATE TABLE IF NOT EXISTS shiller_cape_historical (
    data_date          DATE        NOT NULL,
    sp500_price        DOUBLE,
    eps_10y_real_avg   DOUBLE,     -- Media reale 10Y CPI-adjusted
    cape_ratio         DOUBLE,
    bond_yield         DOUBLE,     -- US 10Y yield contemporaneo
    erp_implied        DOUBLE,     -- Earnings yield - bond yield
    PRIMARY KEY (data_date)
);

-- Segnale valuation composito
CREATE TABLE IF NOT EXISTS valuation_signal (
    signal_date        DATE        NOT NULL,
    ticker             VARCHAR     NOT NULL,
    valuation_score    DOUBLE,     -- [-1, 1]: +1=molto sottovalutato, -1=molto sopravvalutato
    trailing_pe_signal DOUBLE,     -- Componente trailing PE
    forward_pe_signal  DOUBLE,     -- Componente forward PE
    cape_signal        DOUBLE,     -- Componente CAPE
    erp_signal         DOUBLE,     -- Componente ERP
    label              VARCHAR,    -- 'deep_value'|'fair_value'|'stretched'|'bubble_warning'
    PRIMARY KEY (signal_date, ticker)
);
```

### Migration 011 — Correlation Engine v2 (BLOCCO 4)

```sql
-- shared/db/migrations/duckdb/20260715_011_correlation_v2.sql

-- Matrici DCC-GARCH (snapshot settimanale)
CREATE TABLE IF NOT EXISTS dcc_garch_matrix (
    snapshot_date      DATE        NOT NULL,
    asset_a            VARCHAR     NOT NULL,
    asset_b            VARCHAR     NOT NULL,
    dcc_correlation    DOUBLE,     -- Correlazione DCC-GARCH dinamica
    ewma_correlation   DOUBLE,     -- EWMA fallback (sempre disponibile)
    static_correlation DOUBLE,     -- Pearson 252gg
    regime_label       VARCHAR,    -- 'bull'|'bear'|'stress'|'transition'
    correlation_regime VARCHAR,    -- 'high_corr'|'normal'|'decorrelated'|'negative'
    decay_lambda       DOUBLE,     -- Parametro decay EWMA ottimale (MLE)
    PRIMARY KEY (snapshot_date, asset_a, asset_b)
);

-- Lead-lag analysis
CREATE TABLE IF NOT EXISTS lead_lag_signals (
    analysis_date      DATE        NOT NULL,
    leader_asset       VARCHAR     NOT NULL,
    follower_asset     VARCHAR     NOT NULL,
    optimal_lag_days   INTEGER,    -- Lag ottimale in giorni trading [1-60]
    granger_f_stat     DOUBLE,     -- F-statistica test Granger
    granger_pvalue     DOUBLE,     -- p-value test Granger (< 0.05 = causalità)
    cross_corr_peak    DOUBLE,     -- Picco cross-correlazione al lag ottimale
    is_significant     BOOLEAN,    -- True se pvalue < 0.05 AND |corr| > 0.3
    lead_signal        VARCHAR,    -- 'bullish_lead'|'bearish_lead'|'neutral'
    PRIMARY KEY (analysis_date, leader_asset, follower_asset)
);

-- Regime correlazioni cross-asset (overview)
CREATE TABLE IF NOT EXISTS cross_asset_regime (
    regime_date        DATE        NOT NULL,
    avg_equity_bond_corr  DOUBLE,  -- Stock-bond correlation media (chiave per risk parity)
    avg_equity_gold_corr  DOUBLE,
    avg_equity_fx_corr    DOUBLE,
    credit_equity_corr    DOUBLE,  -- HY vs equity
    vix_correlation_regime VARCHAR, -- 'crisis_coupling'|'normal'|'divergence'
    diversification_score DOUBLE,  -- [0,1]: 1=portfolio max diversificato
    correlation_signal    DOUBLE,  -- [-1,1]: per Composite Signal
    PRIMARY KEY (regime_date)
);
```

---

## BLOCCO 1 — Labour Market Data Ingest + Engine Validation
**Settimane 1-3 | Dipende da: baseline v7.2.0**

### 1.1 — Fetcher FRED per Labour Market

#### `engine/analytics/labour_market/jolts_fetcher.py`

```python
# Fetcher per dati JOLTS via FRED API
# Serie FRED target: JTSJOL (openings), JTSHIL (hires), JTSQUL (quits),
#                    JTSLAL (layoffs), JTSQUR (quits rate), JTSJOR (openings rate),
#                    JTSHIR (hires rate), JTSLDR (layoffs rate)

class JOLTSFetcher(BaseMacroFetcher):
    """Fetch mensile JOLTS via FRED; pipeline invariabile Rule 12."""
    
    FRED_SERIES: dict[str, str] = {
        "JTSJOL": "job_openings",        # Job openings, thousands
        "JTSQUL": "quits",               # Quits level
        "JTSHIL": "hires",               # Hires level
        "JTSLAL": "layoffs_discharges",  # Layoffs & discharges
        "JTSQUR": "quits_rate",          # Quits rate %
        "JTSJOR": "openings_rate",       # Openings rate %
        "JTSHIR": "hires_rate",          # Hires rate %
        "JTSLDR": "layoffs_rate",        # Layoffs rate %
    }
    
    # Beveridge Gap calcolato internamente: openings_rate - UNRATE (FRED)
    # Utile come segnale lead: openings rate alta + bassa disoccupazione = labor tight
```

#### `engine/analytics/labour_market/claims_fetcher.py`

```python
# Serie FRED: ICSA (initial claims), CCSA (continuing claims),
#             IURSA (insured unemployment rate)
# Frequenza: settimanale (ogni giovedì)
# Note importanti:
#   - Holiday adjustments: holiday weeks → forward fill con flag
#   - Revision: FRED aggiorna i dati pregressi; usare sempre ultime revisioni

class ClaimsFetcher(BaseMacroFetcher):
    """Fetch settimanale initial+continuing claims da FRED."""
    
    FRED_SERIES: dict[str, str] = {
        "ICSA":  "initial_claims",      # Thousands, seasonally adjusted
        "CCSA":  "continuing_claims",   # Thousands, seasonally adjusted
        "IURSA": "insured_unemp_rate",  # %, seasonally adjusted
    }
    
    # 4wk MA calcolata post-fetch: claims_4wk_ma = rolling(4).mean()
    # YoY: claims_yoy_pct = (current / year_ago - 1) * 100
    # 26wk trend: pendenza regressione lineare (polyfit degree=1) normalizzata
```

#### `engine/analytics/labour_market/payroll_fetcher.py`

```python
# FRED series per NFP settoriale:
# PAYEMS (total), MANEMP (manufacturing), USCONS (construction),
# USMINE (mining), USTPU (trade/transport/utilities), USINFO (information),
# USFIRE (financial), USPBS (professional/business), USEHS (health/edu),
# USLAH (leisure/hospitality), USGOVT (government), CES7000000001 (other services)

class PayrollFetcher(BaseMacroFetcher):
    """Fetch NFP per settore + total da FRED.
    
    Calcola automaticamente:
    - Revisioni: (current - prior_release) per ogni settore
    - Cyclical vs defensive: manufacturing, construction, retail = cyclical
    - YoY growth rate per settore
    - Share of total nonfarm payrolls
    """
```

### 1.2 — Labour Market Analyzers

#### `engine/analytics/labour_market/jolts_analyzer.py`

**Logica chiave (investment bank standard):**

```
Beveridge Curve Analysis:
  - Normale: alto openings + bassa disoccupazione → economia sana
  - Problema: alto openings + alta disoccupazione → mismatch strutturale
  - Recessione entry: openings in calo rapido + disoccupazione in salita
  
Segnali predittivi da JOLTS:
  1. Quits Rate > 2.5%: workers confident → economy strong (lead +3M)
  2. Openings Rate MoM change: proxy domanda lavoro futura (lead +1-2M)
  3. Hires Rate / Openings Rate ratio: efficienza mercato (lead +2M)
  4. Layoffs Rate spikes: recessione imminente (lead +0-1M, alta affidabilità)
```

**Output `JOLTSSignal`:**

```python
@dataclass(frozen=True)
class JOLTSSignal:
    """Segnale sintetico da analisi JOLTS."""
    signal_date: pd.Timestamp
    quits_signal: np.float64        # [-1,1]: quits rate vs storico
    openings_signal: np.float64     # [-1,1]: openings trend
    beveridge_regime: str           # 'tight'|'normal'|'slack'
    composite_labour_signal: np.float64  # Aggregato pesato
    lead_months: int                # Orizonte predittivo stimato
    quality_score: np.float64       # DataQualityReport.score
```

#### `engine/analytics/labour_market/claims_cycle_detector.py`

**Logica regime (empirica su dati storici NBER):**

```
Threshold calibrate su dati 1970-2025:
  EXPANSION:    claims_4wk_ma < 300K AND yoy_pct < +10%
  PEAK:         claims_4wk_ma in [300K-350K] OR yoy_pct in [10%-20%]
  CONTRACTION:  claims_4wk_ma > 350K OR yoy_pct > +20%
  TROUGH:       claims_4wk_ma calante dopo peak > 400K

Segnale lead recessione:
  - 4wk MA claims +15% YoY per 4+ settimane consecutive → recession warning
  - Historical lead time: 3-6 mesi (media 4.2M su 8 recessioni NBER 1970-2020)
  
Output: signal_strength = f(regime, trend, spike_indicator)
  - expansion: +0.5 to +1.0
  - peak:       -0.1 to +0.3
  - contraction: -1.0 to -0.4
  - trough:     -0.5 to 0.0
```

#### `engine/analytics/labour_market/labour_regime_classifier.py`

**Classificatore sintetico (4 regime):**

```
Inputs pesati:
  jolts_signal      weight=0.35  (openings + quits composite)
  claims_signal     weight=0.30  (4wk MA + yoy trend)
  payroll_signal    weight=0.25  (NFP trend + sector decomp)
  unrate_signal     weight=0.10  (UNRATE level vs natural rate NROU)

Regime boundaries (regime_score ∈ [-1, +1]):
  TIGHT:        score > +0.4   → inflationary pressure, Fed hawkish risk
  BALANCED:     score ∈ [-0.1, +0.4] → equilibrio, crescita sostenibile
  SLACK:        score ∈ [-0.5, -0.1] → sottoutilizzo lavoro
  DETERIORATING: score < -0.5  → warning pre-recessione

Recession probability (probit model):
  P(recession_6m) = probit(α + β1*claims_yoy + β2*UNRATE_change + β3*jolts_quits_change)
  Coefficienti calibrati su 1970-2024 (OLS pre-training)
```

#### `engine/analytics/labour_market/labour_forecast_engine.py`

**Modelli di forecasting:**

```
Per ogni variabile target (UNRATE, NFP_Total, JOLTS_Openings, Claims_4wkMA):

1. ARIMA(p,d,q) auto-selection:
   - AIC grid search: p ∈ [0,3], d ∈ [0,2], q ∈ [0,3]
   - Max 36 combinazioni (bounded search)
   - Se convergenza fallisce → fallback Ridge

2. Ridge Regression con lag features:
   - Features: [t-1, t-2, t-3, t-6, t-12] per ogni variabile
   - Normalizzazione: StandardScaler (evita leakage)
   - Alpha ottimale: cross-validation 5-fold su finestra rolling

3. Ensemble (peso ARIMA: 0.6, Ridge: 0.4):
   - Usato quando entrambi i modelli disponibili
   - Walk-forward validation su ultimi 24M per calcolo RMSE

Output per ogni orizzonte (1M, 3M, 6M):
   predicted_value, ci_lower_90, ci_upper_90, model_used, rmse_oos
```

### 1.3 — Scheduler Jobs Labour Market

```yaml
# config/labour_market.yaml
fetcher:
  jolts:
    fred_series: [JTSJOL, JTSQUL, JTSHIL, JTSLAL, JTSQUR, JTSJOR, JTSHIR, JTSLDR]
    schedule_cron: "0 17 8-12 * 3"  # Terzo mercoledì mese, ore 17:00 EST (release BLS)
    lookback_years: 20
    rate_budget_source: "fred"
  
  claims:
    fred_series: [ICSA, CCSA, IURSA]
    schedule_cron: "30 8 * * 4"    # Ogni giovedì, ore 8:30 EST (release settimanale)
    lookback_years: 20
    rate_budget_source: "fred"
  
  payrolls:
    fred_series: [PAYEMS, MANEMP, USCONS, USMINE, USTPU, USINFO, USFIRE, USPBS, USEHS, USLAH, USGOVT]
    schedule_cron: "30 8 1-7 * 5"  # Primo venerdì mese, ore 8:30 EST (NFP day)
    lookback_years: 20
    rate_budget_source: "fred"

analyzer:
  regime_update_cron: "0 18 * * 5"   # Venerdì sera dopo NFP
  forecast_update_cron: "0 10 * * 1" # Lunedì mattina (weekly update)
  
quality:
  min_quality_score: 0.6  # Threshold accettazione dati
  warn_if_gap_days: 10    # Alert se gap > 10gg nelle serie settimanali
```

### Definition of Done — Blocco 1

```
□ Migration 008 applicata: 5 tabelle create senza errori
□ JOLTSFetcher: 20 anni di dati in DuckDB (da 2004)
□ ClaimsFetcher: 20 anni di dati settimanali in DuckDB (da 2004)
□ PayrollFetcher: 20 anni NFP + 11 settori in DuckDB (da 2004)
□ DataQualityReport allegato a ogni serie: quality_score ≥ 0.7
□ JOLTSAnalyzer: Beveridge gap calcolato + regime classificato per ogni data
□ ClaimsCycleDetector: regime 4-stati assegnato + signal_strength [-1,1]
□ PayrollDecomposer: cyclical/defensive split + revisions calcolate
□ LabourRegimeClassifier: regime composito con recession_prob_6m per ogni settimana
□ LabourForecastEngine: RMSE UNRATE 3M < 0.30% su walk-forward 2020-2024
□ LabourForecastEngine: MAE NFP 1M < 80K posti su walk-forward 2022-2024
□ Scheduler: jobs JOLTS, Claims, Payroll girati senza errori in staging 48h
□ SanityChecker: claims_4wk_ma < 0 → CRITICAL | NFP < -2000K → CRITICAL
```

---

## BLOCCO 2 — Signal Quality Engine + Composite Signal v2
**Settimane 4-5 | Dipende da: Blocco 1 per segnale labour**

### 2.1 — Economic Surprise Engine

#### `engine/analytics/surprise_engine/consensus_loader.py`

**Strategia acquisizione consensus (in ordine di priorità):**

```
FONTE 1: YAML manuale (sempre disponibile, fallback garantito)
  File: config/surprise_engine.yaml
  Struttura:
    releases:
      - code: "NFP"
        name: "Non-Farm Payrolls"
        sector: "labour"
        next_release: "2026-06-06"
        consensus: 180.0    # Migliaia
        prior: 177.0
        unit: "K"
  
FONTE 2: Investing.com scraping (libero, robusto)
  URL: https://www.investing.com/economic-calendar/
  Parser: BeautifulSoup4 → estrai event_name, actual, forecast, previous
  Gestione anti-block: headers realistici + retry con backoff
  Rate limit: max 10 richieste/ora (conservative per rispettare i server)
  
FONTE 3: FRED per indicatori disponibili (GDP, CPI, UNRATE, INDPRO)
  Nessun consensus su FRED, ma "prior" sempre disponibile
  Surprise = actual - prior (proxy se consensus non disponibile)

Scelta implementativa finale:
  Il ConsensusLoader prova FONTE 2 → se fallisce usa FONTE 1
  MAI interrompere il programma per mancanza di consensus (graceful degradation)
  Alert se YAML non aggiornato da > 14 giorni
```

#### `engine/analytics/surprise_engine/surprise_calculator.py`

**Formula sorpresa standardizzata (Bloomberg Economic Surprise Index standard):**

```
z_score = (actual - consensus) / σ_storica

dove:
  σ_storica = rolling std delle sorprese (actual - consensus) degli ultimi 36 mesi
  min_periods = 6 (almeno 6 osservazioni per calcolare σ stabile)
  
  Se σ_storica < σ_min (soglia YAML): usa σ_globale serie storica
  Se |z_score| > 10: flagga come outlier (possibile errore consensus)

Copertura target minima: 20 indicatori
  Labour (6): NFP, JOLTS, Claims, Quits Rate, JOLTS Openings, Payroll Revisions
  Growth (5): GDP, ISM Manufacturing, ISM Services, Retail Sales, Industrial Production
  Inflation (5): CPI YoY, Core CPI, PCE, PPI, Import Prices
  Housing (4): Housing Starts, Building Permits, Existing Home Sales, Case-Shiller
```

#### `engine/analytics/surprise_engine/sector_surprise_aggregator.py`

**Aggregazione settoriale con EMA e momentum:**

```python
class SectorSurpriseAggregator:
    """Aggrega z-score per settore con decadimento esponenziale.
    
    Formula:
      score_t = α * z_score_t + (1-α) * score_{t-1}
      dove α = 1 - exp(-1/halflife_weeks)
      halflife_weeks = 8 (default, configurabile in YAML)
    
    Momentum:
      momentum_t = score_t - score_{t-4weeks}  (variazione mensile)
      direction = 'improving' se momentum > +0.15
                = 'deteriorating' se momentum < -0.15
                = 'stable' altrimenti
    
    Pesi settori (configurabili in YAML):
      labour:    0.30
      growth:    0.30
      inflation: 0.25
      housing:   0.15
    """
```

### 2.2 — Composite Signal v2

**Architettura a 7 componenti (investment bank standard):**

```
┌────────────────────────────────────────────────────────────────────┐
│              COMPOSITE SIGNAL v2 — 7 COMPONENTI                    │
│                                                                     │
│  1. Technical Signal       peso 0.15   (RSI, MACD, Volume, MA)     │
│  2. Macro Conviction       peso 0.20   (15 serie FRED: ciclo econ)  │
│  3. Labour Market          peso 0.15   ★ NUOVO (regime + forecast)  │
│  4. Sentiment              peso 0.10   (8 fonti: CNN, AAII, ecc.)   │
│  5. Valuation              peso 0.15   ★ NUOVO (PE, CAPE, ERP)     │
│  6. Economic Surprise      peso 0.10   ★ NUOVO (ESI composite)     │
│  7. Volatility Regime      peso 0.15   (VIX term structure + GARCH) │
│                                                                     │
│  OUTPUT: signal ∈ [-1, +1]                                         │
│    +1 = FORTE RIALZISTA    -1 = FORTE RIBASSISTA                   │
│    Breakdown per componente sempre esposto (Rule: RiskScore)       │
└────────────────────────────────────────────────────────────────────┘
```

**Regole di ponderazione dinamica (regime-adaptive):**

```python
# I pesi cambiano in base al regime di mercato corrente
# In regime STRESS: peso volatility aumenta, peso technical diminuisce
# In regime BULL: peso technical aumenta, peso valuation aumenta
# In regime BEAR: peso macro conviction aumenta, peso sentiment invertito

class CompositeSignalAggregator:
    """Aggregatore segnale composito v2 con pesi regime-adattivi."""
    
    BASE_WEIGHTS: dict[str, np.float64] = {
        "technical":    np.float64(0.15),
        "macro":        np.float64(0.20),
        "labour":       np.float64(0.15),
        "sentiment":    np.float64(0.10),
        "valuation":    np.float64(0.15),
        "surprise":     np.float64(0.10),
        "volatility":   np.float64(0.15),
    }
    
    # Invariante: sum(weights) == 1.0 (verificato in __post_init__)
    # Invariante: ogni segnale componente ∈ [-1, +1]
    # Anti-look-ahead: tutti i segnali componente usano dati di chiusura t-1
```

### Definition of Done — Blocco 2

```
□ Migration 009 applicata: 3 tabelle create senza errori
□ ConsensusLoader: YAML fallback funzionante (garantito offline)
□ ConsensusLoader: scraping Investing.com per ≥ 15 indicatori
□ SurpriseCalculator: z-score == 0 quando actual == consensus (test deterministico)
□ SurpriseCalculator: 20 indicatori con z-score in DuckDB
□ SectorSurpriseAggregator: EMA aggiornata settimanalmente per 4 settori
□ EconomicSurpriseIndex: segnale [-1,1] disponibile per Composite v2
□ VolumeAnalyzer.compute() vettorizzato: < 50ms su 5 anni
□ CompositeSignalAggregator v2: tutti e 7 i segnali integrati
□ Pesi v2 sommano a 1.0 (test di sanità in test_composite_signal_v2.py)
□ Correlazione Signal v2 vs v1 su dati storici 2020-2024: > 0.85
□ Backtest Signal v2: Sharpe ratio calcolato su benchmark SPY 2020-2024
```

---

## BLOCCO 3 — Valuation Engine: P/E Ratio Multi-Indicatore
**Settimane 6-7 | Dipende da: baseline v7.2.0 (SEC EDGAR, yfinance già presenti)**

### 3.1 — Earnings Fetcher

#### `engine/analytics/valuation/earnings_fetcher.py`

**Fonti dati per EPS (multiple, con fallback):**

```
FONTE A: SEC EDGAR XBRL (già presente nel progetto — SECEdgarFetcher)
  Metriche: us-gaap/EarningsPerShareDiluted, us-gaap/Revenues
  Ticker mapping: necessario CIK → ticker (EDGAR company.json)
  Frequenza: quarterly (4Q rolling per trailing EPS)
  Disponibile per: S&P500 companies individualmente
  Per indice (SPY/^GSPC): aggregazione ponderata su top 50 per market cap
  
FONTE B: Alpha Vantage EARNINGS API (gratuito 25 req/day)
  Endpoint: /query?function=EARNINGS&symbol=SPY
  Dati: EPS annuale + trimestrale storico
  Fallback se SEC EDGAR fallisce
  
FONTE C: yfinance (già integrato)
  yf.Ticker("SPY").financials → income_statement
  EPS: net_income / shares_outstanding (approssimazione)
  Usato per validazione incrociata
  
FONTE D: FRED per indici aggregati
  FRED SP500EPS: EPS aggregato S&P 500 (aggiornamento trimestrale)
  Più robusto di EDGAR per indici, meno preciso per singoli titoli
  
Raccomandazione implementativa:
  Per ^GSPC / SPY:  FRED SP500EPS (primario) + yfinance (validazione)
  Per singoli titoli: Alpha Vantage (primario) + SEC EDGAR (secondario)
```

#### `engine/analytics/valuation/forward_estimates_fetcher.py`

**Forward EPS (12 mesi forward consensus):**

```
SFIDA: dati forward gratuiti sono rari e poco affidabili

Soluzione a 3 livelli:
  
LIVELLO 1: FRED series SPASTT01USM657N (SP500 P/E ratio implicito)
  → Da cui: Forward EPS = Price / Forward PE
  Disponibile con ritardo 1-2 settimane
  
LIVELLO 2: Alpha Vantage EARNINGS_CALENDAR
  → Stima EPS forward dei prossimi 3M
  Qualità media, ma gratuita e automatizzata
  
LIVELLO 3: YAML manuale consenso
  File: config/valuation.yaml → forward_eps_manual
  Aggiornato trimestralmente con stime Wall Street (da barclays/GS research pubblici)
  Fallback garantito quando API non disponibili

Nota: forward EPS ha incertezza elevata. Il sistema lo usa sempre con
  un flag is_estimated=True e il PE forward viene mostrato con una banda
  di confidenza esplicita in UI.
```

#### `engine/analytics/valuation/shiller_cape_fetcher.py`

**Shiller CAPE (dati 1881-oggi):**

```python
# Dataset pubblico di Robert Shiller (Yale University)
# URL: http://www.econ.yale.edu/~shiller/data/ie_data.xls
# Formato: Excel con fogli "Data", "CAPE", "Real Data"
# Aggiornamento: mensile

class ShillerCAPEFetcher:
    """Fetch CAPE da dataset pubblico Shiller (Yale).
    
    Pipeline:
      1. Download XLS da URL pubblico (aiohttp)
      2. Parse foglio "Data" con pandas (skiprows necessario)
      3. Calcola CPI-adjusted EPS su rolling 10 anni
      4. Calcola CAPE = Price / mean(real_EPS_10y)
      5. Calcola ERP implicito = 1/CAPE - Bond_Yield_10y
      6. Persist in DuckDB: shiller_cape_historical (serie dal 1881)
    
    Fallback: FRED series MULTPL/SHILLER_PE_RATIO_MONTH
    (disponibile tramite Quandl/Nasdaq Data Link con chiave gratuita)
    
    Rate limit: 1 richiesta/giorno (dataset aggiornamento mensile)
    """
```

### 3.2 — P/E Calculator + Context Builder

#### `engine/analytics/valuation/pe_calculator.py`

**Le tre metriche P/E e il loro significato:**

```
TRAILING P/E:
  Formula: Price / (Sum of last 4 quarters EPS diluted)
  Pro: basato su dati reali, non su stime
  Contro: guarda indietro; distorto in recessioni (EPS crolla)
  Soglie indicative S&P500 (media storica ~16-18x):
    < 15x:  storicament economico
    15-20x: fair value range
    20-25x: premium ma giustificato in bassa inflazione
    > 25x:  stretched, richiede crescita EPS eccezionale
    > 30x:  storicament associato a correzioni significative

FORWARD P/E:
  Formula: Price / (Consensus analyst EPS next 12M)
  Pro: forward-looking, incorpora aspettative
  Contro: stime analisti sistematicamente ottimistiche (+5-10% bias)
  Normalizzazione: applicare correction factor -5% alle stime raw
  Soglie (mean ~15x, più basso del trailing per aspettativa crescita):
    < 14x:  cheap, mercato sconta deterioramento utili
    14-18x: range normale
    18-22x: premium
    > 22x:  stretched o crescita EPS eccezionale prezzata

SHILLER CAPE:
  Formula: Price / Mean(CPI-adjusted EPS, 10 years)
  Pro: elimina volatilità ciclica EPS; molto predittivo a 10 anni
  Contro: non utile per timing preciso (può restare alto 5-10 anni)
  Media storica 1881-2025: ~16.8x
  Soglie CAPE:
    < 15x:  deep value storico
    15-22x: fair value range
    22-28x: premium
    > 28x:  stretched (CAPE 2000: 44x; 2021: 38x; 2009: 13x)
    
EQUITY RISK PREMIUM (ERP):
  Formula: ERP = Earnings Yield - Risk-Free Rate
    Earnings Yield = 1 / Forward PE
    Risk-Free Rate = US 10Y Treasury (DGS10, da FRED)
  Interpretazione:
    ERP > 3%:  azioni attraenti vs bond
    ERP 1-3%:  fair value
    ERP < 1%:  azioni costose relativamente ai bond
    ERP < 0%:  azioni storicamente molto costose (2021: -0.5%)
  Questo è il segnale più importante per asset allocation relativa
```

#### `engine/analytics/valuation/pe_context_builder.py`

**Contestualizzazione storica (standard investment bank):**

```python
class PEContextBuilder:
    """Calcola z-score e percentile storico di ogni metrica P/E.
    
    Per ogni metrica M (trailing_pe, forward_pe, cape, erp):
      z_score_M = (M_today - mean(M, 20y)) / std(M, 20y)
      percentile_M = percentileofscore(history_20y, M_today)
    
    Interpretazione z-score:
      z > +2.0: metrica estremamente alta (top 97.7%)
      z +1 to +2: alta (top 84-97%)
      z -1 to +1: range normale
      z < -2.0: estremamente bassa (bottom 2.3%)
    
    Composite valuation score (per Composite Signal v2):
      v_score = -1 * (
          0.30 * normalize(trailing_pe_zscore) +
          0.35 * normalize(forward_pe_zscore) +
          0.20 * normalize(cape_zscore) +
          0.15 * normalize(-erp)  # ERP alto = azioni attraenti (segno invertito)
      )
      # v_score ∈ [-1,+1]: +1=deep value, -1=bubble
    
    Label qualitativo:
      v_score > +0.5:  'deep_value'
      v_score +0.1 to +0.5: 'cheap'
      v_score -0.1 to +0.1: 'fair_value'
      v_score -0.1 to -0.4: 'stretched'
      v_score < -0.4: 'bubble_warning'
    """
```

### 3.3 — Dashboard Valuation (M6)

**Specifiche UI `M6_Valuation_PE.py`:**

```
LAYOUT: 3 sezioni principali

SEZIONE A — KPI Attuali (4 metriche + semaforo)
  ┌─────────────┬─────────────┬─────────────┬─────────────┐
  │ Trailing PE │  Forward PE │ Shiller CAPE│     ERP     │
  │   22.5x     │   20.1x     │   31.2x     │  +1.8%     │
  │  🟡 alto    │  🟡 alto    │  🔴 molto alto│  🟢 ok     │
  │  %tile: 78  │  %tile: 72  │  %tile: 88  │  %tile: 55 │
  └─────────────┴─────────────┴─────────────┴─────────────┘

SEZIONE B — Contesto Storico (chart interattivo)
  Tab 1: "Trailing PE" — Serie storica 20 anni con bande ±1σ, ±2σ
  Tab 2: "Forward PE" — Idem con stima consensus
  Tab 3: "CAPE Shiller" — Serie dal 1881 (selezione zoom)
  Tab 4: "ERP" — ERP vs 10Y yield (scatter + timeline)
  
  Ogni chart: linea verticale "oggi", shading recessioni NBER

SEZIONE C — Valuation Dashboard Multi-Indicatore
  Matrice 2x2 (CAPE vs ERP, Trailing vs Forward) con:
  - Quadranti: cheap-cheap / cheap-expensive / ecc.
  - Punto "oggi" + trailing 5 anni
  - Annotazioni eventi storici (2000, 2009, 2020, ecc.)
  
  Sub-sezione: "Cosa implica il CAPE attuale per i prossimi 10 anni"
  → formula Shiller: expected_10y_return = 1/CAPE - expected_inflation + growth
  → 3 scenari: pessimistico/base/ottimistico (con sensitivity table)

SEZIONE D — Sector-Level P/E (se dati disponibili)
  Heatmap settoriale: Technology, Healthcare, Financials, Energy, ecc.
  Colore = forward PE percentile storico

Metriche tecniche:
  Cache TTL: 3600s (dati aggiornamento giornaliero)
  Caricamento: < 2s (query DuckDB pre-computata)
  Stato vuoto: messaggio educativo + istruzioni configurazione FRED key
```

### Definition of Done — Blocco 3

```
□ Migration 010 applicata: 4 tabelle create senza errori
□ ShillerCAPEFetcher: serie dal 1881 in DuckDB (>= 1700 record mensili)
□ EarningsFetcher: trailing EPS S&P500 disponibile (ultimi 5 anni)
□ ForwardEstimatesFetcher: forward EPS disponibile con is_estimated flag
□ PECalculator: trailing PE, forward PE, CAPE, ERP calcolati per ogni data
□ PEContextBuilder: z-score e percentile calcolati su finestra 20 anni
□ ValuationSignalGenerator: v_score ∈ [-1,+1] (test deterministico)
□ Label 'fair_value' quando tutti gli indicatori nella media (test)
□ Dashboard M6: 4 tab caricano senza eccezioni
□ Dashboard M6: CAPE chart dal 1881 renderizzato < 2s
□ Dashboard M6: Matrice 2x2 ERP vs CAPE con punto "oggi" visibile
□ Integrazione Composite v2: valuation_signal contribuisce al composite
□ ERP > 3% → label 'attractive' (test deterministico)
□ ERP < 0% → label 'extreme' (test deterministico)
```

---

## BLOCCO 4 — Correlation Engine v2
**Settimane 8-9 | Dipende da: baseline v7.2.0 (CorrelationAnalyzer esistente)**

### 4.1 — Filosofia di Design (Investment Bank Standard)

**Problema con la correlazione statica (e con il DCC-GARCH-lite attuale):**

```
❌ Correlazione Pearson 252gg: stabile ma cieca ai regime change
❌ EWMA con λ fisso: non ottimale per tutti gli asset
❌ HMM-lite K-means: non usa direttamente la volatilità condizionale
❌ Lead-lag: cross-correlazione raw senza Granger causality

✅ Standard investment bank:
  1. DCC-GARCH(1,1): correlazioni dinamiche con vol condizionale esplicita
  2. Decay EWMA ottimale: λ stimato via MLE su asset specifico
  3. Regime-conditioned: correlazioni separate per bull/bear/stress/transition
  4. Granger causality: test formale di lead-lag (non solo cross-corr)
  5. Cross-asset matrix: equity/bond/credit/FX/commodity nella stessa view
```

### 4.2 — DCC-GARCH via `arch` library (feature-flagged)

#### `engine/analytics/correlation/dcc_garch.py`

```python
# FEATURE FLAG: dcc_garch_full (default: False — computazionalmente costoso)
# Quando disabled → fallback automatico su dcc_ewma_enhanced.py

class DCCGARCHAnalyzer:
    """DCC-GARCH(1,1) tramite libreria arch.
    
    Implementazione:
      1. Per ogni asset i: fit GARCH(1,1) → σ_it (volatilità condizionale)
      2. Standardizza residui: z_it = r_it / σ_it
      3. Stima DCC: Q_t = (1-α-β)*Q_bar + α*(z_t-1 z_t-1') + β*Q_t-1
         dove α+β < 1 (stazionarietà), α,β > 0
      4. R_t = diag(Q_t)^{-1/2} * Q_t * diag(Q_t)^{-1/2} (correlazioni)
    
    Limitazioni note:
      - Lento per N>30 asset (O(N^2) per ogni timestamp)
      - Richiede ~252gg di dati per fit stabile
      - Non adatto a intraday (calibrato su daily)
    
    Feature flag: 'dcc_garch_full' in config/feature_flags.yaml
    Fallback: DCCEWMAEnhanced (sempre disponibile, < 100ms)
    
    from arch import arch_model  # arch library: pip install arch
    """
```

#### `engine/analytics/correlation/dcc_ewma_enhanced.py`

**EWMA Enhanced (fallback computazionalmente efficiente):**

```python
class DCCEWMAEnhanced:
    """EWMA con decay ottimale stimato via MLE — sempre disponibile.
    
    Miglioramenti rispetto all'EWMA attuale (dcc_ewma_enhanced vs analyzer.py):
    
    1. Decay ottimale per coppia:
       λ_optimal = argmax_λ [ Σ_t log P(r_t | Q_t(λ)) ]
       dove P è likelihood normal multivariata
       Ricerca: grid search λ ∈ [0.90, 0.99] con passo 0.01
       Cache: λ_optimal per coppia persistito in config/correlation_lambdas.json
    
    2. Regime-conditioning:
       Calcola EWMA separatamente per ogni regime (bull/bear/stress/transition)
       Output: dict[regime → correlation_matrix]
       Permette di confrontare: "correlazione in crisi vs in bull"
    
    3. Shrinkage regolarizzazione (Ledoit-Wolf):
       Se matrice EWMA non semi-definita positiva (numericamente):
       → Ledoit-Wolf shrinkage per garantire PSD
       → scipy.linalg.solve per inversione stabile
    
    Performance target: < 200ms per 20 asset su 5 anni giornalieri
    """
```

### 4.3 — Lead-Lag Analysis (Granger Causality)

#### `engine/analytics/correlation/lead_lag_analyzer.py`

**Standard professionale per lead-lag:**

```python
class LeadLagAnalyzer:
    """Analisi lead-lag via Granger causality test.
    
    Algoritmo:
    
    1. Pre-processing:
       - Rendimenti log: r_t = log(P_t / P_{t-1})
       - ADF test per stazionarietà (differenziare se necessario)
       - Winsorize outlier a ±5σ (outlier non devono falsare il test)
    
    2. Granger Causality Test (statsmodels.tsa.stattools.grangercausalitytests):
       Per ogni coppia (A, B) e ogni lag k ∈ [1, 2, 5, 10, 21]:
         H0: A non causa B a lag k
         Test: F-test sul modello VAR(k)
         Significativo se: p-value < 0.05 AND F-stat > soglia YAML
    
    3. Selezione lag ottimale:
       optimal_lag = lag con p-value minimo E massima cross-corr
       Cross-corr al lag ottimale deve essere |corr| > 0.3 (filtro noise)
    
    4. Lead signal:
       Se A causa B con lag ottimale k:
         lead_signal = 'bullish_lead' se corr_at_lag > 0
         lead_signal = 'bearish_lead' se corr_at_lag < 0
       
    5. Esempi di lead-lag storicamente robusti (da usare come test):
       - Credit spreads (HYG) → Equity (SPY): lead ~5-10gg in crisi
       - VIX → Equity: contemporaneous o lead 1-2gg
       - Copper (COPX) → Global growth proxies: lead ~10-15gg
       - Small cap (IWM) → Large cap (SPY): lead ~3-5gg ciclo
       - Bond (TLT) → Equity (growth regime): lead variabile
    
    Output per coppia:
      LeadLagResult(leader, follower, lag_days, f_stat, p_value,
                    cross_corr_peak, is_significant, lead_signal)
    
    Performance: < 500ms per 10 coppie su 3 anni giornalieri
    """
```

### 4.4 — Cross-Asset Correlation Matrix

#### `engine/analytics/correlation/cross_asset_matrix.py`

**Vista cross-asset (standard Bloomberg CORR dashboard):**

```python
class CrossAssetMatrix:
    """Matrice correlazioni cross-asset regime-conditioned.
    
    Asset universe (configurabile in config/correlation_v2.yaml):
      US Equity:    SPY (large cap), IWM (small cap), QQQ (tech)
      Bonds:        TLT (long-term), IEF (7-10Y), SHY (short)
      Credit:       HYG (high yield), LQD (investment grade)
      Commodities:  GLD (gold), USO (crude), COPX (copper)
      FX:           UUP (dollar index), FXE (euro)
      Volatility:   ^VIX
    
    Calcoli:
      1. Correlazione DCC o EWMA per ogni coppia (N=13 → 78 coppie)
      2. Separazione per regime: 4 regimi × 78 coppie = 312 correlazioni
      3. Aggregati chiave:
         - equity_bond_corr: media SPY/IWM vs TLT/IEF (chiave risk parity)
         - equity_gold_corr: flyweight vs safe haven
         - credit_equity_corr: risk appetite indicator
      4. Diversification score:
         D = 1 - mean(|off_diagonal correlations|)
         D = 1: portfolio non correlato (massima diversificazione)
         D = 0: tutti gli asset si muovono insieme (crisi)
      5. correlation_signal per Composite v2:
         signal = D - D_historical_mean_regime  (normalizzato)
    
    Update frequency:
      Weekly snapshot (venerdì sera)
      Intraday non necessario (correlazioni giornaliere sufficienti)
    
    Performance: < 500ms per universo 13 asset su 5 anni
    """
```

### 4.5 — Upgrade E8 Correlations Dashboard

**Nuove sezioni in `E8_Correlations.py`:**

```
Tab 1: "Matrice Corrente" (esistente, aggiornata con DCC)
  → Heatmap 13x13 DCC correlations (regime attuale)
  → Toggle: DCC vs EWMA vs Static (confronto 3 metodi)
  → Regime label visibile + data ultimo update

Tab 2: "Evoluzione nel Tempo" (upgrade da statico a dinamico)
  → Rolling correlation selezionabile: 1M / 3M / 6M
  → Coppia selezionabile (dropdown)
  → Overlay regime HMM (shading colore per regime)
  → Annotazione eventi (COVID, 2022 rate hike, ecc.)

Tab 3: "Lead-Lag Matrix" ★ NUOVO
  → Heatmap N×N: leader (colonne) vs follower (righe)
  → Colore: verde = Granger significativo (p<0.05), grigio = ns
  → Intensità: cross-corr al lag ottimale
  → Click su cella → dettaglio (lag_days, F-stat, p-value, segnale)
  → Tabella top-5 relazioni significative (ordinata per p-value)

Tab 4: "Regime Cross-Asset" ★ NUOVO
  → 4 mini-heatmap: bull / bear / stress / transition
  → Scatter: equity_bond_corr vs regime_score (storico)
  → Diversification score timeline
  → Alert se D < D_stress_threshold (regime crisi correlazioni)

Tab 5: "Correlation Signal" ★ NUOVO
  → Grafico correlation_signal vs Composite Signal v2
  → Contributo correlazioni al segnale composito
  → Statistiche periodo corrente vs media storica
```

### Definition of Done — Blocco 4

```
□ Migration 011 applicata: 3 tabelle create senza errori
□ DCCEWMAEnhanced: decay λ ottimale stimato per almeno 10 coppie chiave
□ DCCEWMAEnhanced: matrice PSD garantita (Ledoit-Wolf se necessario)
□ DCCEWMAEnhanced: < 200ms per 20 asset su 5 anni (benchmark)
□ DCCGARCHAnalyzer: feature-flagged, non attivo di default
□ LeadLagAnalyzer: Granger test su 10 coppie chiave in < 500ms
□ LeadLagAnalyzer: SPY-HYG lead 5-10gg Granger significativo su 2020-2021 (smoke test)
□ CrossAssetMatrix: 13 asset × 4 regimi calcolati
□ DiversificationScore: D = 1.0 se tutti gli asset decorrelati (test deterministico)
□ E8_Correlations: Tab Lead-Lag caricato senza eccezioni
□ E8_Correlations: Tab Regime Cross-Asset con 4 mini-heatmap
□ correlation_signal integrato nel Composite v2
□ Test: correlazione regime-stress > correlazione regime-bull (empiricamente verificato)
```

---

## BLOCCO 5 — UI Integration + Dashboard Upgrade
**Settimane 10-11 | Dipende da: Blocchi 1-4 al 90%**

### Nuove pagine da creare/completare:

| Pagina | Status | Dipende da |
|--------|--------|------------|
| `M3_Labour_Market.py` | Completamento (era placeholder) | Blocco 1 |
| `M5_Economic_Surprise.py` | Nuova | Blocco 2 |
| `M6_Valuation_PE.py` | Nuova | Blocco 3 |
| `Q9_Labour_Forecasting.py` | Nuova | Blocco 1 |
| `Q10_Surprise_Heatmap.py` | Nuova | Blocco 2 |
| `E8_Correlations.py` | Upgrade (5 tab) | Blocco 4 |
| `K1_Market_Overview.py` | Upgrade con Composite v2 breakdown | Blocco 2 |

### Upgrade `K1_Market_Overview.py` — Composite v2 Breakdown:

```
SEZIONE COMPOSITE SIGNAL v2:
  Score globale: [-1, +1] con gauge visuale
  
  Breakdown 7 componenti (barra orizzontale per ognuno):
  ┌─────────────────────────────────────────────────────┐
  │ Technical Signal     ████████░░░░  +0.42 (peso 15%) │
  │ Macro Conviction     ██████░░░░░░  +0.28 (peso 20%) │
  │ Labour Market        ████░░░░░░░░  +0.15 (peso 15%) │
  │ Sentiment            ██████████░░  +0.55 (peso 10%) │
  │ Valuation            ░░░░██░░░░░░  -0.20 (peso 15%) │
  │ Economic Surprise    ████████░░░░  +0.35 (peso 10%) │
  │ Volatility Regime    ████████████  +0.60 (peso 15%) │
  │ ─────────────────────────────────────────────────── │
  │ COMPOSITE v2:        ██████████░░  +0.34 MODERATO ▲ │
  └─────────────────────────────────────────────────────┘
  
  Trend 30 giorni del composite (spark line)
  Alert se composite cambia segno (da bullish a bearish o viceversa)
```

### Definition of Done — Blocco 5

```
□ M3 Labour Market: 4 tab (JOLTS / Claims / Payroll / Regime) caricano senza eccezioni
□ M3: forecast 3 orizzonti visibile in Q9
□ M5 Economic Surprise: heatmap 20 indicatori × 12 mesi renderizzata < 2s
□ M6 Valuation PE: 4 sezioni (KPI + chart storico + matrice + implicazioni)
□ M6: CAPE chart dal 1881 renderizzato < 3s
□ Q10 Surprise Heatmap: popup dettaglio su click cella funzionante
□ E8 Correlations: tutti e 5 i tab operativi
□ K1 Market Overview: composite v2 breakdown con 7 barre visibili
□ Navigazione aggiornata: M3, M5, M6, Q9, Q10 accessibili senza 404
□ Ogni nuova pagina: @st.cache_data con TTL appropriato (definito in YAML)
□ Ogni nuova pagina: graceful degradation con DB vuoto (warning visibile, no crash)
□ DESIGN_TOKENS: zero colori hardcoded in tutte le nuove pagine
```

---

## BLOCCO 6 — Test · Hardening · Benchmark · CI
**Settimana 12 | Dipende da: tutti i blocchi precedenti**

### Test Suite Completa

```
tests/engine/test_labour_market/ (≥ 5 file):
  □ test_jolts_fetcher.py:           mock FRED + 4 path, DataQualityReport allegato
  □ test_jolts_analyzer.py:          4 regimi + Beveridge gap sign test
  □ test_claims_cycle_detector.py:   ciclo expansion→contraction su fixture 2020
  □ test_payroll_decomposer.py:      cyclical/defensive split + revisions
  □ test_labour_regime_classifier.py: classificazione deterministica
  □ test_labour_forecast_engine.py:  fit + forecast su 10 anni FRED, RMSE check

tests/engine/test_valuation/ (≥ 5 file):
  □ test_shiller_cape_fetcher.py:    mock URL + parsing XLS, serie dal 1881
  □ test_earnings_fetcher.py:        mock FRED + SEC EDGAR, trailing EPS
  □ test_pe_calculator.py:           trailing/forward/CAPE deterministici
  □ test_pe_context_builder.py:      z-score, percentile, label
  □ test_valuation_signal_generator.py: segnale ∈ [-1,+1], label boundaries

tests/engine/test_surprise_engine/ (≥ 4 file):
  □ test_consensus_loader.py:        YAML fallback, mock scraping
  □ test_surprise_calculator.py:     z-score == 0 se actual == consensus
  □ test_sector_surprise_aggregator.py: EMA decadimento esponenziale verificato
  □ test_surprise_signal_generator.py:  segnale ∈ [-1,1] per tutti i casi edge

tests/engine/test_correlation_v2/ (≥ 4 file):
  □ test_dcc_ewma_enhanced.py:       decay ottimale MLE, PSD guarantee
  □ test_lead_lag_analyzer.py:       Granger deterministico su fixture, p-value
  □ test_cross_asset_matrix.py:      D=1 se decorrelati, 4 regimi calcolati
  □ test_correlation_signal_generator.py: segnale ∈ [-1,1]

tests/integration/ (≥ 3 file):
  □ test_composite_signal_v2.py:     pipeline completa 7 componenti su fixture DuckDB
  □ test_valuation_pipeline.py:      end-to-end: earnings → PE → signal → DuckDB
  □ test_labour_surprise_pipeline.py: labour → surprise → composite
```

### Performance Benchmarks

| Modulo | Target | Strumento |
|--------|--------|-----------|
| JOLTSFetcher (mock, 20 anni) | < 500ms | pytest-benchmark |
| ClaimsCycleDetector.compute() | < 100ms | pytest-benchmark |
| LabourForecastEngine.forecast() 3 orizzonti | < 5s | pytest-benchmark |
| PECalculator.compute() 20 anni | < 200ms | pytest-benchmark |
| PEContextBuilder.build() 20 anni | < 100ms | pytest-benchmark |
| SectorSurpriseAggregator.aggregate() 5 settori | < 500ms | pytest-benchmark |
| CompositeSignalAggregator v2.compute() | < 300ms | pytest-benchmark |
| DCCEWMAEnhanced 20 asset, 5 anni | < 200ms | pytest-benchmark |
| LeadLagAnalyzer 10 coppie, 3 anni | < 500ms | pytest-benchmark |
| CrossAssetMatrix 13 asset, 4 regimi | < 500ms | pytest-benchmark |
| M3 Labour Market caricamento | < 2.5s | Browser timing |
| M5 Surprise heatmap rendering | < 2s | Browser timing |
| M6 Valuation PE caricamento | < 2s | Browser timing |
| E8 Correlations Tab Lead-Lag | < 3s | Browser timing |

### Hardening + Sicurezza

```
□ SanityChecker esteso:
  - claims_4wk_ma < 0 o > 2.000.000 → CRITICAL
  - NFP < -2.000K (fuori COVID) → CRITICAL
  - CAPE < 5 o > 60 → WARN (dato impossibile)
  - ERP > +15% o < -10% → WARN (possibile errore dati)
  - Forward EPS negativo non in recessione → WARN
  - z_score surprise > 10 → WARN (consensus probabilmente errato)

□ CrossSourceValidator esteso:
  - FRED PAYEMS vs sum settori → discrepanza > 5% → WARN
  - CAPE calcolato vs CAPE da dataset Shiller → discrepanza > 2% → WARN
  - Trailing PE da yfinance vs da EDGAR → discrepanza > 10% → WARN

□ feature_flags.yaml aggiornato:
  - labour_market_fetcher: true
  - labour_market_scheduler: true
  - labour_market_forecasting: true
  - economic_surprise_engine: true
  - valuation_pe_engine: true
  - dcc_garch_full: false        # default off (computazionalmente costoso)
  - lead_lag_granger: true
  - cross_asset_matrix: true
  - composite_signal_v2: true
```

### mypy + ruff

```
□ mypy --strict: 0 errors su tutti i nuovi moduli
□ ruff check .: 0 warnings su tutto il nuovo codice
□ Coverage globale: ≥ 80%
□ Coverage engine/analytics/: ≥ 85%
□ Coverage engine/analytics/valuation/: ≥ 85%
□ Coverage engine/analytics/labour_market/: ≥ 85%
```

### Definition of Done — Blocco 6 (= Definition of Done del Progetto v4)

```
□ Tutti i benchmark nei target
□ mypy --strict 0 errors su tutti i nuovi moduli
□ ruff 0 warnings
□ Coverage ≥ 80% globale, ≥ 85% su analytics/
□ Test integration end-to-end: pipeline labour + surprise + valuation → composite → DuckDB
□ Scheduler: tutti i job girano senza errori per 48h consecutive in staging
□ Backup testato con le 4 nuove tabelle (008, 009, 010, 011)
□ CHANGELOG aggiornato (v7.2.0 → v7.3.0 → v7.4.0)
□ config/feature_flags.yaml: tutti i nuovi flag documentati
□ Navigazione: M3, M5, M6, Q9, Q10 accessibili senza 404
□ Totale test: ≥ 200 (da 131 attuali)
```

---

## FEATURE FLAGS — AGGIORNAMENTI

```yaml
# config/feature_flags.yaml — aggiunte per ROADMAP v4

# ──── BLOCCO 1: Labour Market ────────────────────────────────────────
labour_market_fetcher:        true    # Fetch JOLTS/Claims/Payroll da FRED
labour_market_scheduler:      true    # Job scheduler JOLTS/Claims/Payroll
labour_market_forecasting:    true    # ARIMA+Ridge forecast 1M/3M/6M
labour_beveridge_analysis:    true    # Beveridge curve + gap calcolato

# ──── BLOCCO 2: Signal Quality ────────────────────────────────────────
economic_surprise_engine:     true    # SurpriseCalculator + Aggregator
surprise_consensus_scraping:  false   # Scraping Investing.com (default off)
surprise_consensus_yaml:      true    # YAML fallback consenso (sempre on)
surprise_scheduler:           true    # Job scheduler venerdì 18:00
composite_signal_v2:          true    # Composite a 7 componenti

# ──── BLOCCO 3: Valuation ─────────────────────────────────────────────
valuation_pe_engine:          true    # P/E Calculator + Context Builder
shiller_cape_fetcher:         true    # Download dati Shiller Yale
forward_pe_estimates:         true    # Forward EPS da Alpha Vantage/YAML
valuation_sector_pe:          false   # PE settoriale (richiede più dati)

# ──── BLOCCO 4: Correlations v2 ───────────────────────────────────────
dcc_ewma_enhanced:            true    # EWMA con decay ottimale (sempre on)
dcc_garch_full:               false   # DCC-GARCH via arch (default off!)
lead_lag_granger:             true    # Granger causality test
cross_asset_matrix:           true    # Matrice 13 asset × 4 regimi
correlation_signal_composite: true    # Segnale correlazioni → Composite v2
```

---

## RATE LIMITS — NUOVE SORGENTI

| Sorgente | Endpoint | Limite | Dichiarato in |
|----------|----------|--------|---------------|
| FRED API | `/fred/series/observations` | 120 req/min | `rate_limits.yaml` |
| BLS API | `/publicAPI/v2/timeseries/data` | 50 req/day | `rate_limits.yaml` |
| SEC EDGAR XBRL | `/api/xbrl/companyfacts` | 10 req/sec | già presente |
| Alpha Vantage | `/query?function=EARNINGS` | 25 req/day (free) | già presente |
| Shiller Yale | Excel URL | 1 req/day | `rate_limits.yaml` |
| Investing.com | Calendar scraping | 10 req/hour | `rate_limits.yaml` |

---

## TIMELINE RIEPILOGATIVA

```
Settimana  1  → Blocco 1: Migration 008 + JOLTSFetcher + ClaimsFetcher + PayrollFetcher
Settimana  2  → Blocco 1: JOLTSAnalyzer + ClaimsCycleDetector + PayrollDecomposer
Settimana  3  → Blocco 1: LabourRegimeClassifier + LabourForecastEngine + scheduler job
Settimana  4  → Blocco 2: Migration 009 + ConsensusLoader + SurpriseCalculator
Settimana  5  → Blocco 2: SectorSurpriseAggregator + CompositeSignalAggregator v2
Settimana  6  → Blocco 3: Migration 010 + ShillerCAPEFetcher + EarningsFetcher
Settimana  7  → Blocco 3: PECalculator + PEContextBuilder + ValuationSignalGenerator
Settimana  8  → Blocco 4: Migration 011 + DCCEWMAEnhanced + LeadLagAnalyzer
Settimana  9  → Blocco 4: CrossAssetMatrix + CorrelationSignalGenerator
Settimana 10  → Blocco 5: M3, M5, M6 dashboard + E8 upgrade
Settimana 11  → Blocco 5: Q9, Q10 + K1 upgrade + navigazione
Settimana 12  → Blocco 6: Test suite completa + benchmark + hardening + CHANGELOG
─────────────────────────────────────────────────────────────────────────────────
TOTALE: 12 settimane aggiuntive rispetto a baseline v7.2.0
TARGET FINALE: v7.4.0 (≥ 200 test, 4 nuove migrations, 7 nuove pagine)

PIETRE MILIARI (GO/NO-GO):
  Fine Blocco 1: dati labour 20 anni in DuckDB + RMSE target → GO Blocco 2
  Fine Blocco 2: 7-component composite signal + ESI operativo → GO Blocco 5 (UI)
  Fine Blocco 3: CAPE 1881-oggi + ERP calcolato → GO Blocco 5 (UI)
  Fine Blocco 4: DCC ottimizzato + Granger operativo → GO Blocco 5 (UI)
  Fine Blocco 5: tutte le pagine operative → GO Blocco 6
```

---

## METRICHE DI SUCCESSO

| Metrica | Target | Strumento |
|---------|--------|-----------|
| LabourForecastEngine RMSE UNRATE 3M | < 0.30% | Walk-forward 2020-2024 |
| LabourForecastEngine MAE NFP 1M | < 80K posti | Walk-forward 2022-2024 |
| CAPE storico disponibile | dal 1881 (>1700 record) | DuckDB count |
| ERP calcolato e aggiornato | giornaliero | DuckDB freshness |
| Lead-lag Granger: coppie testate | ≥ 10 | LeadLagAnalyzer |
| Correlazione in regime stress vs bull: differenza | significativa (>0.15) | test empirico |
| CompositeSignalAggregator v2 | < 300ms | pytest-benchmark |
| DCCEWMAEnhanced 20 asset | < 200ms | pytest-benchmark |
| M6 Valuation PE rendering | < 2s | Browser timing |
| Coverage engine/analytics/ | ≥ 85% | pytest --cov |
| Test totali | ≥ 200 | pytest |
| Indicatori surprise coperti | ≥ 20 | config audit |
| mypy --strict errors | 0 | mypy |

---

## RISCHI SPECIFICI DI QUESTA ROADMAP

| # | Rischio | Prob | Impatto | Mitigazione |
|---|---------|------|---------|-------------|
| R1 | Shiller Yale cambia URL o formato XLS | Media | Medio | Fallback su FRED MULTPL/SHILLER_PE; test di regressione URL |
| R2 | Alpha Vantage 25 req/day insufficiente per bulk | Alta | Basso | YAML manuale fallback; scheduling notturno fuori peak hours |
| R3 | Investing.com blocca scraping | Alta | Medio | YAML manual fallback sempre disponibile; Rotating headers |
| R4 | ARIMA non converge su alcune serie labour | Media | Basso | Fallback Ridge con warm message; default Ridge se AIC diverge |
| R5 | arch library incompatibile con Python/NumPy versione | Media | Basso | Feature flag dcc_garch_full=false; EWMA sempre disponibile |
| R6 | Granger causality instabile su serie corte | Media | Medio | min_periods=252gg; warning esplicito se serie < 1 anno |
| R7 | Forward EPS stime obsolete in YAML | Alta | Medio | Alert automatico se YAML > 90gg; reminder nel footer M6 |
| R8 | EDGAR EPS aggregato per indice SPY complesso | Alta | Medio | Usare FRED SP500EPS come primario; EDGAR per single-stock |
| R9 | Composite v2 diverge da v1 > 20% | Bassa | Medio | Test correlazione storica pre-deploy; rollback via feature flag |

---

## DIPENDENZE NUOVE (pyproject.toml)

```toml
# Aggiunte necessarie per ROADMAP v4

# BLOCCO 1 — nessuna nuova (FRED via FredSimpleClient + async aiohttp già presenti)

# BLOCCO 2 — scraping
beautifulsoup4 = ">=4.12,<5.0"   # Parsing HTML Investing.com
lxml = ">=5.0,<6.0"              # Parser HTML veloce per BeautifulSoup

# BLOCCO 3 — Excel parsing
openpyxl = ">=3.1,<4.0"         # Parsing XLS/XLSX dataset Shiller
xlrd = ">=2.0,<3.0"             # Supporto .xls legacy

# BLOCCO 4 — DCC-GARCH avanzato (feature-flagged)
arch = {version = ">=6.3,<7.0", optional = true}  # DCC-GARCH via arch library

# statsmodels già presente per Granger (verificare pyproject.toml)
# scipy già presente per shrinkage (verificare)
```

---

## APPENDICE — SEGNALI LEAD INDICATOR PRIORITARI
### (Logica ispirata a Goldman Sachs Global Investment Research)

```
CATEGORIA A — Lead indicator più affidabili per mercato azionario (lead: 3-9 mesi)
  1. Initial Claims 4wk MA: rising +15% YoY → bear market warning
  2. JOLTS Quits Rate declining: workers insecure → hiring slowdown → earnings risk
  3. Beveridge Gap widening post-tight: mismatch strutturale → stagflation risk
  4. CAPE > 30 + ERP < 1%: valuation compression risk (long-term, 3-5Y)
  5. Credit spreads (HYG OAS) widening: risk appetite declining → equity risk

CATEGORIA B — Lead indicator di conferma (lead: 1-3 mesi)
  6. Economic Surprise Index declining: consensus top-down revision incoming
  7. Payroll revisions sistematicamente negative: employment weaker than reported
  8. Correlation regime shift (stress_coupling): diversification collapsing
  9. Composite Signal v2 cambia segno: sentiment/macro alignment shift
 10. Forward PE > trailing PE × 1.15: earning expectation troppo ottimiste

CATEGORIA C — Coincident / lagging (per conferma)
 11. NFP monthly: coincident, ma sector decomp ha valore lead
 12. Unemployment rate: lagging di 6-12 mesi rispetto al ciclo
 13. CAPE Shiller: eccellente per ritorni a 10 anni, inutile per timing breve
```

---

*MarketAI — Roadmap Analisi Mercato v4.0*  
*Baseline: v7.2.0 (131 test passing) · Estende ROADMAP_v6.0, ROADMAP_UNIFICATA_v2.0, ROADMAP_ANALISI_PREVISIONE_v1.0*  
*12 settimane · 6 blocchi · 32 convenzioni rispettate*  
*Target: v7.4.0 — ≥ 200 test · 4 nuove migrations · 7 nuove pagine · Strumento di vantaggio informativo professionale*  
*⚠️ Disclaimer: Software a scopo informativo e educativo. Non costituisce consulenza finanziaria.*
