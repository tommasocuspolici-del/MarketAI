Il Data Provider System è il componente responsabile dell'acquisizione di dati finanziari da fonti esterne (API, file, database) e del loro pre-processing per il motore di previsione. Segue un'architettura a plugin che garantisce flessibilità e resilienza.

## Architettura
Il sistema è composto da:
- **Provider Registry**: Mappa dei provider disponibili con i loro endpoint e parametri (definiti in `Configuration/data_sources.yaml`).
- **Provider Base Class**: Classe astratta che definisce l'interfaccia comune (`fetch_data(symbol, start_date, end_date)`).
- **Provider Concreti**: Implementazioni per Finnhub, Alpha Vantage, Yahoo Finance, CryptoCompare, etc.
- **Fallback Manager**: Gestisce la logica di fallback in caso di errore o rate limit di un provider.
- **Cache Layer**: Memorizza i dati recenti in Redis per ridurre le chiamate API e velocizzare l'accesso.

## Flusso di Richiesta Dati
1. Il modulo richiedente (es. Ensemble Predictor) chiama `DataProvider.get_data(symbol, ...)`.
2. Il sistema controlla la cache: se i dati sono disponibili e freschi (TTL configurabile), li restituisce.
3. Altrimenti, interroga il provider primario (es. Finnhub) tramite il suo client.
4. Se la risposta ha successo, i dati vengono salvati in cache e restituiti.
5. In caso di errore (timeout, quota esaurita), il Fallback Manager attiva il provider secondario (es. Alpha Vantage) e registra l'evento nei log.
6. Se tutti i provider falliscono, viene sollevata un'eccezione e il sistema notifica l'amministratore.

## Configurazione
Il file `data_sources.yaml` contiene per ogni provider:
yaml
- name: finnhub
  enabled: true
  priority: 1
  api_key: ${FINNHUB_API_KEY}
  base_url: https://finnhub.io/api/v1
  rate_limit: 60  # chiamate al minuto
  cache_ttl: 300  # secondi
  timeout: 10



Data provider plugin systems 

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


- [[2 - consolidamento]]
- [[Architecture Overview]]
- [[Probabilistic Prediction]]
