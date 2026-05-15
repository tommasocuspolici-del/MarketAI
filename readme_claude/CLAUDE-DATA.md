# CLAUDE TEMA — Gestione Dati e Persistenza

## Dual database
- **DuckDB (OLAP)** → prezzi, macro, fondamentali, sentiment, backtest, stress test, segnali.
- **SQLite (OLTP)** → posizioni personali, profili, obiettivi, alert, cash flow.

## Pipeline invariabile

- Mai scrivere in DB senza clean+validate.
- Cache L1: `diskcache` con TTL configurabile (default 300s).

## DataCleaner e QualityReport
- `DataCleaner`: gap filling (lineare per prezzi, forward fill per volumi), outlier detection (z‑score > 5), stale data detection.
- `DataQualityReport`: score [0,1] allegato a OGNI serie.
- Se `quality_score < 0.5` → warning e dato ESCLUSO da calcoli critici.

## DuckDB Migrations
- Ogni modifica schema → script in `shared/db/migrations/duckdb/YYYYMMDD_NNN_desc.sql`.
- `DuckDBMigrator.apply_pending()` all’avvio.
- Mai modificare schema manualmente.

## Validazione Pandera
```python
class PricesSchema(pa.DataFrameModel):
    ticker: Series[str]
    date: Series[pd.Timestamp]
    open: Series[float] = pa.Field(ge=0)
    high: Series[float] = pa.Field(ge=0)
    low: Series[float] = pa.Field(ge=0)
    close: Series[float] = pa.Field(ge=0)
    volume: Series[float] = pa.Field(ge=0)
    class Config:
        strict = True
        coerce = True