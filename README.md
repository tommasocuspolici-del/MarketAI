# FRED Data Universe

**Script:** `scripts/bulk_fred_download.py`
**Fetcher:** `engine/market_data/fetchers/fred_bulk_fetcher.py`
**Fonte:** Federal Reserve Economic Data (St. Louis Fed)
**Rate limit:** 120 req/min, illimitato giornaliero (gratuito, API key opzionale)

---

## Panoramica

MarketAI scarica **600+ serie macroeconomiche** da FRED tramite `FREDBulkFetcher`. Questi dati alimentano le pagine M* (Macro Signals), il Composite Signal K1, lo Stress Testing e i modelli predittivi macro.

**Download iniziale:** ~10 minuti a rate limitato.
**Aggiornamento:** le serie vengono aggiornate automaticamente con frequenza variabile (giornaliera, settimanale, mensile, trimestrale).

---

## Categorie di serie e ID critici

### Crescita e PIL

| Serie FRED ID | Descrizione | Frequenza | Usata in |
|---|---|---|---|
| `A191RL1Q225SBEA` | Real GDP Growth Rate (%) | Trimestrale | E6, M4, stress test |
| `GDP` | GDP livello in miliardi $ | Trimestrale | ⚠️ NON usare per % crescita |
| `GDPC1` | Real GDP livello | Trimestrale | Calcoli interni |

**REGOLA CRITICA — Bug B5:** Mai usare `"GDP"` per mostrare crescita percentuale. La serie `"GDP"` è il livello in miliardi di dollari (es. 28.000). Usare **sempre** `"A191RL1Q225SBEA"` per il tasso di crescita percentuale del PIL reale.

### Inflazione

| Serie FRED ID | Descrizione | Frequenza |
|---|---|---|
| `CPIAUCSL` | CPI All Items (livello) | Mensile |
| `CPILFESL` | Core CPI (esclude food ed energy) | Mensile |
| `PCEPI` | PCE Price Index (preferito dalla Fed) | Mensile |
| `T10YIE` | Breakeven Inflation 10 anni | Giornaliero |

### Mercato del lavoro

| Serie FRED ID | Descrizione | Frequenza | Pagina |
|---|---|---|---|
| `UNRATE` | Unemployment Rate (%) | Mensile | M3 |
| `ICSA` | Initial Claims settimanali | Settimanale | M3 |
| `CCSA` | Continuing Claims | Settimanale | M3 |
| `JTSJOL` | JOLTS: Job Openings | Mensile | M3 |
| `PAYEMS` | Non-Farm Payrolls | Mensile | M3 |

### Yield Curve

| Serie FRED ID | Descrizione | Frequenza | Pagina |
|---|---|---|---|
| `DGS2` | 2-Year Treasury Yield | Giornaliero | E3, M2 |
| `DGS5` | 5-Year Treasury Yield | Giornaliero | E3, M2 |
| `DGS10` | 10-Year Treasury Yield | Giornaliero | E3, M2 |
| `DGS30` | 30-Year Treasury Yield | Giornaliero | E3, M2 |
| `T10Y2Y` | Spread 10Y-2Y (invertita se < 0) | Giornaliero | M2, K1 |
| `T10Y3M` | Spread 10Y-3M (principale leading indicator) | Giornaliero | M2 |

**Indicatore recessione:** `T10Y2Y < 0` (curva invertita) → probabilità recessione aumenta.

### Mercati finanziari e condizioni finanziarie

| Serie FRED ID | Descrizione | Frequenza |
|---|---|---|
| `VIXCLS` | CBOE VIX | Giornaliero |
| `BAMLH0A0HYM2` | HY Spread (BofA) | Giornaliero |
| `BAMLC0A0CM` | IG Spread (BofA) | Giornaliero |
| `DEXUSEU` | EUR/USD Exchange Rate | Giornaliero |
| `NFCI` | Chicago Fed National Financial Conditions Index | Settimanale |

### Settore immobiliare

| Serie FRED ID | Descrizione | Frequenza |
|---|---|---|
| `HOUST` | Housing Starts | Mensile |
| `PERMIT` | Building Permits | Mensile |
| `CSUSHPINSA` | Case-Shiller Home Price Index | Mensile |
| `MORTGAGE30US` | Tasso mutuo 30 anni | Settimanale |

### PMI e Survey

| Serie FRED ID | Descrizione | Frequenza |
|---|---|---|
| `MANEMP` | Manufacturing Employment | Mensile |
| `DGORDER` | Durable Goods Orders | Mensile |
| `UMCSENT` | University of Michigan Consumer Sentiment | Mensile |
| `USSLIND` | Leading Index | Mensile |

---

## Mapping serie → pagine dashboard

| Pagina | Serie principali usate |
|---|---|
| E3 Bonds | `DGS2`, `DGS5`, `DGS10`, `DGS30`, `T10Y2Y`, `BAMLH0A0HYM2`, `BAMLC0A0CM` |
| E6 Macro | `A191RL1Q225SBEA`, `CPIAUCSL`, `UNRATE`, `T10Y2Y`, `NFCI` |
| M1 VIX | `VIXCLS` |
| M2 Yield Curve | `DGS2`, `DGS5`, `DGS10`, `DGS30`, `T10Y2Y`, `T10Y3M` |
| M3 Labour Market | `UNRATE`, `ICSA`, `CCSA`, `JTSJOL`, `PAYEMS` |
| M4 Economic Surprise | Serie ad alta frequenza vs consensus |
| M5 Valuation P/E | Nessuna serie FRED diretta (dati azionari) |
| K1 Composite Signal | `T10Y2Y`, `VIXCLS`, `BAMLH0A0HYM2`, `A191RL1Q225SBEA` |

---

## FREDBulkFetcher — comportamento

```python
from engine.market_data.fetchers.fred_bulk_fetcher import FREDBulkFetcher

fetcher = FREDBulkFetcher(api_key=os.getenv("FRED_API_KEY"))  # key opzionale
n_loaded = fetcher.fetch_and_persist(
    series_ids=FRED_SERIES_LIST,   # lista di 600+ ID
    lookback_years=30,             # 30 anni di storico (Regola 31)
)
# Persistenza: DuckDB tabella macro_series
# Pipeline: fetch → clean → validate → duckdb_write → cache → return
# Rate limit: gestito da RateLimitManager ("fred": 120 req/min)
```

---

## Persistenza (DuckDB)

```sql
CREATE TABLE macro_series (
    series_id   VARCHAR NOT NULL,     -- "T10Y2Y", "UNRATE", ecc.
    date        DATE NOT NULL,
    value       DOUBLE,
    source      VARCHAR DEFAULT 'fred',
    updated_at  TIMESTAMPTZ,
    PRIMARY KEY (series_id, date)
);
-- Retention: 30 anni (Regola 31)
```

---

## Regole operative

```
❌ Mai usare "GDP" per crescita % → usare "A191RL1Q225SBEA" (Bug B5)
❌ Serie FRED non documentata aggiunta senza aggiornare questa pagina
❌ Download diretto senza passare per FREDBulkFetcher
   → Pipeline fetch→clean→validate→duckdb obbligatoria
```

---

## Aggiungere nuove serie FRED

```
□ 1. Identificare l'ID su https://fred.stlouisfed.org
□ 2. Aggiungere all'elenco in config/data_sources.yaml sezione "fred"
□ 3. Documentare in questa pagina con tabella e pagina dashboard
□ 4. Eseguire: poetry run python scripts/bulk_fred_download.py --series NEW_ID
□ 5. Verificare DataQualityReport: quality_score > 0.5
```

---

## Collegamenti

- [[Data Flow]] — come le serie FRED entrano nella pipeline
- [[Market Analysis Engine]] — utilizzo nelle pagine M* e K1
- [[Market Regime]] — T10Y2Y alimenta il regime detection
- [[Sentiment Engine]] — FRED complementa il sentiment macro
