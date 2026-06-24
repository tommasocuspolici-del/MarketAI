# MarketAI Vault – Benvenuto

Questo vault Obsidian contiene la documentazione operativa per lo sviluppo di **MarketAI** (v11→v15). È ottimizzato per il **vibecoding** con Claude Code Pro: ogni sessione ha un prompt di apertura, una checklist e link ai moduli coinvolti.

## Mappa delle Fasi

[[1 - roadmap preliminare]] – Installer, Management UI, CLAUDE.md v2
[[2 - consolidamento]]– Data Provider Plugin, Logging JSON, CI/CD, MkDocs
[[3 - fase modellistica]]– Ensemble, Quantile Forecasting, Feature Engineering
[[4 - fase avanzata]]– N‑BEATS, Backtesting con costi, FastAPI, Metriche avanzate
[[5 - refactoring UI]]– pywebview, Persistenza sessioni, Drift detection, Build EXE

## Workflow Vibecoding

1. Apri la sessione corrente dalla cartella `03 - Sessions/`.
2. Leggi l'**obiettivo** e i **file da creare**.
3. Copia il **Prompt di apertura** per Claude.
4. Esegui `poetry run pytest -m regression -q` per assicurarti che non ci siano regressioni.
5. Segui i task, spuntando la **Definition of Done**.
6. Al termine, aggiorna il file della sessione con note o eventuali deviazioni.

## Collegamenti rapidi

- [[Architecture Overview]]
- [[Data Provider System]]
- [[Ensemble Predictor]]
- [[N-BEATS]]
- [[Realistic Backtester]]
- [[FastAPI Backend]]
- [[pywebview Shell]]
- [[Glossary]]