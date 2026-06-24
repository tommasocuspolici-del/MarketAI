# Data Provider Plugin System

**Introdotto in:** v12 – Consolidamento  
**File principali:** `engine/market_data/providers/`

## Panoramica

Il sistema fornisce un'interfaccia unificata per accedere a diverse fonti di dati finanziari. I provider sono registrati in un `ProviderRegistry` che gestisce priorità e fallback automatico.

## Componenti

- **`DataProvider`** (ABC) – interfaccia comune con `get_history()` e `get_info()`.
- **`ProviderRegistry`** (singleton) – ordina i provider per priorità e tenta il primo che risponde.
- **Provider concreti**:
  - `YFinanceProvider` – primario (priorità 1)
  - `AlphaVantageProvider` – fallback (priorità 2), usa `RateLimitManager`
  - `FinnhubProvider` – terziario (priorità 3), disabilitato se manca API key

## Regole di progettazione

- Ogni provider deve normalizzare i dati in un DataFrame con colonne `Open, High, Low, Close, Volume` e indice `DatetimeIndex` UTC‑aware.
- I provider **non** devono essere chiamati direttamente dalle UI: usare sempre `ProviderRegistry.get_history()`.
- Il fallback è automatico: se un provider fallisce, il registry passa al successivo in ordine di priorità.

## Come aggiungere un nuovo provider

1. Crea `engine/market_data/providers/mio_provider.py`.
2. Eredita da `DataProvider` e implementa i metodi.
3. Imposta `_priority` (più basso = priorità maggiore).
4. Registra il provider all'avvio (es. in `scripts/init_providers.py`).

## Test

- Tutti i test devono usare **mock** (nessuna chiamata API reale).
- `tests/engine/providers/` contiene test per ogni provider e per il registry.
- La fallback chain è testata in `test_fallback_chain.py`.

## Collegamenti

- [[2 - consolidamento]]
- [[Architecture Overview]]
- [[ProbabilisticPrediction]]