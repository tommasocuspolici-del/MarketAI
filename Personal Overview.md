# Architettura di MarketAI

MarketAI è strutturato in tre layer principali, collegati da un **Bridge** che espone contratti API chiari [[Bridge Overview]].

```mermaid
graph TB
    subgraph Engine[Engine Layer]
        ED[Market Data]
        EA[Analytics]
        EB[Backtesting]
        ES[Stress Test]
    end
    subgraph Personal[Personal Layer]
        PP[Portfolio]
        PG[Goals]
        PT[Tax]
        PN[Net Worth]
    end
    Engine -->|bridge/api_contracts.py| Bridge[Bridge]
    Personal -->|bridge/api_contracts.py| Bridge
    subgraph Shared[Shared Layer]
        DD[DuckDB]
        SD[SQLite]
        SC[Cache]
    end
    Bridge --> Shared