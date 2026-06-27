# MarketAI Vault v2.1 — Knowledge Base

Vault Obsidian per lo sviluppo di **MarketAI Professional** con Claude Code Pro (Opus 4.8).
**Versione vault:** 2.1 (post-analisi gap, Giugno 2026)
**Versione progetto:** v11.0.0-pre → v15.0.0 (roadmap attiva)

---

## Struttura

```
MarketAI Vault/
├── CLAUDE.md                          ← copiare nella root del progetto
├── .claude/                           ← file di riferimento per Claude Code
│   ├── 01_environment.md              ← ambiente, Python 3.12, installer
│   ├── 02_architecture.md             ← layer, directory, pattern
│   ├── 03_conventions.md              ← 32 regole + anti-pattern
│   ├── 04_session_guide.md            ← template prompt Opus, DoD
│   ├── 05_dependencies.md             ← dipendenze pinnate
│   ├── 06_pages_map.md                ← mappa 40+ pagine dashboard
│   ├── 07_data_pipeline.md            ← pipeline dati, DuckDB, migrations
│   └── 08_bugfix_protocol.md          ★ NUOVO v2.1: protocollo bugfix
├── Architecture/
│   ├── Architecture Overview.md
│   ├── Data Flow.md
│   ├── Engine Overview.md
│   ├── Market Analysis Engine.md      ★ NUOVO v2.1
│   ├── Personal Overview.md
│   ├── Shared Overview.md
│   └── Bridge Overview.md
├── Modules/                           ← documentazione moduli singoli
│   ├── [moduli v1: Ensemble, Feature Builder, N-Beats, ecc.]
│   ├── BaseModel Interface.md         ★ NUOVO v2.1
│   ├── Forecasting Engine Map.md      ★ NUOVO v2.1
│   ├── Model Registry.md              ★ COMPLETATO v2.1 (era vuoto)
│   ├── Advanced Metrics.md            ★ NUOVO v2.1
│   ├── Sentiment Engine.md            ★ NUOVO v2.1
│   ├── Correlation Engine.md          ★ NUOVO v2.1
│   ├── Market Regime.md               ★ NUOVO v2.1
│   ├── Risk Scoring.md                ★ NUOVO v2.1
│   ├── Backtesting Strategies.md      ★ NUOVO v2.1
│   ├── FRED Data Universe.md          ★ NUOVO v2.1
│   ├── Portfolio Optimization.md      ★ NUOVO v2.1
│   └── Custom Indicators DSL.md       ★ NUOVO v2.1
├── Bridge/
│   └── API contracts.md
├── API/
│   └── FastAPI Backend.md
├── index/
│   ├── Home.md                        ★ AGGIORNATO v2.1
│   └── Vibecoding workflow.md         ★ AGGIORNATO v2.1 (Recovery + Vault Update Rules)
├── roadmaps/                          ← roadmap operative
├── Glossary/
│   └── Glossary.md                    ★ AGGIORNATO v2.1 (27 nuovi termini)
├── Configuration/
│   └── Config Files.md
└── scripts/
    └── install_v3.py
```

---

## Utilizzo con Claude Code

1. Copiare `CLAUDE.md` nella root del progetto (`%APPDATA%\MarketAI\`)
2. I file `.claude/` devono essere nella sottocartella `.claude/` del progetto
3. Caricare i file con `@` in Claude Code (es. `@.claude/02_architecture.md`)
4. Per i bugfix: `@.claude/08_bugfix_protocol.md` (nuovo in v2.1)

---

## Changelog Vault

| Versione | Data | Modifiche |
|---|---|---|
| v2.1 | Giugno 2026 | +11 nuovi moduli, 08_bugfix_protocol, Vibecoding aggiornato, Glossario +27 termini |
| v2.0 | Maggio 2026 | Audit completo e ricostruzione del vault da v1 |
| v1.0 | Aprile 2026 | Vault iniziale |
