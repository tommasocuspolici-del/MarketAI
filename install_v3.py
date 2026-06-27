# Sentiment Engine

**Introdotto in:** v10 (base) · v12 (8 fonti complete)
**File sorgente:** `engine/analytics/sentiment/`
**Stato:** Aggregatore di 8 fonti indipendenti in un composite score

---

## Panoramica

Il Sentiment Engine aggrega **8 fonti indipendenti** in un composite score [0, 100] che rappresenta il sentiment di mercato corrente. Un score basso indica estremo pessimismo (paura), un score alto indica estremo ottimismo (avidità).

**Regola anti-pattern:** `❌ Sentiment da < 3 fonti → minimo 3 fonti indipendenti sempre`

---

## Le 8 Fonti

| # | Fonte | Tipo | Aggiornamento | API / Fetcher |
|---|---|---|---|---|
| 1 | CNN Fear & Greed Index | Composite | Giornaliero | Scraping via `beautifulsoup4` |
| 2 | Crypto Fear & Greed | Cripto | Giornaliero | API pubblica `alternative.me` |
| 3 | AAII Investor Sentiment | Survey | Settimanale | `pandas_datareader` o scraping |
| 4 | Put/Call Ratio | Options | Giornaliero | Yahoo Finance (^PCR) |
| 5 | COT Report (Commitment of Traders) | Futures | Settimanale | CFTC API |
| 6 | Insider Trading | Equity | Variabile | Finnhub insider data |
| 7 | Short Interest | Equity | Bisettimanale | Finnhub / SEC |
| 8 | Finnhub News Sentiment | NLP | Tempo reale | `finnhub-python` + `vaderSentiment` |

---

## Struttura del modulo

```
engine/analytics/sentiment/
├── aggregator.py          ← Orchestratore: chiama tutte le fonti e combina
├── composite_score.py     ← SentimentScore dataclass e logica di aggregazione
└── sources/
    ├── cnn_fear_greed.py  ← Scraper CNN F&G
    ├── crypto_fear_greed.py ← API alternative.me
    ├── aaii_survey.py     ← AAII Investor Survey
    ├── put_call_ratio.py  ← Yahoo Finance options data
    ├── cot_report.py      ← CFTC COT data
    ├── insider_trading.py ← Finnhub insider data
    ├── short_interest.py  ← Finnhub / SEC short data
    └── news_sentiment.py  ← Finnhub news + VADER NLP
```

---

## Output: SentimentScore

```python
from engine.analytics.sentiment.composite_score import SentimentScore

# Generato da aggregator.py
score = SentimentScore(
    composite=42.5,           # [0, 100] — 50 = neutro, < 25 = estremo pessimismo
    sources={
        "cnn_fear_greed": 38.0,
        "crypto_fear_greed": 29.0,
        "aaii_bearish_pct": 45.0,     # % investitori ribassisti
        "put_call_ratio": 1.15,        # > 1.0 = più put che call (ribassista)
        "cot_net_positioning": -0.3,   # negativo = posizionamento short netto
        "insider_buy_sell_ratio": 0.8, # < 1.0 = più vendite che acquisti
        "short_interest_pct": 3.2,     # % float in short
        "news_sentiment_score": 0.35,  # VADER compound [-1, +1] normalizzato [0,100]
    },
    weights={...},             # pesi da OP_CONFIG o config YAML
    contrarian_signal=None,    # "BUY" | "SELL" | None
    timestamp=datetime.utcnow(),
)
```

---

## Pesi configurabili

I pesi delle 8 fonti sono in `config/sentiment_sources.yaml` e acceduti tramite `OP_CONFIG`:

```yaml
# config/sentiment_sources.yaml
cnn_fear_greed:      0.20    # fonte più seguita dal mercato
crypto_fear_greed:   0.10    # correlato ma specifico crypto
aaii_survey:         0.15    # survey retail investor
put_call_ratio:      0.20    # proxy diretto del hedging istituzionale
cot_report:          0.15    # positioning futures (smart money)
insider_trading:     0.08    # segnale debole ma indipendente
short_interest:      0.07    # proxy conviction dei ribassisti
news_sentiment:      0.05    # molto volatile, peso basso
```

**Regola:** Mai hardcodare i pesi nel codice. Sempre da `OP_CONFIG.sentiment.*` o YAML.

---

## Contrarian Signals

Quando il sentiment raggiunge estremi storici, vengono generati segnali contrarian:

```python
# In composite_score.py
def compute_contrarian_signal(composite: float) -> str | None:
    """
    Estremo pessimismo (score < 20) → segnale contrarian BUY
    Estremo ottimismo (score > 80) → segnale contrarian SELL
    """
    if composite < 20:
        return "BUY"      # il mercato è troppo pessimista → possibile rimbalzo
    elif composite > 80:
        return "SELL"     # il mercato è troppo ottimista → possibile correzione
    return None
```

I contrarian signals vengono mostrati in E7 (Sentiment page) e alimentano il Composite Signal (K1).

---

## Integrazione con il Composite Signal (K1)

Il `SentimentScore.composite` viene normalizzato in [-1, +1] e passato come componente del `CompositeSignalEngine`:

```python
# In alpha_generation/composite_signal.py
sentiment = SentimentAggregator().compute()
sentiment_component = (sentiment.composite - 50) / 50.0    # normalizza [0,100] → [-1,+1]
# sentiment_component > 0 → segnale bullish
# sentiment_component < 0 → segnale bearish
```

---

## Rate limits e scheduling

| Fonte | Rate limit | Frequenza aggiornamento |
|---|---|---|
| CNN Fear & Greed | Nessuno (scraping) | 1/giorno (ore 18:00 EST) |
| Crypto Fear & Greed | 1/min (gratuita) | 1/giorno |
| AAII | Nessuno (settimanale) | 1/settimana (giovedì) |
| Put/Call Ratio | yfinance (60 req/min) | 1/giorno (market close) |
| COT Report | CFTC API | 1/settimana (venerdì) |
| Insider Trading | Finnhub 60 req/min | Variabile |
| Short Interest | Finnhub 60 req/min | 2/mese |
| News Sentiment | Finnhub WebSocket | Tempo reale |

---

## Persistenza

```sql
-- DuckDB: tabella sentiment time series
CREATE TABLE sentiment_scores (
    timestamp    TIMESTAMPTZ PRIMARY KEY,
    composite    DOUBLE NOT NULL,
    cnn_fg       DOUBLE,
    crypto_fg    DOUBLE,
    aaii_bearish DOUBLE,
    put_call     DOUBLE,
    cot_net      DOUBLE,
    insider_ratio DOUBLE,
    short_pct    DOUBLE,
    news_vader   DOUBLE,
    contrarian   VARCHAR    -- "BUY" | "SELL" | NULL
);
-- Retention: 3 anni (Regola 31)
```

---

## Dashboard associata

- **E7 Sentiment** — radar chart 8 fonti, contrarian signals, storico vs prezzi
- **Q5 Sentiment Engine** — aggregazione dettagliata, pesi configurabili
- **K1 Composite Signal** — componente sentiment nel segnale composito

---

## Test

```
tests/engine/analytics/test_sentiment_aggregator.py
  - test_aggregator_minimum_3_sources: fallisce se < 3 fonti attive
  - test_contrarian_buy_below_20: score 15 → contrarian "BUY"
  - test_contrarian_sell_above_80: score 85 → contrarian "SELL"
  - test_weights_sum_to_one: somma pesi = 1.0
  - test_composite_range: score sempre in [0, 100]
```

---

## Anti-pattern da evitare

```
❌ Sentiment calcolato con meno di 3 fonti attive
   → Lanciare InsufficientSourcesError se fonti attive < 3

❌ Fonti non indipendenti conteggiate come separate
   → CNN F&G e Crypto F&G sono correlate ma rimangono separate per peso ridotto

❌ Pesi hardcoded nel codice
   → Sempre da OP_CONFIG / YAML

❌ Contrarian signal su range stretti (es. < 40 o > 60)
   → Solo estremi reali: < 20 o > 80
```

---

## Collegamenti

- [[Market Analysis Engine]] — contesto architetturale
- [[Correlation Engine]] — correlazione sentiment e prezzi
- [[Market Regime]] — sentiment influenza il regime detection
- [[Data Flow]] — come il sentiment entra nel composite signal
