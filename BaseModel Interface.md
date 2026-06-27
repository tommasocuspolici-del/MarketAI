
---

#### `02 - Engine Layer/Engine Overview.md`
```markdown
# Engine Layer - Panoramica

Il motore di analisi quantitativa di MarketAI. Contiene tutti i moduli per l'acquisizione, l'elaborazione e l'analisi dei dati di mercato.

## Moduli

- [[Analytics]]: Calcolo di indicatori tecnici, fondamentali e sentiment.
- [[Backtesting]]: Simulazione di strategie di trading.
- [[Data Universe]]: Gestione delle fonti dati (Yahoo, FRED, SEC, ecc.).
- [[Forecasting]]: Proiezioni a 3 scenari.
- [[Alpha Generation]]: Generazione di segnali alpha.
- [[Fixed Income]]: Analisi di titoli a reddito fisso.
- [[Futures Analysis]]: Analisi dei futures.
- [[IB Forecast]]: Forecast basati su Institutional Brokerage.

## Dipendenze
- `shared/db`: Accesso al database DuckDB/SQLite[reference:27]
- `shared/config`: Configurazioni di sistema[reference:28]
- `bridge`: Espone i dati al Personal Layer tramite API contracts[reference:29]

## Statistiche
- **Copertura test**: ≥ 94% per analytics[reference:30]
- **Latenza pipeline**: 45ms su 5 ticker[reference:31]

## Collegamenti
- [[Architecture Overview]]
- [[Shared Overview]]
- [[Bridge Overview]]