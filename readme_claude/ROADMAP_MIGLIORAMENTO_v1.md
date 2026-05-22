# MarketAI — Roadmap Miglioramento Professionale
## Analisi, Ottimizzazione e Ampliamento Dati
### Versione 1.0 — Maggio 2026
> Baseline: v7.1.1 (86 test passing)
> Estende: ROADMAP_v6.0 · ROADMAP_UNIFICATA_v2.0 · ROADMAP_ANALISI_PREVISIONE_v1.0
> Segue le 32 convenzioni obbligatorie v6.0
> Fonte: Analisi dei 7 Nuclei Tematici + Estensione Dati

---

## PREMESSA — ANALISI CRITICA DEI NUCLEI TEMATICI

Le risposte ricevute sui 7 nuclei delineano un'ambizione architetturale corretta ma presentano
**tre debolezze strutturali** che questa roadmap corregge prima di implementare qualunque modulo:

**Debolezza 1 — Ordine di implementazione non rispetta le dipendenze**
I nuclei originali trattano Modelli Previsionali (N1) prima di Qualità Dati (N7), mentre
senza dati puliti e verificati ogni modello è costruito su sabbia. Questa roadmap inverte
la priorità: infrastruttura dati → regime → segnali → modelli → portfolio → UI.

**Debolezza 2 — Mancanza di data expansion sistematica**
Le risposte fanno riferimento a fonti esistenti senza specificare quali nuove serie,
frequenze e provider amplierebbero concretamente la qualità degli indicatori.
Questa roadmap aggiunge un **Blocco 0 — Data Universe Expansion** dedicato.

**Debolezza 3 — Feature flag e anti-pattern non sempre rispettati**
Alcune proposte (es. Gamma Exposure, TFT, LSTM) richiedono dipendenze pesanti che
devono essere controllate da feature flag e non inserite di default.
Ogni modulo pesante in questa roadmap ha il suo flag esplicito.

---

## MAPPA DELLE DIPENDENZE GLOBALE

```
┌──────────────────────────────────────────────────────────────────────┐
│             BASELINE: v7.1.1 (86 test) + Settimane 0–9               │
│             Roadmap Unificata 2.0 completata                          │
└─────────────────────────────┬────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
  ┌───────────────┐  ┌────────────────┐  ┌────────────────────┐
  │  FASE A       │  │  FASE B        │  │  FASE C            │
  │  Data Universe│  │  Signal        │  │  Modelli           │
  │  Expansion    │  │  Quality       │  │  Previsionali      │
  │  (Sett. 1–3)  │  │  Framework     │  │  Avanzati          │
  │               │  │  (Sett. 4–6)   │  │  (Sett. 7–10)      │
  └───────┬───────┘  └───────┬────────┘  └────────┬───────────┘
          └──────────────────┴──────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
  ┌───────────────┐  ┌────────────────┐  ┌────────────────────┐
  │  FASE D       │  │  FASE E        │  │  FASE F            │
  │  Risk &       │  │  Backtesting   │  │  Derivati e        │
  │  Portfolio    │  │  Professionale │  │  Volatilità        │
  │  Avanzato     │  │  (Sett. 14–16) │  │  (Sett. 17–19)     │
  │  (Sett. 11–13)│  │                │  │                    │
  └───────┬───────┘  └───────┬────────┘  └────────┬───────────┘
          └──────────────────┴──────────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │  FASE G            │
                    │  UI, Osservabilità │
                    │  e Hardening       │
                    │  (Sett. 20–22)     │
                    └────────────────────┘
```

---

## NUOVE CONVENZIONI (33–40) — Aggiuntive alle 32 v6.0

```
━━ NUOVE — ROADMAP MIGLIORAMENTO v1.0 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

33. MODEL_REGISTRY    Ogni modello ML/statistico viene registrato in DuckDB
                      (tabella model_registry) con: iperparametri, hash dataset,
                      metriche OOS, data training, versione. Nessun modello in
                      produzione senza entry nel registro.

34. CONFORMAL_CI      Gli intervalli di confidenza usano Conformal Prediction
                      adattiva per serie temporali (split conformal con finestre
                      mobili). Nessun intervallo basato solo su ±σ gaussiana.

35. LOOK_AHEAD_DATA   Ogni serie temporale ha un campo publication_lag_days.
                      Il vintage database (tabella data_vintages) traccia le
                      revisioni. Nessun dato usato prima della data di
                      pubblicazione effettiva (as-of semantics).

36. IC_DYNAMIC        L'Information Coefficient è calcolato dinamicamente
                      (rolling 252gg, Spearman) per ogni segnale dopo ogni
                      chiusura di mercato. Nessun IC statico in produzione.

37. SIGNAL_REGISTRY   Ogni segnale ha una Signal Scorecard persistita in DuckDB:
                      IC medio, IC std, t-stat, Sharpe long-short, hit rate,
                      alpha decay half-life, staleness flag.

38. DATA_UNIVERSE     Il file config/data_universe.yaml definisce l'elenco
                      completo di tutte le serie dati usate dal sistema (FRED,
                      provider, frequenza, lag, retention). È la fonte di verità
                      unica per la copertura dati.

39. ADAPTIVE_WEIGHTS  I pesi del CompositeSignalAggregator non sono costanti.
                      Vengono aggiornati mensilmente tramite ridge regression
                      OOS. I pesi correnti sono persistiti in DuckDB.

40. FEATURE_PARITY    Nessun modulo ML viene attivato senza un test di parità
                      rispetto al baseline (random walk o media storica). Un
                      modello che non batte il baseline viene disabilitato
                      automaticamente e segnalato.
```

---

## ANTI-PATTERN AGGIUNTIVI

```
━━ MODELLI E SEGNALI ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ IC statico hardcoded nei segnali    → IC rolling 252gg sempre
❌ Pesi fissi nel CompositeSignal      → adaptive weights mensile
❌ Intervallo CI basato su ±σ          → Conformal Prediction adattiva
❌ Modello senza entry in model_registry → registrazione obbligatoria
❌ Modello in-sample selection         → walk-forward o CPCV sempre
❌ Feature con look-ahead nel training  → as-of semantics obbligatorie
❌ Modello pesante senza feature flag  → flag obbligatorio (default: false)
❌ Signal senza alpha decay analysis   → half-life calcolato sempre

━━ DATI ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ Serie FRED senza publication_lag    → lag registrato in data_universe.yaml
❌ Revisione dato non tracciata        → data_vintages obbligatorio
❌ Serie con < 5 anni di storia        → warning DataQualityReport
❌ Cross-source senza validazione      → CrossSourceValidator sempre
❌ Audit log assente su fetch/write    → append-only su audit_log DuckDB

━━ PORTFOLIO E RISK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ CVaR senza segmentazione per regime → CVaR condizionale sempre
❌ Backtest senza PSR                  → Probabilistic Sharpe Ratio sempre
❌ N strategie senza correzione test   → Benjamini-Hochberg FDR obbligatorio
❌ Portafoglio senza Component VaR     → contributo marginale per posizione
```

---

## STRUTTURA DIRECTORY — NUOVI MODULI

```
market_ai/
│
├── engine/
│   ├── analytics/
│   │   ├── signals/                         ★ NUOVO — Fase B
│   │   │   ├── __init__.py
│   │   │   ├── ic_calculator.py             # IC rolling Spearman per segnale
│   │   │   ├── signal_scorecard.py          # Scorecard centralizzata segnali
│   │   │   ├── alpha_decay_analyzer.py      # Half-life decay per segnale
│   │   │   ├── signal_combiner.py           # Ensemble con pesi adattativi
│   │   │   ├── signal_normalizer.py         # Cross-sectional + time-series
│   │   │   └── staleness_detector.py        # Flag stale per ogni segnale
│   │   │
│   │   ├── regime/                          ★ ESPANSO — Fase B
│   │   │   ├── hmm_macro_regime.py          # HMM 4 stati su 15+ variabili
│   │   │   ├── regime_timeline.py           # macro_regime_timeline DuckDB
│   │   │   ├── regime_change_detector.py    # CUSUM + Bai-Perron
│   │   │   ├── conditional_returns.py       # Rendimenti attesi per regime
│   │   │   └── international_regime.py      # Regime differenziale USA/EU/CN
│   │   │
│   │   ├── forecasting/                     ★ ESPANSO — Fase C
│   │   │   ├── model_registry.py            # Registro modelli su DuckDB
│   │   │   ├── conformal_predictor.py       # Conformal Prediction adattiva
│   │   │   ├── ensemble_combiner.py         # Stacking dinamico con Kalman
│   │   │   ├── nowcaster.py                 # MIDAS + bridge equations
│   │   │   ├── var_vecm_engine.py           # VAR/VECM per macro
│   │   │   ├── tft_engine.py                # Temporal Fusion Transformer
│   │   │   ├── signal_decay_curve.py        # Curva decadimento skill predittivo
│   │   │   └── scenario_tree_builder.py     # Scenario tree probabilistico
│   │   │
│   │   ├── risk/                            ★ ESPANSO — Fase D
│   │   │   ├── cvar_regime_calculator.py    # CVaR condizionale al regime
│   │   │   ├── factor_risk_attribution.py  # Decomposizione Barra-style
│   │   │   ├── component_var.py             # Marginal + Component VaR
│   │   │   ├── liquidity_analyzer.py        # ADTV, giorni liquidazione
│   │   │   └── tail_hedge_advisor.py        # Copertura tail risk
│   │   │
│   │   └── derivatives/                     ★ ESPANSO — Fase F
│   │       ├── vol_surface_svi.py           # Fit SVI/SABR sulla superficie
│   │       ├── vrp_calculator.py            # Volatility Risk Premium
│   │       ├── gex_calculator.py            # Gamma Exposure per strike
│   │       ├── vol_regime_markov.py         # Catena Markov su VIX
│   │       └── options_strategy_scanner.py  # Scanner strategie opzioni
│   │
│   ├── alpha_generation/
│   │   ├── composite_signal_v3.py           ★ AGGIORNATO — pesi adattativi
│   │   └── backtest_engine/                 ★ ESPANSO — Fase E
│   │       ├── wfo_runner.py                # Walk-Forward Optimization
│   │       ├── psr_calculator.py            # Probabilistic Sharpe Ratio
│   │       ├── fdr_corrector.py             # Benjamini-Hochberg FDR
│   │       ├── monte_carlo_paths.py         # 1000+ path con bootstrap
│   │       └── capacity_estimator.py        # Stima capacità segnale
│   │
│   └── data_universe/                       ★ NUOVO — Fase A
│       ├── universe_loader.py               # Carica config/data_universe.yaml
│       ├── vintage_manager.py               # Tracciamento revisioni serie
│       ├── lag_registry.py                  # Publication lag per ogni serie
│       └── cross_source_validator_v2.py     # Validazione estesa cross-fonte
│
├── shared/
│   ├── model_registry/                      ★ NUOVO — Fase C
│   │   ├── registry.py                      # CRUD registro modelli DuckDB
│   │   └── experiment_tracker.py            # Tracking esperimenti
│   │
│   └── db/
│       └── migrations/
│           └── duckdb/
│               ├── 20260701_010_signal_quality.sql      ★ NUOVO
│               ├── 20260701_011_model_registry.sql      ★ NUOVO
│               ├── 20260701_012_data_vintages.sql       ★ NUOVO
│               ├── 20260701_013_regime_timeline.sql     ★ NUOVO
│               └── 20260701_014_audit_log.sql           ★ NUOVO
│
├── config/
│   ├── data_universe.yaml                   ★ NUOVO — Fase A
│   ├── signal_registry.yaml                 ★ NUOVO — Fase B
│   ├── model_registry.yaml                  ★ NUOVO — Fase C
│   └── feature_flags.yaml                   # Aggiornato con nuovi flag
│
└── presentation/
    └── dashboard_engine/
        └── pages/
            ├── Q11_Signal_Scorecard.py      ★ NUOVO — Fase B
            ├── Q12_Model_Registry.py        ★ NUOVO — Fase C
            ├── Q13_Regime_Timeline.py       ★ NUOVO — Fase B
            ├── Q14_Risk_Attribution.py      ★ NUOVO — Fase D
            ├── Q15_Backtesting_Pro.py       ★ NUOVO — Fase E (sostituisce T1)
            └── Q16_Vol_Surface.py           ★ NUOVO — Fase F
```

---

## FASE A — DATA UNIVERSE EXPANSION (Settimane 1–3)
**Obiettivo:** Ampliare sistematicamente le serie dati disponibili per
migliorare la qualità di tutti gli indicatori prodotti dal sistema.
Senza questa base, ogni modulo successivo opera con dati insufficienti.

### A.1 — Nuove Serie FRED da Aggiungere

Le 28 serie attuali coprono prevalentemente USA macro di base.
L'espansione porta il totale a **85+ serie** suddivise per categoria:

```yaml
# config/data_universe.yaml — sezione FRED estesa

fred_series_expanded:

  # MERCATO DEL LAVORO — da 4 a 18 serie
  labour:
    existing:   [ICSA, CCSA, PAYEMS, UNRATE]
    new:
      - JTSJOL       # JOLTS Job Openings
      - JTSQUR       # Quits Rate
      - JTSHLR       # Hires Rate
      - U6RATE       # Sottoutilizzo allargato
      - LNS12300060  # Prime Age E-Pop Ratio (25-54)
      - CES0500000003 # Average Hourly Earnings
      - CES0500000008 # Average Weekly Hours
      - AWHMAN        # Avg Weekly Hours Manufacturing
      - CES1000000003 # Mining & Logging AHE
      - MANEMP        # Manufacturing Employment
      - USCONS        # Construction Employment
      - USGOVT        # Government Employment
      - SRVPRD        # Services Employment
      - AEHOUS        # Leisure & Hospitality

  # INFLAZIONE — da 3 a 12 serie
  inflation:
    existing:   [CPIAUCSL, CPIUFDSL, PCEPILFE]
    new:
      - CPILFESL     # CPI ex-food & energy
      - PPIFES        # PPI Final Demand Services
      - PPIACO        # PPI All Commodities
      - MICH          # Michigan Inflation Expectations 1Y
      - EXPINF1YR     # Cleveland Fed 1Y Inflation Expectations
      - EXPINF5YR     # Cleveland Fed 5Y Expectations
      - T10YIE        # 10Y Breakeven Inflation Rate
      - T5YIE         # 5Y Breakeven Inflation Rate
      - TREATIS       # TIPS 10Y Real Yield Proxy

  # TASSI E CURVA — da 4 a 14 serie
  rates:
    existing:   [DGS10, DGS3MO, T10Y3M, FEDFUNDS]
    new:
      - DGS1          # 1Y Treasury
      - DGS2          # 2Y Treasury
      - DGS5          # 5Y Treasury
      - DGS30         # 30Y Treasury
      - DFII10        # 10Y TIPS (Real)
      - SOFR          # SOFR (sostituisce LIBOR)
      - DPRIME        # Prime Rate
      - TB3MS         # T-Bill 3M
      - GS1M          # 1M Treasury
      - BAMLC0A0CM    # Investment Grade OAS

  # CRESCITA E CICLO — da 3 a 15 serie
  growth:
    existing:   [GDPC1, INDPRO, ISRATIO]
    new:
      - RSAFS         # Retail Sales SA
      - MRTSSM44X72USS # Core Retail (ex-gas, auto)
      - TOTALSA       # Total Vehicle Sales
      - HOUST         # Housing Starts
      - PERMIT        # Building Permits
      - NHSUSSPT      # New Home Sales
      - EXRHVZNQ      # Existing Home Sales (via release)
      - DSPIC96       # Real Disposable Personal Income
      - PCE           # Personal Consumption Expenditure
      - A067RL1Q156SBEA # Corporate Profits (trimestrale)
      - BOPGSTB       # Trade Balance
      - MCUMFN        # Capacity Utilization Manufacturing
      - IPMAN         # Industrial Production Manufacturing

  # CREDITO E CONDIZIONI FINANZIARIE — da 3 a 10 serie
  credit:
    existing:   [BAMLH0A0HYM2, TEDRATE, NFCI]
    new:
      - BAMLH0A2HYS   # HY Short-Term OAS
      - BAMLC0A4CBBB  # BBB OAS
      - MSPUS         # Median House Price
      - DRSFRMACBS    # 30Y Mortgage Rate
      - DRCCLACBS     # Consumer Credit Delinquency Rate
      - TERMCBPER24NS # Auto Loan Rate 24M
      - SLQSNQ        # Senior Loan Officer Survey (Tightening)

  # INTERNAZIONALE — NUOVO (0 → 16 serie)
  international:
    new:
      # Eurozona
      - CPIEURO       # CPI Eurozona
      - LRHUTTTTEZM156S # Unemployment Rate Eurozona
      - IRLTLT01EZM156N # 10Y Germany Bund
      # UK
      - LRHUTTTTGBM156S # Unemployment UK
      - IRLTLT01GBM156N # 10Y Gilt
      # Giappone
      - LRHUTTTTJPM156S # Unemployment Japan
      # Cina
      - CHNCPIALLMINMEI # CPI Cina
      # Emergenti aggregati
      - EMVOVERALLEMV # EM Volatility
      # Commodity internazionali
      - PALLFNFINDEXM  # World Food Price Index (IMF)
      - PNRGINDEXM     # World Energy Price Index
      - PMETAUSDM      # World Metal Prices

  # SENTIMENT E SURVEY — NUOVO (0 → 10 serie)
  surveys:
    new:
      - UMCSENT       # University of Michigan Consumer Sentiment
      - CSCICP03USM665S # Conference Board Consumer Confidence
      - BSCICP03USM665S # Business Confidence Index
      - NAPM           # ISM Manufacturing PMI
      - NMFCI          # ISM Non-Manufacturing PMI
      - BOGMBASE       # Monetary Base (M0)
      - M2SL           # M2 Money Supply
      - WRMFSL         # Retail Money Funds (liquidità)
```

### A.2 — Nuovi Provider di Dati Esterni

```yaml
# Aggiunte a config/data_sources.yaml

providers_new:

  # 1. CBOE — Dati derivati e volatilità
  cboe:
    base_url: "https://cdn.cboe.com/api/global/delayed_quotes"
    series:
      - ^VIX         # VIX spot (già presente)
      - ^VIX9D       # VIX 9 giorni
      - ^VXV         # VIX 3 mesi
      - ^VXST        # VIX short-term (9gg)
      - ^SKEW        # CBOE SKEW Index
      - ^VXN         # NASDAQ Volatility
      - ^RVX         # Russell 2000 Volatility
      - ^OVX         # Oil Volatility
      - ^GVZ         # Gold Volatility
    rate_limit: 30/min
    feature_flag: cboe_vol_data

  # 2. BLS — Bureau of Labor Statistics API gratuita
  bls:
    base_url: "https://api.bls.gov/publicAPI/v2"
    series:
      - CES0000000001  # Total Nonfarm Employment
      - LNS14000000    # Unemployment Rate (alternativo FRED)
      - LNS12032194    # Part-time for economic reasons
      - CUUR0000SA0    # CPI-U All Urban (cross-check FRED)
      - PRS85006092    # Nonfarm Business Productivity
      - PRS85006112    # Unit Labor Costs
    api_key_env: BLS_API_KEY
    rate_limit: 500/day (no key), 25000/day (with key)
    feature_flag: bls_api

  # 3. CFTC — Commitment of Traders (gratuito, settimanale)
  cftc:
    base_url: "https://www.cftc.gov/dea/newcot"
    reports:
      - futures_only   # Posizioni futures per asset class
      - disaggregated  # Commercial, Non-Commercial, Non-Reportable
    instruments:
      - ES             # S&P 500 E-mini
      - NQ             # NASDAQ 100 E-mini
      - GC             # Gold futures
      - CL             # Crude Oil WTI
      - ZN             # 10Y Treasury Note
      - 6E             # Euro FX
      - ^VX            # VIX futures
    rate_limit: 5/min
    feature_flag: cot_data

  # 4. World Bank API (gratuito, dati annuali)
  world_bank:
    base_url: "https://api.worldbank.org/v2"
    indicators:
      - NY.GDP.MKTP.KD.ZG   # GDP growth (annual %)
      - FP.CPI.TOTL.ZG      # CPI inflation
      - SL.UEM.TOTL.ZS      # Unemployment (% total labor force)
      - NE.EXP.GNFS.ZS      # Exports (% of GDP)
    countries: [US, EU, CN, JP, GB, DE, IT, FR, BR, IN]
    rate_limit: 30/min
    feature_flag: world_bank_data

  # 5. OECD API (gratuito, dati mensili/trimestrali)
  oecd:
    base_url: "https://stats.oecd.org/SDMX-JSON/data"
    datasets:
      - DP_LIVE/./CLI.OECD+G20  # Composite Leading Indicators
      - DP_LIVE/./BCI.OECD+G7   # Business Confidence Index
      - DP_LIVE/./CCI.OECD+G7   # Consumer Confidence Index
    rate_limit: 10/min
    feature_flag: oecd_data

  # 6. Econoday (scraping calendario macro)
  econoday:
    base_url: "https://mny.econoday.com"
    data:
      - consensus_forecasts    # Consensus per ogni rilascio
      - economic_calendar      # Calendario prossimi rilasci
      - historical_surprises   # Sorprese storiche per indicatore
    rate_limit: 5/min
    feature_flag: economic_surprise_engine

  # 7. Federal Reserve H.8 — Aggregati bancari
  fed_h8:
    base_url: "https://www.federalreserve.gov/releases/h8"
    series:
      - Total Loans & Leases (commercial banks)
      - Real estate loans
      - Commercial & industrial loans
      - Consumer loans
    frequency: weekly
    rate_limit: 5/min
    feature_flag: fed_banking_data

  # 8. SEC EDGAR — Extended (già presente ma da ampliare)
  sec_edgar_extended:
    additional_forms:
      - 13F          # Posizioni fondi hedge (trimestrale)
      - Form4        # Insider trading (quotidiano)
      - 8-K          # Current reports (event-driven)
    companies_universe: SP500 + Russell 2000 (2500+ ticker)
    feature_flag: sec_edgar_extended
```

### A.3 — Vintage Database e As-Of Semantics

```python
# shared/db/migrations/duckdb/20260701_012_data_vintages.sql

-- Tracciamento revisioni serie storiche (as-of semantics)
CREATE TABLE IF NOT EXISTS data_vintages (
    series_id          VARCHAR     NOT NULL,
    observation_date   DATE        NOT NULL,
    vintage_date       DATE        NOT NULL,     -- data in cui il valore era disponibile
    value              DOUBLE      NOT NULL,
    is_revised         BOOLEAN     DEFAULT FALSE,
    revision_count     INTEGER     DEFAULT 0,
    first_published    DATE,
    source             VARCHAR,
    PRIMARY KEY (series_id, observation_date, vintage_date)
);

-- Registro dei lag di pubblicazione per ogni serie
CREATE TABLE IF NOT EXISTS publication_lag_registry (
    series_id              VARCHAR     PRIMARY KEY,
    typical_lag_days       INTEGER,    -- ritardo tipico dal periodo osservato
    max_lag_days           INTEGER,    -- ritardo massimo storico
    revision_frequency     VARCHAR,    -- 'none'|'monthly'|'quarterly'|'annual'
    revision_magnitude_avg DOUBLE,     -- revisione media assoluta (%)
    source                 VARCHAR,
    last_updated           TIMESTAMPTZ DEFAULT NOW()
);

-- Audit log immutabile
CREATE TABLE IF NOT EXISTS audit_log (
    log_id          BIGINT      DEFAULT nextval('seq_audit_log'),
    event_ts        TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    operation       VARCHAR     NOT NULL,   -- 'fetch'|'write'|'delete'|'migrate'
    source          VARCHAR,
    endpoint        VARCHAR,
    data_hash_sha256 VARCHAR,
    record_count    INTEGER,
    outcome         VARCHAR,    -- 'success'|'partial'|'error'
    error_msg       VARCHAR,
    duration_ms     DOUBLE,
    PRIMARY KEY (log_id)
);

CREATE SEQUENCE IF NOT EXISTS seq_audit_log START 1;
```

### Definition of Done — Fase A

```
□ config/data_universe.yaml creato con 85+ serie documentate
□ 57 nuove serie FRED scaricate e in DuckDB (estensione da 28 a 85)
□ BLS API integrata con API key (25k req/day vs 500 free)
□ CFTC COT report: parsing settimanale funzionante, 5 strumenti in DB
□ OECD CLI + BCI + CCI: dati 10 anni presenti in DuckDB
□ World Bank GDP: 10 paesi × 4 indicatori in DuckDB
□ data_vintages: tracciamento revisioni attivo su almeno 20 serie FRED
□ publication_lag_registry: lag documentati per tutte le 85+ serie
□ audit_log: ogni fetch/write registrato (test su 100 operazioni)
□ CrossSourceValidatorV2: check tra FRED e BLS per overlapping series
□ Scheduler: tutti i nuovi job aggiunti con trigger corretti per frequenza
□ DataQualityReport: aggiornato per includere punteggio vintage coverage
□ test_data_universe.py: coverage ≥ 80%
□ RateLimitManager: tutti i nuovi provider configurati in rate_limits.yaml
```

---

## FASE B — SIGNAL QUALITY FRAMEWORK (Settimane 4–6)
**Obiettivo:** Rendere ogni segnale misurabile, confrontabile e auto-diagnosticante.

### B.1 — IC Rolling Calculator

```python
# engine/analytics/signals/ic_calculator.py
"""
Information Coefficient Calculator — Convenzione 36.

Calcola IC Spearman rolling per ogni segnale vs rendimento forward.
IC = 0 → segnale casuale. IC > 0.05 → segnale debole ma reale.
IC > 0.10 → segnale significativo. IC < 0 → segnale inverso.

Regola 36: IC calcolato dopo ogni chiusura di mercato. Mai statico.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from shared.logger import get_logger

log = get_logger(__name__)


@dataclass
class ICResult:
    """Risultato IC per un segnale a un dato orizzonte."""
    signal_id:      str
    horizon_days:   int
    ic_mean:        float    # Media IC rolling
    ic_std:         float    # Std IC rolling (volatilità del segnale)
    ic_tstat:       float    # t-stat = IC_mean / (IC_std / sqrt(N))
    ic_ir:          float    # Information Ratio = IC_mean / IC_std
    hit_rate:       float    # % periodi con IC > 0
    is_significant: bool     # |t-stat| > 2.0


class ICCalculator:
    """Calcola IC rolling per un segnale rispetto a rendimenti forward."""

    def __init__(self, window: int = 252) -> None:
        self._window = window

    def compute(
        self,
        signal: pd.Series,
        forward_returns: pd.Series,
        signal_id: str,
        horizon_days: int,
    ) -> ICResult:
        """
        Args:
            signal:          Serie segnale normalizzato [-1, 1] o z-score.
            forward_returns: Rendimento forward a horizon_days periodi.
                             Deve essere allineato temporalmente (shift già applicato).
            signal_id:       Identificativo segnale.
            horizon_days:    Orizzonte forward.

        Returns:
            ICResult con statistiche rolling.
        """
        aligned = pd.concat([signal, forward_returns], axis=1).dropna()
        if len(aligned) < self._window:
            log.warning("ic_calculator.insufficient_data",
                        signal_id=signal_id, n=len(aligned))
            return ICResult(signal_id, horizon_days, 0.0, 1.0, 0.0, 0.0, 0.5, False)

        ic_series = aligned.rolling(self._window).apply(
            lambda x: stats.spearmanr(x[:, 0], x[:, 1])[0], raw=True
        ).iloc[:, 0]

        ic_clean   = ic_series.dropna().to_numpy(dtype=np.float64)
        ic_mean    = float(np.nanmean(ic_clean))
        ic_std     = float(np.nanstd(ic_clean)) if len(ic_clean) > 1 else 1.0
        ic_tstat   = ic_mean / (ic_std / np.sqrt(len(ic_clean))) if ic_std > 0 else 0.0
        ic_ir      = ic_mean / ic_std if ic_std > 0 else 0.0
        hit_rate   = float(np.mean(ic_clean > 0))

        log.info("ic_calculator.computed",
                 signal_id=signal_id, horizon=horizon_days,
                 ic_mean=round(ic_mean, 4), tstat=round(ic_tstat, 2))

        return ICResult(
            signal_id      = signal_id,
            horizon_days   = horizon_days,
            ic_mean        = round(ic_mean, 4),
            ic_std         = round(ic_std, 4),
            ic_tstat       = round(ic_tstat, 2),
            ic_ir          = round(ic_ir, 3),
            hit_rate       = round(hit_rate, 3),
            is_significant = abs(ic_tstat) > 2.0,
        )
```

### B.2 — Signal Quality Database Schema

```sql
-- shared/db/migrations/duckdb/20260701_010_signal_quality.sql

CREATE TABLE IF NOT EXISTS signal_scorecard (
    signal_id          VARCHAR     NOT NULL,
    snapshot_date      DATE        NOT NULL,
    horizon_days       INTEGER     NOT NULL,
    ic_mean            DOUBLE,
    ic_std             DOUBLE,
    ic_tstat           DOUBLE,
    ic_ir              DOUBLE,
    hit_rate           DOUBLE,
    sharpe_ls          DOUBLE,     -- Sharpe long-short portafoglio quintili
    alpha_decay_hl     INTEGER,    -- Half-life in giorni
    is_stale           BOOLEAN     DEFAULT FALSE,
    staleness_days     INTEGER     DEFAULT 0,
    is_significant     BOOLEAN,
    weight_current     DOUBLE,     -- Peso corrente nel composite
    PRIMARY KEY (signal_id, snapshot_date, horizon_days)
);

-- Storico pesi adattativi del CompositeSignal
CREATE TABLE IF NOT EXISTS composite_weights_history (
    snapshot_date      DATE        NOT NULL,
    signal_id          VARCHAR     NOT NULL,
    weight             DOUBLE      NOT NULL,
    optimization_method VARCHAR,   -- 'ridge_oos'|'ic_proportional'|'kalman'
    PRIMARY KEY (snapshot_date, signal_id)
);

-- Regime timeline per HMM
CREATE TABLE IF NOT EXISTS macro_regime_timeline (
    snapshot_date      DATE        NOT NULL,
    regime_label       VARCHAR     NOT NULL,   -- expansion|slowdown|contraction|recovery
    prob_expansion     DOUBLE,
    prob_slowdown      DOUBLE,
    prob_contraction   DOUBLE,
    prob_recovery      DOUBLE,
    regime_confidence  DOUBLE,     -- max(prob_i)
    model_version      VARCHAR,
    PRIMARY KEY (snapshot_date)
);
```

### B.3 — HMM Macro Regime con Variabili Estese

**Miglioramento rispetto alla versione attuale:** l'HMM passa da 4 variabili
a 12 variabili osservate, includendo dati internazionali e dati di credito,
per una rilevazione di regime più robusta e anticipatoria.

```yaml
# config/hmm_regime.yaml

hmm_config:
  n_states: 4          # expansion, slowdown, contraction, recovery
  n_iter: 200
  covariance_type: full

# Variabili osservate per l'HMM (tutte mensili, z-score normalizzate)
observed_variables:
  domestic_growth:
    - INDPRO_MOM       # Var. mensile produzione industriale
    - RSAFS_MOM        # Var. mensile retail sales
    - PAYEMS_MOM       # Var. mensile occupati totali
    - NAPM             # ISM Manufacturing PMI

  financial_conditions:
    - T10Y3M           # Spread curva (inversione = recessione)
    - BAMLH0A0HYM2     # HY spread (credit stress)
    - NFCI             # Chicago Fed Financial Conditions
    - VIX_LEVEL        # Livello VIX (risk appetite)

  inflation_labour:
    - CPIAUCSL_YOY     # CPI YoY
    - UNRATE           # Tasso disoccupazione
    - JTSJOL_LEVEL     # JOLTS Job Openings

  international:
    - OECD_CLI_US      # CLI USA (leading indicator)

# Soglie confidenza
confidence_threshold: 0.80   # Sotto questa soglia → soft conditioning
retraining_trigger:
  cusum_threshold: 5.0        # Soglia CUSUM per ritraining
  min_months_between: 3       # Minimo 3 mesi tra retraining
```

### Definition of Done — Fase B

```
□ ICCalculator: IC rolling 252gg per ogni segnale del composite
□ Signal Scorecard: persistita in DuckDB dopo ogni chiusura di mercato
□ Alpha decay half-life calcolato per tutti i segnali attivi
□ Staleness detector: flag automatico se lag > soglia per serie sottostante
□ HMM Macro Regime: 4 stati su 12 variabili osservate
□ macro_regime_timeline: 10 anni di storia calcolata al primo avvio
□ CUSUM regime change detector: alert generato su break strutturale
□ Conditional returns: matrice rendimenti attesi per regime su DuckDB
□ CompositeSignal v3: pesi adattativi aggiornati mensilmente (ridge OOS)
□ composite_weights_history: storico pesi persistito
□ Q11_Signal_Scorecard: pagina dashboard funzionante
□ Q13_Regime_Timeline: timeline colorata per regime con overlay dati
□ test_signals/: coverage ≥ 85%
□ test_regime/: coverage ≥ 85%
□ Benchmark: ICCalculator.compute() 10 anni < 500ms
```

---

## FASE C — MODELLI PREVISIONALI AVANZATI (Settimane 7–10)
**Obiettivo:** Costruire un framework di forecasting multi-modello con
validazione statistica rigorosa e intervalli di confidenza calibrati.

### C.1 — Model Registry Schema

```sql
-- shared/db/migrations/duckdb/20260701_011_model_registry.sql

CREATE TABLE IF NOT EXISTS model_registry (
    model_id           VARCHAR     PRIMARY KEY,   -- UUID
    model_type         VARCHAR     NOT NULL,      -- 'arima'|'ridge'|'xgboost'|'lstm'|'tft'|'var'|'prophet'
    target_metric      VARCHAR     NOT NULL,
    horizon_days       INTEGER     NOT NULL,
    asset_class        VARCHAR,
    hyperparams        JSON,
    dataset_hash       VARCHAR,    -- SHA256 del training dataset
    train_start        DATE,
    train_end          DATE,
    val_start          DATE,
    val_end            DATE,
    mse_oos            DOUBLE,
    mae_oos            DOUBLE,
    mape_oos           DOUBLE,
    directional_acc    DOUBLE,     -- Hit rate direzionale OOS
    sharpe_predictive  DOUBLE,
    is_active          BOOLEAN     DEFAULT FALSE,
    is_baseline_beaten BOOLEAN     DEFAULT FALSE,  -- Convenzione 40
    registered_at      TIMESTAMPTZ DEFAULT NOW(),
    notes              VARCHAR
);

-- Risultati walk-forward per ogni fold
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
```

### C.2 — Conformal Prediction Adattiva

```python
# engine/analytics/forecasting/conformal_predictor.py
"""
Conformal Prediction adattiva per serie temporali.

Invece degli intervalli gaussiani ±σ, la Conformal Prediction garantisce
copertura (1-α) senza assunzioni distributive, usando i residui storici
come misura di non-conformità.

Per serie temporali: split conformal con finestre mobili (LOCART).
Il quantile di calibrazione viene ricalcolato ogni settimana su
una finestra rolling di 252 osservazioni.

Convenzione 34: Nessun CI basato solo su ±σ.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared.logger import get_logger

log = get_logger(__name__)


@dataclass
class ConformalInterval:
    """Intervallo di confidenza conforme per una previsione."""
    point_forecast: float
    lower:          float    # Percentile 10 (alpha=0.10)
    upper:          float    # Percentile 90
    coverage_level: float    # 1 - alpha (es. 0.90)
    n_calibration:  int      # Campioni usati per calibrazione
    is_valid:       bool     # False se n_calibration < 30


class AdaptiveConformalPredictor:
    """
    Conformal Prediction adattiva per serie temporali.

    Funziona su qualsiasi base model che produca una previsione puntuale.
    Il calibration set è una finestra mobile dei residui storici.
    """

    MIN_CALIBRATION: int = 30

    def __init__(
        self,
        alpha: float = 0.10,    # 1-alpha = livello di copertura (90%)
        calibration_window: int = 252,
    ) -> None:
        self._alpha  = alpha
        self._window = calibration_window
        self._calibration_residuals: list[float] = []

    def update(self, actual: float, forecast: float) -> None:
        """Aggiorna i residui di calibrazione con un nuovo osservazione."""
        residual = abs(actual - forecast)
        self._calibration_residuals.append(residual)
        if len(self._calibration_residuals) > self._window:
            self._calibration_residuals.pop(0)

    def predict_interval(self, point_forecast: float) -> ConformalInterval:
        """
        Calcola l'intervallo conforme per una previsione puntuale.

        Il quantile (1-alpha)(1+1/n) viene usato per garantire
        copertura marginale asintotica.
        """
        n = len(self._calibration_residuals)
        if n < self.MIN_CALIBRATION:
            log.warning("conformal.insufficient_calibration", n=n)
            return ConformalInterval(
                point_forecast = point_forecast,
                lower          = point_forecast,
                upper          = point_forecast,
                coverage_level = 1 - self._alpha,
                n_calibration  = n,
                is_valid       = False,
            )

        residuals = np.array(self._calibration_residuals, dtype=np.float64)
        # Quantile corretto per la finezza conforme
        q_level  = np.ceil((1 - self._alpha) * (n + 1)) / n
        q_level  = min(q_level, 1.0)
        q        = float(np.quantile(residuals, q_level))

        return ConformalInterval(
            point_forecast = point_forecast,
            lower          = point_forecast - q,
            upper          = point_forecast + q,
            coverage_level = 1 - self._alpha,
            n_calibration  = n,
            is_valid       = True,
        )
```

### C.3 — Walk-Forward Optimization con PSR e FDR

```python
# engine/alpha_generation/backtest_engine/psr_calculator.py
"""
Probabilistic Sharpe Ratio (Bailey & López de Prado, 2012).

Il PSR risponde a: "con quale probabilità il vero Sharpe
supera una soglia SR*, dato lo Sharpe osservato?"

Corregge per skewness negativa e kurtosi eccessa tipica dei
rendimenti finanziari, che gonfia lo Sharpe osservato.

PSR(SR*) = Φ( (SR_hat - SR*) * sqrt(T-1) /
              sqrt(1 - γ₃ * SR_hat + (γ₄-1)/4 * SR_hat²) )

dove γ₃ = skewness, γ₄ = kurtosis.
"""
from __future__ import annotations

import numpy as np
from scipy import stats


def probabilistic_sharpe_ratio(
    returns: np.ndarray,
    sr_benchmark: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """
    Calcola il Probabilistic Sharpe Ratio.

    Args:
        returns:          Array rendimenti periodici.
        sr_benchmark:     Sharpe di riferimento (default: 0 = random walk).
        periods_per_year: 252 per giornaliero, 12 per mensile.

    Returns:
        PSR in [0, 1]: probabilità che Sharpe reale > sr_benchmark.
    """
    T       = len(returns)
    sr_hat  = float(np.mean(returns) / np.std(returns, ddof=1)) * np.sqrt(periods_per_year)
    gamma_3 = float(stats.skew(returns))
    gamma_4 = float(stats.kurtosis(returns, fisher=False))  # kurtosis non eccessa

    # Deviazione standard dello Sharpe stimato
    variance_sr = (
        1 - gamma_3 * sr_hat / np.sqrt(periods_per_year)
        + (gamma_4 - 1) / 4 * (sr_hat / np.sqrt(periods_per_year)) ** 2
    ) / (T - 1)

    if variance_sr <= 0:
        return 0.5

    z = (sr_hat - sr_benchmark) / np.sqrt(variance_sr)
    return float(stats.norm.cdf(z))
```

### C.4 — Feature Flag per Modelli Pesanti

```yaml
# Aggiornamenti a config/feature_flags.yaml

# Blocco C — Modelli previsionali
conformal_prediction:   true    # Intervalli CP per tutti i modelli
model_registry:         true    # Registro centralizzato modelli
wfo_runner:             true    # Walk-Forward Optimization
psr_calculator:         true    # Probabilistic Sharpe Ratio
fdr_correction:         true    # Benjamini-Hochberg su N strategie
nowcasting_midas:       false   # MIDAS: richiede dati ad alta freq.
var_vecm_engine:        true    # VAR/VECM per macro (leggero)
xgboost_forecaster:     true    # XGBoost su feature macro
lstm_forecaster:        false   # LSTM: richiede GPU o CPU potente
tft_forecaster:         false   # TFT: PyTorch Forecasting, pesante
prophet_forecaster:     true    # Prophet: leggero, stagionalità
scenario_tree:          true    # Albero scenari probabilistico
signal_ensemble:        true    # Stacking dinamico segnali
adaptive_weights:       true    # Pesi adattativi composite signal
```

### Definition of Done — Fase C

```
□ Model Registry: ogni modello ha entry con hash dataset e metriche OOS
□ Conformal Prediction: intervalli calibrati per ARIMA, Ridge, Prophet, XGBoost
□ Walk-Forward: 5+ fold su dati reali, PSR calcolato per ogni strategia
□ Convenzione 40: test parity baseline (random walk) automatico
□ FDR correction: BH applicato quando si confrontano > 5 strategie
□ VAR/VECM: addestrato su 5 serie macro interconnesse (Fed Funds, CPI, GDP, HY, UNRATE)
□ XGBoost: feature importances visibili in Q12_Model_Registry
□ Prophet: stagionalità calcolata per tutti i ticker principali
□ Scenario tree: 3 rami (bear/base/bull) con probabilità stimate per ogni ticker
□ Ensemble combiner: pesi Kalman aggiornati mensilmente
□ Q12_Model_Registry: dashboard funzionante con confronto metriche OOS
□ test_forecasting/: coverage ≥ 80%
□ Benchmark: XGBoost forecast 10 ticker < 30s
□ Benchmark: Prophet forecast 1 ticker < 5s
□ MAPE OOS globale (media ticker principali) < 5% a 1W
```

---

## FASE D — RISK & PORTFOLIO AVANZATO (Settimane 11–13)
**Obiettivo:** Portare il risk engine a standard istituzionale.

### D.1 — CVaR Condizionale al Regime

Miglioramento della Convenzione 31 applicata al rischio:

```python
# engine/analytics/risk/cvar_regime_calculator.py
"""
CVaR Condizionale al Regime di Mercato.

Il CVaR standard assume che il futuro assomigli alla media storica.
In realtà, il rischio estremo è molto più alto durante i regimi di
contrazione e stress. Questo modulo stima il CVaR condizionato al
regime corrente, usando la distribuzione t-Student con gradi di
libertà stimati via MLE separatamente per ogni regime.

Output:
  · cvar_unconditional: CVaR su tutta la storia
  · cvar_by_regime: dict {regime: CVaR} condizionale
  · cvar_blended: CVaR pesato per probabilità regimi correnti
"""
```

### D.2 — Nuove Tabelle DuckDB per Risk Analytics

```sql
-- Aggiunta a migration 010

CREATE TABLE IF NOT EXISTS portfolio_risk_metrics (
    snapshot_date      DATE        NOT NULL,
    portfolio_id       VARCHAR     NOT NULL,
    var_95             DOUBLE,
    var_99             DOUBLE,
    cvar_95            DOUBLE,
    cvar_99            DOUBLE,
    cvar_expansion     DOUBLE,     -- CVaR condizionale per regime
    cvar_slowdown      DOUBLE,
    cvar_contraction   DOUBLE,
    max_drawdown_1y    DOUBLE,
    ulcer_index        DOUBLE,
    liquidity_days_90  DOUBLE,     -- Giorni per liquidare 90% portafoglio
    hhi_concentration  DOUBLE,     -- Herfindahl-Hirschman Index
    PRIMARY KEY (snapshot_date, portfolio_id)
);

CREATE TABLE IF NOT EXISTS position_risk_contribution (
    snapshot_date      DATE        NOT NULL,
    portfolio_id       VARCHAR     NOT NULL,
    ticker             VARCHAR     NOT NULL,
    marginal_var       DOUBLE,
    component_var      DOUBLE,
    pct_risk           DOUBLE,     -- % contributo al rischio totale
    adtv_30d           DOUBLE,
    days_to_liquidate  DOUBLE,
    PRIMARY KEY (snapshot_date, portfolio_id, ticker)
);
```

### Definition of Done — Fase D

```
□ CVaRRegimeCalculator: CVaR per tutti e 4 i regimi + blend pesato
□ t-Student MLE: gradi di libertà stimati separatamente per regime
□ ComponentVaR: contributo marginale per ogni posizione eToro
□ LiquidityAnalyzer: ADTV e giorni liquidazione per ogni posizione
□ FactorRiskAttribution: scomposizione varianza (Fama-French 5 fattori)
□ TailHedgeAdvisor: suggerimenti copertura put OTM / inverse ETF
□ portfolio_risk_metrics: record giornaliero dopo ogni chiusura
□ position_risk_contribution: tabella aggiornata per portafoglio eToro
□ Q14_Risk_Attribution: dashboard con torta fattori + tabella contributi
□ test_risk/: coverage ≥ 85%
□ Benchmark: ComponentVaR portafoglio 30 posizioni < 500ms
```

---

## FASE E — BACKTESTING PROFESSIONALE (Settimane 14–16)
**Obiettivo:** Elevare il backtesting a standard accademico/istituzionale.

### E.1 — Walk-Forward Optimization

La WFO sostituisce l'ottimizzazione in-sample e produce metriche valide
solo su periodi OOS mai visti durante il training.

```python
# Configurazione WFO in config/backtesting.yaml (aggiunta)

wfo:
  in_sample_years:    3
  out_of_sample_years: 1
  step_months:        3      # Scorrimento ogni trimestre
  min_oos_periods:    60     # Almeno 60 osservazioni OOS per fold
  metrics_oos_only:   true   # Metriche calcolate SOLO su OOS combinato

statistical_tests:
  psr_benchmark:      0.0    # Sharpe benchmark per PSR
  fdr_alpha:          0.05   # Livello FDR per multiple testing
  min_psr:            0.90   # Scarta strategie con PSR < 90%
```

### E.2 — Costi Realistici e Capacità

```python
# engine/alpha_generation/backtest_engine/capacity_estimator.py
"""
Stima la capacità massima di una strategia in USD.

Capacità = f(turnover, ADTV, participation_rate)
           = ADTV × participation_rate / turnover

Limite di partecipazione standard: 5-20% del volume giornaliero.
"""

PARTICIPATION_RATE: float = 0.05   # 5% del volume giornaliero
```

### Definition of Done — Fase E

```
□ WFO: 5+ fold su ogni strategia principale, metriche solo OOS
□ PSR: calcolato per ogni strategia, solo PSR > 0.90 in produzione
□ FDR: correzione BH applicata quando si confrontano > 5 strategie
□ Monte Carlo: 1000+ path con bootstrap a blocchi (preserva correlazioni)
□ Regime-conditional backtest: metriche per espansione/contrazione/etc.
□ Capacità stimata per ogni strategia attiva
□ Costi realistici: spread + market impact proporzionale a size
□ Drawdown analysis: ulcer index, durata media, tempo recupero
□ Q15_Backtesting_Pro: equity curve + underwater plot + WFO results
□ test_backtest_engine/: coverage ≥ 80%
□ Benchmark: WFO 5 fold × 10 anni < 60s
```

---

## FASE F — DERIVATI E VOLATILITÀ (Settimane 17–19)
**Obiettivo:** Modulo derivati completo con superficie di volatilità
parametrica, GEX e regime di volatilità.

### F.1 — Vol Surface SVI

```python
# engine/analytics/derivatives/vol_surface_svi.py
"""
Fit SVI (Stochastic Volatility Inspired) sulla superficie di volatilità.

Il modello SVI parametrizza il variance smile con 5 parametri per scadenza:
  w(k) = a + b*(ρ*(k-m) + sqrt((k-m)² + σ²))

dove k = log-moneyness, w = variance totale implicita.

Vantaggi: nessun butterfly arbitrage, pochi parametri, rapida calibrazione.
Output: superficie 3D interpolabile, parameter monitoring.

Feature flag: vol_surface_svi (default: true)
"""
```

### F.2 — Gamma Exposure (GEX)

```python
# engine/analytics/derivatives/gex_calculator.py
"""
Gamma Exposure del mercato (stima da dati pubblici).

GEX = Σ_strike (Γ × OI × spot²) per call - Σ (Γ × OI × spot²) per put

GEX > 0 → market maker long gamma → smorzamento volatilità
GEX < 0 → market maker short gamma → amplificazione volatilità

Dati: strike/OI da Yahoo Finance options chain (SPY, QQQ, SPX)
Limite: dati EOD, non intraday. Per intraday richiederebbe CBOE LiveVol.

Feature flag: gex_calculator (default: false — richiede fetch options chain)
"""
```

### F.3 — Vol Regime Markov

```python
# engine/analytics/derivatives/vol_regime_markov.py
"""
Catena di Markov discreta sui regimi di volatilità VIX.

Stati: calm (<15) | normal (15-25) | high (25-35) | extreme (>35)
Matrice di transizione stimata su storia VIX 2000-presente.
Uso: probabilità di transizione → strategia opzioni appropriata.

Regime calm → mean-reversion → short volatility (iron condor)
Regime extreme → mean-reversion → long volatility (straddle)
"""
```

### Definition of Done — Fase F

```
□ VRP calcolato: IV ATM 30gg − RV 30gg, z-score su DuckDB
□ Vol Regime Markov: 4 stati con matrice transizione su 20 anni VIX
□ Vol Surface SVI: fit su dati SPY options, RMSE < 0.5% su strike
□ SKEW alert: notifica quando SKEW > 145 (implementa Convenzione 26)
□ COT VIX: posizionamento netto speculatori in composite signal
□ GEX: calcolato per SPY e QQQ (se flag abilitato)
□ Options Strategy Scanner: suggerimento per ogni coppia (regime vol, outlook)
□ Q16_Vol_Surface: superficie 3D interattiva + regime + VRP gauge
□ test_derivatives/: coverage ≥ 80%
□ Benchmark: VRP calc 5 anni < 200ms
```

---

## FASE G — UI, OSSERVABILITÀ E HARDENING (Settimane 20–22)
**Obiettivo:** Portare l'intera piattaforma a standard di produzione completo.

### G.1 — Nuove Pagine Dashboard

| Pagina | Contenuto Chiave | Dipende da |
|--------|------------------|------------|
| Q11 Signal Scorecard | IC rolling, hit rate, staleness, alpha decay | Fase B |
| Q12 Model Registry | Confronto modelli OOS, PSR, benchmark parity | Fase C |
| Q13 Regime Timeline | HMM storia + breakdown probabilità + CUSUM alert | Fase B |
| Q14 Risk Attribution | Factor decomposition, Component VaR, liquidity | Fase D |
| Q15 Backtesting Pro | WFO equity curve, PSR, FDR, underwater plot | Fase E |
| Q16 Vol Surface | SVI 3D, VRP gauge, regime Markov, GEX | Fase F |

### G.2 — Reliability Dashboard (SLO/SLI)

Aggiornamento di S0 Health con metriche di affidabilità complete:

```python
# Aggiornamenti a presentation/dashboard_engine/pages/S0_Health_API_Status.py

SLO_TARGETS = {
    "api_success_rate_7d":     0.995,   # 99.5% successo fetch
    "scheduler_uptime_7d":     0.990,   # 99% uptime scheduler
    "data_freshness_critical": 1800,    # Max 30 min stale per serie critiche
    "p95_query_latency_ms":    2000,    # P95 < 2s
    "error_budget_monthly":    0.005,   # 0.5% error budget mensile
}
```

### G.3 — Hardening Finale

```
SanityChecker esteso:
  □ IC < -0.5 per segnale attivo → CRITICAL (segnale inverso inatteso)
  □ Composite signal drift > 0.3 in 24h senza news significative → WARN
  □ PSR < 0.5 per modello attivo → alert + disable automatico
  □ data_vintages: revisione > 20% su serie critica → CRITICAL
  □ VIX > 80 → tutti i CVaR ricalcolati immediatamente
  □ audit_log: ogni operazione registrata (test su 48h consecutive)

CrossSourceValidator:
  □ FRED vs BLS employment: discrepanza > 1% → WARN
  □ FRED CPI vs BLS CPI: discrepanza > 0.1% → WARN
  □ Yahoo VIX vs CBOE VIX: discrepanza > 0.5 → CRITICAL
```

### Definition of Done — Fase G (= Definition of Done Progetto)

```
□ 6 nuove pagine (Q11-Q16) caricate senza eccezioni su DB reale
□ S0 Health: SLO/SLI dashboard con consumo error budget mensile
□ Data Freshness Matrix: semaforo per tutte le 85+ serie
□ Audit log: 48h consecutive senza gap (test in staging)
□ mypy --strict: 0 errors su tutto il nuovo codice
□ ruff: 0 warnings
□ Coverage globale ≥ 80%, coverage engine/analytics/ ≥ 85%
□ Tutti i benchmark di latenza nei target (vedi sezione Metriche)
□ Backup: testato con restore su nuovo set di tabelle
□ CHANGELOG: aggiornato v7.1.1 → v8.0
□ config/data_universe.yaml: 85+ serie documentate e aggiornate
□ Tutti i feature flag documentati con descrizione e default
```

---

## MIGRATIONS DUCKDB COMPLETE — QUESTA ROADMAP

| File | Contenuto | Fase |
|------|-----------|------|
| `20260701_010_signal_quality.sql` | signal_scorecard, composite_weights_history | B |
| `20260701_011_model_registry.sql` | model_registry, wfo_results | C |
| `20260701_012_data_vintages.sql` | data_vintages, publication_lag_registry, audit_log | A |
| `20260701_013_regime_timeline.sql` | macro_regime_timeline, conditional_returns | B |
| `20260701_014_risk_extended.sql` | portfolio_risk_metrics, position_risk_contribution | D |

---

## FEATURE FLAGS — TUTTI I NUOVI FLAG

```yaml
# Aggiornamenti completi a config/feature_flags.yaml

# ━━ FASE A — Data Universe ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
bls_api:                      true    # BLS API con API key gratuita
cot_data:                     true    # CFTC Commitment of Traders
oecd_data:                    true    # OECD CLI + BCI + CCI
world_bank_data:              true    # World Bank indicatori
cboe_vol_data:                true    # CBOE VIX9D, VXV, SKEW, OVX, GVZ
fed_banking_data:             false   # Fed H.8 aggregati bancari (sperimentale)
sec_edgar_extended:           false   # 13F + Form4 (pesante)
data_vintage_tracking:        true    # Vintage DB per revisioni FRED
audit_log:                    true    # Log immutabile ogni operazione

# ━━ FASE B — Signal Quality ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ic_rolling_calculator:        true    # IC Spearman rolling per ogni segnale
signal_scorecard:             true    # Scorecard centralizzata
alpha_decay_analysis:         true    # Half-life decay per segnale
adaptive_composite_weights:   true    # Pesi adattativi ridge OOS
hmm_macro_regime_v2:          true    # HMM 4 stati su 12 variabili
regime_change_detection:      true    # CUSUM + Bai-Perron
international_regime:         false   # Regime differenziale USA/EU/CN (sperimentale)

# ━━ FASE C — Modelli Previsionali ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
conformal_prediction:         true    # Intervalli CP adattivi
model_registry:               true    # Registro modelli centralizzato
wfo_runner:                   true    # Walk-Forward Optimization
psr_calculator:               true    # Probabilistic Sharpe Ratio
fdr_correction:               true    # Benjamini-Hochberg FDR
var_vecm_engine:              true    # VAR/VECM per macro (leggero)
xgboost_forecaster:           true    # XGBoost su feature macro
prophet_forecaster:           true    # Prophet (leggero)
nowcasting_midas:             false   # MIDAS: dati alta frequenza
lstm_forecaster:              false   # LSTM: richiede GPU
tft_forecaster:               false   # TFT: PyTorch Forecasting pesante
scenario_tree:                true    # Albero scenari bear/base/bull
signal_ensemble_stacking:     true    # Ensemble con meta-learner

# ━━ FASE D — Risk & Portfolio ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cvar_regime_conditional:      true    # CVaR condizionale al regime
factor_risk_attribution:      true    # Barra-style decomposizione
component_var:                true    # Marginal + Component VaR
liquidity_risk_analyzer:      true    # ADTV e giorni liquidazione
tail_hedge_advisor:           false   # Suggerimenti hedge (sperimentale)
portfolio_optimizer_cvxpy:    true    # Ottimizzatore con vincoli

# ━━ FASE E — Backtesting Pro ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
monte_carlo_paths:            true    # 1000+ path bootstrap
regime_conditional_backtest:  true    # Metriche per regime
capacity_estimation:          true    # Stima capacità segnale

# ━━ FASE F — Derivati e Volatilità ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
vol_surface_svi:              true    # Fit SVI sulla superficie vol
vrp_calculator:               true    # Volatility Risk Premium
vol_regime_markov:            true    # Catena Markov su VIX
options_strategy_scanner:     false   # Scanner strategie opzioni
gex_calculator:               false   # Gamma Exposure (pesante)
cot_vix_signal:               true    # COT VIX → composite signal
```

---

## AMPLIAMENTO DATI — IMPATTO SUGLI INDICATORI ESISTENTI

| Indicatore Attuale | Dati Aggiunti | Miglioramento Atteso |
|---|---|---|
| **MacroConviction** | +57 serie FRED, OECD CLI, World Bank | Da 15 a 35+ feature, IC stimato +0.03-0.05 |
| **HMM Regime** | Serie internazionali (EU, JP, CN), Fed H.8 | Rilevazione regime più precoce (+2-4 settimane) |
| **LabourForecastEngine** | BLS extended (12 nuove serie), JOLTS completo | RMSE UNRATE stimato -15%, MAE NFP -20k |
| **VixSignalCalculator** | VIX9D, VXV, SKEW, GVZ, OVX (CBOE) | Segnali anticipatori su stress vol più accurati |
| **CompositeSignal** | COT data, VRP, IC adattativi | IC composito stimato +0.04-0.08 |
| **CreditStressAnalyzer** | BBB OAS, Mortgage Rate, Delinquency | Stress level più granulare, falsi positivi -30% |
| **InflationAnalysis** | Cleveland Fed expectations, Breakevens, PPI | Lead time inflazione +1-2 mesi |
| **EconomicSurpriseEngine** | BLS cross-check, OECD calendar | Copertura da 20 a 40+ indicatori per settore |
| **SentimentComposite** | COT completo 7 strumenti, Form4 insiders | 2 nuove fonti, riduzione data gaps |
| **StressTest** | Regime condizionale, tail hedging | Scenari forward-looking calibrati su regime corrente |

---

## METRICHE DI SUCCESSO — QUESTA ROADMAP

| Metrica | Target | Strumento |
|---|---|---|
| Serie dati totali in DuckDB | ≥ 85 (da 28) | Data Universe audit |
| IC medio CompositeSignal | > 0.08 (da ~0.04 stimato) | ICCalculator rolling |
| MAPE UNRATE 3M | < 0.25% (da < 0.30%) | WFO test set |
| MAE NFP 1M | < 60k (da < 80k) | WFO test set |
| PSR strategie attive | ≥ 0.90 per tutte | PSRCalculator |
| CVaR contraction vs unconditional | ≥ 1.5× | CVaRRegime |
| Vol surface SVI RMSE | < 0.5% su strike | SVI fit |
| Copertura conformal CI (90%) | 88-92% empiricamente | Backtesting CI |
| Signal staleness rate | < 5% segnali stale | Scorecard |
| Audit log copertura | 100% operazioni | audit_log count |
| Data freshness (serie critiche) | Lag < 30 min | Freshness Matrix |
| Model registry entries | ≥ 20 modelli attivi | Registry count |
| Coverage engine/analytics/ | ≥ 85% | pytest --cov |
| Coverage globale | ≥ 80% | pytest --cov |
| mypy --strict errors | 0 | mypy |
| ruff warnings | 0 | ruff |
| Pagina più pesante (Q15 WFO) | < 3.5s | Browser timing |

---

## TIMELINE RIEPILOGATIVA

```
Sett. 1–3   → FASE A: Data Universe Expansion (85+ serie, vintage DB, audit log)
Sett. 4–6   → FASE B: Signal Quality Framework (IC rolling, HMM v2, pesi adattativi)
Sett. 7–10  → FASE C: Modelli Previsionali Avanzati (registry, conformal CI, WFO, ensemble)
Sett. 11–13 → FASE D: Risk & Portfolio Avanzato (CVaR regime, factor attribution, component VaR)
Sett. 14–16 → FASE E: Backtesting Professionale (PSR, FDR, Monte Carlo, WFO completo)
Sett. 17–19 → FASE F: Derivati e Volatilità (SVI, VRP, vol regime, COT signal)
Sett. 20–22 → FASE G: UI, Osservabilità e Hardening (6 nuove pagine, SLO/SLI, hardening)
─────────────────────────────────────────────────────────────────────────────────────────
TOTALE: 22 settimane (~5.5 mesi) da baseline v7.1.1
VERSIONE RISULTANTE: v8.0 "Professional Analytics Platform"

PIETRE MILIARI (GO/NO-GO):
  Fine Fase A: 85+ serie in DuckDB, audit log attivo            → GO Fase B
  Fine Fase B: IC > 0.05 per almeno 5 segnali, HMM v2 validato → GO Fase C
  Fine Fase C: PSR ≥ 0.90 per modelli attivi, CP calibrated     → GO Fase D
  Fine Fase D: CVaR regime testato su GFC e COVID fixture        → GO Fase E
  Fine Fase E: WFO metriche OOS nei target per 3+ strategie     → GO Fase F
  Fine Fase F: SVI fit OK, COT segnale in composite             → GO Fase G
```

---

## RISCHI AGGIORNATI

| # | Rischio | Prob | Impatto | Mitigazione |
|---|---|---|---|---|
| R1 | FRED revisiona struttura API | Bassa | Alto | Vintage DB → cross-check su revisioni; fallback BLS |
| R2 | Econoday blocca scraping | Media | Medio | Cache aggressiva 7gg; fallback Investing.com; input manuale |
| R3 | CFTC cambia formato CSV COT | Media | Basso | Parser con test fixture locali; alert su parse error |
| R4 | TFT/LSTM OOM su macchina target | Alta | Basso | Feature flag default false; ridge/XGBoost come baseline |
| R5 | IC baseline troppo basso (<0.02) | Media | Alto | Revisionare normalizzazione segnali; aggiungere dati Fase A |
| R6 | SVI non converge su alcuni ticker | Media | Basso | Fallback su IV ATM interpolata; flag per ticker problematici |
| R7 | PSR < 0.90 per strategie correnti | Media | Medio | Disabilitare automaticamente (Convenzione 40); rianalizzare |
| R8 | WFO 22 fold troppo lento (> 5min) | Media | Basso | Parallelizzazione joblib; ridurre a 10 fold se necessario |
| R9 | 85+ serie: DuckDB lento su query | Bassa | Medio | Indici su (series_id, observation_date DESC) su ogni tabella |
| R10 | Vintage DB cresce troppo (> 50GB) | Bassa | Medio | Retention: vintage > 20 anni → Parquet archive |

---

## PROMPT PER PROSSIMA SESSIONE (v8.0 — Fase A)

```
Continuo lo sviluppo di MarketAI Professional Edition.

Stato attuale: v7.1.1 applicata + Roadmap Unificata 2.0 (Sett. 0-9 completate)
Nuova roadmap caricata: ROADMAP_MIGLIORAMENTO_v1.0

Prossimo step (v8.0 — Fase A): Data Universe Expansion
Obiettivo: portare le serie dati da 28 a 85+ in 3 settimane.

Settimana 1:
  1. Creare config/data_universe.yaml con 85+ serie documentate
  2. Migration DuckDB 20260701_012_data_vintages.sql
     (tabelle: data_vintages, publication_lag_registry, audit_log)
  3. Scaricare 57 nuove serie FRED e persistirle in DuckDB
  4. Integrare BLS API (API key gratuita)

Settimana 2:
  5. CFTC COT parser (5 strumenti)
  6. OECD CLI + BCI + CCI (10 anni storia)
  7. CBOE: VIX9D, VXV, SKEW, OVX, GVZ
  8. CrossSourceValidatorV2 per overlapping series FRED/BLS

Settimana 3:
  9. VintageManager: tracciamento revisioni FRED attivo
  10. Audit log: ogni fetch/write registrato
  11. DataQualityReport aggiornato con punteggio vintage coverage
  12. Scheduler: tutti i nuovi job aggiunti

Segui le 32 convenzioni v6.0 + nuove convenzioni 33-40.
Procedi con la Settimana 1 della Fase A.
```

---

*MarketAI — Roadmap Miglioramento Professionale v1.0*
*Baseline: v7.1.1 (86 test passing)*
*22 settimane · 7 Fasi · 8 nuove convenzioni · 32 convenzioni base rispettate*
*Target release: v8.0 "Professional Analytics Platform"*
*⚠️ Disclaimer: Software a scopo informativo e educativo.*
*Non costituisce consulenza finanziaria. Consultare un professionista abilitato.*
