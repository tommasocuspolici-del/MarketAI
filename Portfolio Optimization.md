# Custom Indicators DSL

**File sorgente:** `custom_indicators/`
**Introdotto in:** v10
**Scopo:** Permettere all'utente di definire indicatori tecnici personalizzati via interfaccia

---

## Panoramica

Il modulo `custom_indicators/` offre un mini-DSL (Domain Specific Language) per creare indicatori tecnici personalizzati senza scrivere codice Python direttamente. Gli indicatori vengono definiti tramite la pagina C1 della dashboard e vengono persistiti in SQLite.

---

## Struttura modulo

```
custom_indicators/
├── __init__.py
├── dsl_parser.py          ← Parser del DSL → AST interno
├── dsl_evaluator.py       ← Valutazione dell'AST su pd.Series
├── indicator_registry.py  ← Registry degli indicatori definiti dall'utente
├── indicator_model.py     ← CustomIndicator dataclass (nome, formula, params)
└── builtin_functions.py   ← Funzioni disponibili nel DSL (SMA, EMA, RSI, ecc.)
```

---

## Sintassi DSL

Il DSL è un linguaggio semplice che opera su serie temporali:

```
# Sintassi base
INDICATOR <nome> = <espressione>

# Variabili built-in disponibili
close       ← prezzi di chiusura
open        ← prezzi di apertura
high        ← massimi
low         ← minimi
volume      ← volumi

# Funzioni disponibili
SMA(serie, periodo)         ← Simple Moving Average
EMA(serie, periodo)         ← Exponential Moving Average
RSI(serie, periodo=14)      ← Relative Strength Index
MACD(serie, fast, slow, signal) ← MACD line
BOLLINGER(serie, periodo, std_mult) ← (upper, middle, lower)
ATR(high, low, close, periodo)   ← Average True Range
STOCH(high, low, close, k, d)   ← Stochastic Oscillator

# Operatori aritmetici
+  -  *  /  **  abs()  log()  sqrt()

# Operatori di confronto (ritornano bool series)
>  <  >=  <=  ==  !=
```

### Esempi DSL

```
# MACD personalizzato con parametri diversi dagli standard
INDICATOR MACD_custom = EMA(close, 8) - EMA(close, 21)

# Rapporto volume/prezzo normalizzato
INDICATOR volume_price_ratio = (volume / close) / SMA(volume / close, 20)

# Indicatore di forza relativa personalizzato
INDICATOR custom_rsi_10 = RSI(close, 10)

# Segnale combinato
INDICATOR combined_signal = (EMA(close, 10) > EMA(close, 30)) * RSI(close, 14)
```

---

## CustomIndicator dataclass

```python
# custom_indicators/indicator_model.py
@dataclass
class CustomIndicator:
    indicator_id: str        # UUID generato alla creazione
    name: str                # nome human-readable
    formula: str             # testo DSL della formula
    description: str         # descrizione opzionale
    created_at: datetime
    is_active: bool = True
```

---

## Integrazione con il backtesting

Gli indicatori custom possono essere usati come segnali di trading:

```python
from custom_indicators.indicator_registry import IndicatorRegistry

registry = IndicatorRegistry()
indicator = registry.get("MACD_custom")
signal_series = indicator.evaluate(ohlcv_df)   # pd.Series

# Usare come segnale nel backtesting
signal_shifted = np.sign(signal_series).shift(1)   # anti look-ahead bias
```

**Regola:** Anche i segnali da indicatori custom devono essere shiftati di 1 prima del backtest.

---

## Persistenza

```sql
-- SQLite: indicatori custom definiti dall'utente
CREATE TABLE custom_indicators (
    indicator_id  TEXT PRIMARY KEY,
    name          TEXT NOT NULL UNIQUE,
    formula       TEXT NOT NULL,
    description   TEXT,
    created_at    TEXT NOT NULL,
    is_active     INTEGER DEFAULT 1
);
```

---

## Pagina dashboard

- **C1 Custom Indicators** — editor DSL, preview su ticker selezionato, salvataggio
- **Q12 Strategy Lab** — uso degli indicatori custom come componenti di strategie

---

## Anti-pattern

```
❌ Indicatori custom che usano dati futuri nella formula
   → Il DSL non permette accesso a indici futuri — solo passato e presente

❌ Formule DSL salvate senza validazione sintattica
   → dsl_parser.validate(formula) sempre prima del salvataggio

❌ Indicatori custom usati in backtest senza shift(1)
   → .shift(1) obbligatorio come per tutti i segnali

❌ Loop Python nell'evaluator su serie temporali
   → Tutte le operazioni DSL delegate a pandas/numpy vettorizzato
```

---

## Aggiungere una funzione built-in al DSL

```
□ Aggiungere in custom_indicators/builtin_functions.py
□ Funzione signature: def MY_FUNC(series: pd.Series, ...) -> pd.Series
□ Registrare in BUILTIN_FUNCTIONS dict
□ Test: tests/custom_indicators/test_builtin_functions.py
□ Documentare in questa pagina
```

---

## Limitazioni

- Il DSL non supporta: condizionali multi-riga, loop, import di librerie esterne
- Una formula DSL opera su un singolo ticker alla volta
- Funzioni statistiche avanzate (DCC-GARCH, HMM) non sono disponibili nel DSL — usare i moduli engine/ direttamente

---

## Target performance

| Operazione | Target |
|---|---|
| Parsing + valutazione (5 anni daily) | < 500ms |
| Preview real-time in C1 dashboard | < 1s |

---

## Test

```
tests/custom_indicators/
  test_dsl_parser.py       ← parsing formule valide e non valide
  test_dsl_evaluator.py    ← output corretto per funzioni built-in
  test_indicator_registry.py ← CRUD indicatori
  test_backtesting_integration.py ← indicatore custom → segnale → backtest
```

---

## Glossario

| Termine | Definizione |
|---|---|
| **DSL** | Domain Specific Language — linguaggio semplificato per un dominio specifico |
| **AST** | Abstract Syntax Tree — struttura ad albero che rappresenta la formula parsata |
| **Built-in functions** | Funzioni già disponibili nel DSL senza definizione aggiuntiva |
| **Evaluator** | Componente che esegue l'AST su dati reali producendo una pd.Series |

---

## Collegamenti

- [[Backtesting Strategies]] — uso degli indicatori custom come segnali
- [[Market Analysis Engine]] — dove gli indicatori vengono calcolati
- [[Forecasting Engine Map]] — custom indicators come feature per i modelli ML
