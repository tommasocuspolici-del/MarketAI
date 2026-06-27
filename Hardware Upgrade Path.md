# Roadmap di Progetto — MarketAI v11→v17

Questa pagina è l'indice di tutte le roadmap operative. Ogni roadmap contiene sessioni dettagliate con prompt di apertura, file da creare, e Definition of Done.

> **Stato attuale:** Pianificazione v11 completata (15/06→17/08/2026).
> Implementazione: 18/08/2026 con Claude Code Pro (Opus 4.8).
> **REGOLA:** Non saltare fasi. Ogni versione è prerequisito della successiva.

---

## Fasi Core (v11→v15) — Base Obbligatoria

### v11.0.0 — Infrastruttura (18/08 → 06/09/2026)
[[1 - roadmap preliminare]]

**Obiettivi obbligatori:**
- `[OB-1]` Installer v3 con GUI tkinter (`scripts/install_v3.py`)
- `[OB-2]` Management UI standalone con system tray (`management_ui.py`)
- `[OB-3]` CLAUDE.md v2 con mappa 40+ pagine e vincoli Python

**Durata:** 8 sessioni da 1–2h · **Hardware:** Attuale

---

### v12.0.0 — Consolidamento (~3 settimane)
[[2 - consolidamento]]

**Obiettivi obbligatori:**
- `[OB-1]` Data Provider Plugin System (ABC + ProviderRegistry + 3 provider)
- `[OB-2]` Logging JSON strutturato (structlog, rotazione 20MB)
- `[OB-3]` GitHub Actions CI/CD + coverage badge
- `[OB-4]` MkDocs Material documentazione

**Durata:** 5 sessioni · **Hardware:** Attuale

---

### v13.0.0 — Modellistica Avanzata (~4 settimane)
[[3 - fase modellistica]]

**Obiettivi obbligatori:**
- `[OB-1]` EnsemblePredictor (average, weighted, stacking)
- `[OB-2]` Quantile Forecasting XGBoost/RF (Q10–Q90)
- `[OB-3]` FeatureBuilder automatizzato (lag, rolling, Fourier)

**Durata:** 6 sessioni · **Hardware:** Attuale

---

### v14.0.0 — Modelli Avanzati e FastAPI (~5 settimane)
[[4 - fase avanzata]]

**Obiettivi obbligatori:**
- `[OB-1]` N-BEATS PyTorch CPU-only (ROCm instabile su RX 6700)
- `[OB-2]` RealisticBacktester con commissioni/slippage (fee ≥ 0.001)
- `[OB-3]` Metriche avanzate (SMAPE, Theil's U2, Pinball, CRPS)
- `[OB-4]` FastAPI: `/predict`, `/backtest`, `/models`, `/health`

**Durata:** 7 sessioni · **Hardware:** Attuale

---

### v15.0.0 — UI Nativa e Produzione (~5 settimane)
[[5 - refactoring UI]]

**Obiettivi obbligatori:**
- `[OB-1]` Shell pywebview (finestra nativa, zero browser visibile)
- `[OB-2]` Persistenza sessioni (`db/user_sessions.db` separato)
- `[OB-3]` Model drift detection (WARNING +20% MAE, CRITICAL +50%)

**Durata:** 7 sessioni · **Hardware:** Attuale

---

## ⚠️ UPGRADE HARDWARE CONSIGLIATO — Post v15

> Prima di iniziare v16-v17: **RAM 16GB → 32GB (~80 EUR)**
> Vedi [[Hardware Upgrade Path]] per dettagli completi.

---

## Fasi Espansione (v16→v17) — Terminale Istituzionale

### v16.0.0 — Feature Differenzianti (~10 settimane, feb–apr 2027)
[[6 - visione 2027]]

**Obiettivi obbligatori:**
- `[OB-1]` Telegram Bot Integration (notifiche push smartphone)
- `[OB-2]` Options Chain Analytics (Put/Call ratio, Greeks, Max Pain)
- `[OB-3]` Alternative Data Sources (Google Trends, Reddit, Wikipedia)
- `[OB-4]` Multi-Broker Import (Degiro, Fineco, Trading212)
- `[OB-5]` PDF Report Automatico Settimanale (WeasyPrint + Telegram)

**Opzionali:**
- `[OPT-1]` COT Report CFTC (Commitment of Traders)
- `[OPT-2]` Factor Analysis Fama-French 5 Fattori

**Durata:** 6 sessioni · **Hardware:** 32GB RAM

---

### v17.0.0 — Terminale Istituzionale (~15 settimane, mag–dic 2027)
[[6 - visione 2027]]

**Obiettivi obbligatori:**
- `[OB-1]` LLM Locale Ollama + RAG su bilanci/earnings call
- `[OB-2]` Portfolio Optimizer (Black-Litterman, HRP, Min-CVaR)
- `[OB-3]` Risk Management Istituzionale (Kelly, Factor, LVaR)
- `[OB-4]` Regime-Conditional Allocation (HMM → cvxpy)
- `[OB-5]` Event Study Engine (Abnormal Returns, CAR)

**Opzionali:**
- `[OPT-1]` Chronos Foundation Model (zero-shot, post GPU upgrade)
- `[OPT-2]` Geopolitical Risk Index (GDELT + GPR Fed)
- `[OPT-3]` Tax-Loss Harvesting Automatico IT

**Durata:** 6 sessioni · **Hardware:** 32GB RAM (+ RTX 4060 consigliato)

---

## Timeline Riepilogativa Completa

```
18/08–06/09/2026   v11   Infrastruttura (8 sessioni)
Settembre 2026     v12   Consolidamento (5 sessioni)
Ottobre 2026       v13   Modellistica (6 sessioni)
Novembre 2026      v14   Avanzata (7 sessioni)
Dic 2026–Gen 2027  v15   UI Nativa (7 sessioni)

── UPGRADE RAM 32GB (~80 EUR) ──

Feb–Apr 2027       v16   Feature Differenzianti (6 sessioni)
Mag–Dic 2027       v17   Terminale Istituzionale (6 sessioni)

TOTALE: ~45 sessioni · ~24 mesi
MVP completo: Gennaio 2027 (fine v15)
Terminale istituzionale: Fine 2027 (fine v17)
```

## Pietre Miliari (GO/NO-GO)

| Milestone | Criterio GO | Hardware |
|-----------|-------------|----------|
| Fine v11 | Installer funzionante, Management UI, 0 regressioni | Attuale |
| Fine v12 | ProviderRegistry fallback chain funzionante, CI verde | Attuale |
| Fine v13 | Ensemble + fan chart funzionanti, coverage ≥ 89% | Attuale |
| Fine v14 | N-BEATS su CPU < 3min, FastAPI /predict 200 OK | Attuale |
| Fine v15 | pywebview funzionante su Windows 11, MarketAI.exe < 80MB | Attuale |
| **Upgrade RAM** | **32GB verificati, `psutil.virtual_memory().total ≥ 30GB`** | ⚠️ ~80 EUR |
| Fine v16 | Telegram alert su smartphone, Options chain, Alt data | 32GB RAM |
| Fine v17 | LLM risponde a domande bilancio, BL optimizer valido | 32GB RAM |
