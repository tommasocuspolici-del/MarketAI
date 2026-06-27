# MarketAI Vault — Home

Vault Obsidian per lo sviluppo di **MarketAI Professional** (v11→v17).
Workflow: **Claude Code Pro (Opus 4.8)** · Sessioni brevi 1–2h · Gate regressione obbligatorio.

---

## 🤖 Claude Code — Avvio Rapido

**File di contesto:** `CLAUDE.md` (root del progetto, NON nel vault)
**Gate obbligatorio:** `poetry run pytest -m regression -q --tb=short` → 0 failed

Reference files (caricare con `@` in Claude Code quando necessario):
- `@.claude/01_environment.md` — ambiente, Python 3.12, installer
- `@.claude/02_architecture.md` — layer, moduli, pattern
- `@.claude/03_conventions.md` — 32 regole + anti-pattern
- `@.claude/04_session_guide.md` — template prompt Opus, DoD
- `@.claude/05_dependencies.md` — dipendenze pinnate (yfinance, websockets, pandera)
- `@.claude/06_pages_map.md` — mappa 40+ pagine dashboard
- `@.claude/07_data_pipeline.md` — pipeline dati, DuckDB, migrations
- `@.claude/08_bugfix_protocol.md` — protocollo bugfix con routing errori

---

## 🗺️ Mappa delle Fasi

| Fase | Versione | File Roadmap | Hardware |
|---|---|---|---|
| Infrastruttura | v11 | [[1 - roadmap preliminare]] | Attuale |
| Consolidamento | v12 | [[2 - consolidamento]] | Attuale |
| Modellistica Avanzata | v13 | [[3 - fase modellistica]] | Attuale |
| Modelli Avanzati + FastAPI | v14 | [[4 - fase avanzata]] | Attuale |
| UI Nativa + Produzione | v15 | [[5 - refactoring UI]] | Attuale |
| ⚠️ **UPGRADE RAM 32GB** | — | [[Hardware Upgrade Path]] | ~80 EUR |
| Feature Differenzianti | v16 | [[6 - visione 2027]] | 32GB RAM |
| Terminale Istituzionale | v17 | [[6 - visione 2027]] | 32GB RAM |

---

## 🔗 Navigazione Rapida

**Visione e Strategia:**
- [[6 - visione 2027]] — ★ NUOVO: roadmap completa v16-v17 con sessioni dettagliate
- [[Feature Map 2027]] — ★ NUOVO: tabella rapida nuove feature e dipendenze
- [[Hardware Upgrade Path]] — ★ NUOVO: upgrade path RAM e GPU con costi

**Architettura:**
- [[Architecture Overview]] — Struttura layer e diagramma Mermaid
- [[Market Analysis Engine]] — motore di analisi di mercato completo
- [[Data Flow]] — Pipeline dati end-to-end
- [[Engine Overview]] — Moduli engine/
- [[Personal Overview]] — Moduli personal/
- [[Shared Overview]] — DB, cache, logging, resilience
- [[Bridge Overview]] — Contratti API engine ↔ personal

**Motore di Previsione:**
- [[Forecasting Engine Map]] — mappa relazioni tra tutti i moduli forecasting
- [[BaseModel Interface]] — contratto comune tutti i modelli
- [[Model Registry]] — singleton accesso modelli
- [[Ensemble predictor]] — 3 strategie di combinazione
- [[Feature Builder]] — lag, rolling, Fourier, selezione automatica
- [[N-Beats]] — Neural forecasting CPU-only PyTorch
- [[Probabilistic Prediction]] — quantili Q10–Q90, fan chart
- [[Advanced Metrics]] — SMAPE, Theil's U2, CRPS, Pinball, diagnostica

**Motore di Analisi di Mercato:**
- [[Sentiment Engine]] — 8 fonti aggregate, contrarian signals
- [[Correlation Engine]] — DCC-GARCH, HMM, network graph
- [[Market Regime]] — HMM bull/bear/transition/stress
- [[Risk Scoring]] — RiskScore con breakdown obbligatorio
- [[FRED Data Universe]] — 600+ serie macro, ID critici, mapping pagine

**Backtesting e Portfolio:**
- [[Realistic Backtester]] — commissioni, slippage, equity netta
- [[Backtesting Strategies]] — 5 strategie esistenti, pattern aggiunta nuova
- [[Portfolio Optimization]] — frontiera efficiente CVXPY, rebalancing

**Infrastruttura:**
- [[Data Provider System]] — ProviderRegistry, fallback chain
- [[Persistenza sessioni]] — SQLite dedicato, storico analisi
- [[Custom Indicators DSL]] — DSL per indicatori personalizzati
- [[API contracts]] — Bridge contracts engine ↔ personal
- [[FastAPI Backend]] — endpoint /predict /backtest /health
- [[Config Files]] — YAML configuration reference

**Riferimenti:**
- [[Glossary]] — Glossario tecnico
- [[Visioning and Dependencies]] — Versioni e dipendenze
- [[Roadmaps]] — Indice completo tutte le roadmap

---

## ⚡ Workflow Sessione (sintesi)

1. `poetry run pytest -m regression -q` → **0 failed** (STOP se fallisce → `@.claude/08_bugfix_protocol.md`)
2. `poetry env info` → **Python 3.12.x** confermato
3. Aprire roadmap sessione → copiare prompt di apertura
4. Implementare con Claude Code Opus 4.8
5. Gate finale: `pytest -m regression -q` → 0 failed
6. Commit: `feat: descrizione` + `Co-Authored-By: Claude Opus 4.8`
7. Aggiornare vault se introdotti moduli nuovi

---

## 📊 Stato Vault v3.0

| Area | File | Stato |
|---|---|---|
| Pipeline Vault → Claude Code | `.claude/01-08` | ✅ Completo |
| Anti-regression patterns | `03_conventions.md`, `Vibecoding workflow` | ✅ Solido |
| Motore di previsione | `Forecasting Engine Map`, `BaseModel`, `Model Registry` | ✅ Documentato |
| Motore di analisi di mercato | `Market Analysis Engine`, `Sentiment`, `Correlation`, `Regime` | ✅ Documentato |
| Analisi quantitativa | `Advanced Metrics`, `Backtesting Strategies`, `FRED Data Universe` | ✅ Documentato |
| Gestione bugfix | `08_bugfix_protocol.md` | ✅ Documentato |
| **Visione 2027** | `Vision/`, `6 - visione 2027.md` | ★ NUOVO v3.0 |
| **Feature Map** | `Vision/Feature Map 2027.md` | ★ NUOVO v3.0 |
| **Hardware Upgrade** | `Vision/Hardware Upgrade Path.md` | ★ NUOVO v3.0 |
| **Roadmap v16-v17** | `roadmaps/Roadmaps.md` aggiornato | ★ NUOVO v3.0 |
