# Shared Layer – Componenti Trasversali e Infrastruttura

**Introdotto in:** v10 (Architettura base)  
**File principali:** `shared/` (intera cartella)  
**Stato:** Infrastruttura condivisa tra Engine e Personal

## Panoramica

Lo **Shared Layer** fornisce servizi e componenti trasversali utilizzati da tutti gli altri layer (Engine, Personal, Bridge, UI). Non contiene logica di business, ma offre infrastruttura per:

- **Persistenza** (DuckDB + SQLite)
- **Caching** (TTL, fallback chain)
- **Monitoraggio** (health check, metriche)
- **Resilienza** (circuit breaker, graceful degradation)
- **Rate limiting** (per API esterne)
- **Logging** (strutturato JSON)
- **Feature flags** (abilitazione/disabilitazione moduli)

Il Shared Layer è progettato per essere **disaccoppiato** e **testabile** indipendentemente dai moduli che lo utilizzano.

```mermaid
graph TB
    subgraph Shared[Shared Layer]
        DB[Database<br/>DuckDB + SQLite]
        CACHE[Cache<br/>TTL + fallback]
        MON[Monitoring<br/>health check]
        RES[Resilience<br/>circuit breaker]
        RL[Rate Limiting<br/>per provider]
        LOG[Logging<br/>strutturato JSON]
        FF[Feature Flags<br/>abilitazione moduli]
    end
    
    Engine[Engine Layer] --> DB
    Engine --> CACHE
    Engine --> RL
    Personal[Personal Layer] --> DB
    Personal --> CACHE
    UI[UI / FastAPI] --> MON
    UI --> LOG
    Bridge[Bridge] --> FF