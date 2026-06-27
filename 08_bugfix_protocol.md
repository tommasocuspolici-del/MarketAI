# 06 — Mappa Completa Pagine Dashboard

## Dashboard Engine (`presentation/dashboard_engine/pages/`)

### Prefisso E — Market Data Classiche (E0–E14)
| Pagina | Titolo | Contenuto Principale |
|---|---|---|
| E0 | API Health | Status provider, latenza, errori per fonte |
| E1 | Market Overview | KPI S&P500/NASDAQ/BTC/EUR-USD/Gold/Oil/VIX + regime badge |
| E2 | Equities | Screener multi-criterio, candlestick pro, fondamentali, SEC EDGAR |
| E3 | Bonds | Yield curve 2Y/5Y/10Y/30Y, spread HY vs IG, inversione curva |
| E4 | Commodities | WTI/Brent/Gold/Silver/Gas/Copper, BDI, commodity/equity ratio |
| E5 | Forex & Options | Heatmap FX majors, Put/Call ratio, VIX term structure |
| E6 | Macro | FRED dashboard 600+ serie, semaforo verde/giallo/rosso |
| E7 | Sentiment | Radar chart 8 fonti, contrarian signals, storico vs prezzi |
| E8 | Correlations | Network graph, heatmap rolling 30/90/252gg, regime-conditional |
| E9 | Forecasting | ARIMA/Prophet, 3 scenari, SHAP feature importance, MAPE OOS |
| E10 | Delta Tracker | Variazioni settimanali/mensili/YTD, alert anomalie |
| E11 | Analysis Pipeline | Pipeline stepper, trigger manuale refresh, log operazioni |
| E12 | Backtesting | Strategy builder, equity curve, walk-forward, vs Buy&Hold |
| E13 | Stress Test | Scenari storici + sintetici, probabilità, slider what-if |
| E14 | Alerts | Alert attivi, configurazione soglie, storico |

### Prefisso K — Composite Signal
| Pagina | Titolo | Contenuto |
|---|---|---|
| K1 | Composite Signal | Alpha aggregator: segnali macro + tecnico + fondamentale + sentiment |

### Prefisso M — Macro Signals (M1–M7)
| Pagina | Titolo | Contenuto |
|---|---|---|
| M1 | VIX Dashboard | VIX term structure, fear gauge, regime implied vol |
| M2 | Yield Curve | Spread 2Y-10Y, inversione, probabilità recessione |
| M3 | Labour Market | Claims, JOLTS, Payroll — Trigger: `📥 Carica da FRED` |
| M4 | Economic Surprise | Indice sorpresa economica, country heatmap |
| M5 | Economic Surprise Setup | Caricamento consensus — Trigger: `📥 Carica consensus` |
| M6 | Valuation PE | Shiller CAPE, P/E ratio storico, mean reversion |
| M7 | IB Consensus | Stime consensus istituzioni, revision trend |

### Prefisso N — News (N1–N2)
| Pagina | Titolo | Contenuto |
|---|---|---|
| N1 | News Feed | Feed notizie real-time da Finnhub + filtri |
| N2 | News Analysis | Sentiment notizie, entity extraction, topic clustering |

### Prefisso Q — Quantitative (Q1–Q14)
| Pagina | Titolo | Contenuto |
|---|---|---|
| Q1 | Backtesting | Engine backtest completo, fan chart probabilistico |
| Q2 | Stress Test | Scenari storici + sintetici forward-looking |
| Q3 | Correlations | DCC-GARCH, network, lead-lag analysis |
| Q4 | Optimizer | Ottimizzazione portfolio (Sharpe/CVaR), frontiera efficiente |
| Q5 | Sentiment Engine | Aggregazione 8 fonti, contrarian signals |
| Q9 | Labour Forecasting | ARIMA+Ridge su UNRATE/ICSA/JOLTS — Trigger: `🤖 Genera previsioni` |
| Q10 | Surprise Heatmap | Heatmap sorpresa economica per paese/indicatore |
| Q11 | Options | Put/Call ratio, skew, superficie volatilità |
| Q12 | MultiTimeframe | Analisi tecnica multi-timeframe (1h/1d/1w/1M) |
| Q14 | Strategy Lab | Prototipazione strategie custom con backtesting rapido |

### Prefisso S — System (S0, S2)
| Pagina | Titolo | Contenuto |
|---|---|---|
| S0 | System Health | HealthChecker: DuckDB, SQLite, cache, scheduler |
| S2 | Settings | Config operativa, gestione sessioni, salute modelli (v15) |

### Prefisso A — Assorted
| Pagina | Titolo | Contenuto |
|---|---|---|
| A1 | Market QA | Quality assurance dati, DataQualityReport, anomalie |

### Prefisso C — Custom Indicators
| Pagina | Titolo | Contenuto |
|---|---|---|
| C1 | Custom Indicators | DSL per indicatori personalizzati, backtesting rapido |

### Prefisso H — History (v15)
| Pagina | Titolo | Contenuto |
|---|---|---|
| H1 | Cronologia Analisi | Storico sessioni con export/import JSON (v15) |

---

## Dashboard Personal (`presentation/dashboard_personal/pages/`)

### Prefisso P — Personal Finance (P1–P9)
| Pagina | Titolo | Contenuto |
|---|---|---|
| P1 | Overview Patrimonio | KPI: patrimonio totale, rendimento YTD, tasso risparmio |
| P2 | Portafoglio eToro | Upload XLSX → TWR/MWR/Alpha, allocazione, VaR/CVaR |
| P3 | Cash Flow | Waterfall entrate/uscite, trend 12 mesi, proiezione 6 mesi |
| P4 | Net Worth | Timeline patrimonio netto, assets vs liabilities |
| P5 | Goals | Obiettivi SMART, progress bar, feasibility checker |
| P6 | Profilo Investitore | Visualizzazione e aggiornamento profilo InvestorProfile |
| P7 | Scenari Ricchezza | Monte Carlo 10k sim fan chart, FIRE calculator |
| P8 | Fiscale | Plus/minusvalenze IT 26%, stima imposta, tax-loss harvesting |
| P9 | Alerts Personali | Alert obiettivi, ribilanciamento, soglie patrimonio |

---

## Note Tecniche per le Pagine

### Pattern Obbligatorio (ogni pagina)
```python
from presentation.ui.auth import require_auth
from presentation.ui.session_keys import SK
from presentation.ui.cache_policy import CACHE_TTL
import streamlit as st

require_auth()   # SEMPRE prima riga

# TTL cache corretti per tipo di dato:
# CACHE_TTL.MARKET_KPI      = 900s   (prezzi live)
# CACHE_TTL.MACRO_CONVICTION = 3600s  (macro, fondamentali)
# CACHE_TTL.PORTFOLIO_TOTALS = 300s   (portfolio utente)

# Refresh manuale in alto a destra:
cols = st.columns([4, 1])
with cols[1]:
    if st.button("🔄 Aggiorna", key=f"{PAGE_ID}_refresh"):
        st.cache_data.clear()
        st.rerun()
```

### Stato Attuale Pagine
- **Attive e funzionanti:** E1, E6, K1, M3, P2 (verificate con dati reali)
- **Con banner DEMO:** E7 (sentiment), E8 (correlazioni) — dati simulati
- **In sviluppo:** Q* pages avanzate, H1
- **Bug noti:** E6 usa "A191RL1Q225SBEA" (non "GDP"), P2 usa InstrumentRegistry per #XXXX

### Health Status Bar (ogni pagina)
```python
# In sidebar di ogni pagina:
from shared.health import HealthChecker
health = HealthChecker(...).check_all()
if health.status.value == "operational":
    st.sidebar.success("🟢 Sistema Operativo")
elif health.status.value == "degraded":
    st.sidebar.warning("🟡 Sistema Degradato")
else:
    st.sidebar.error("🔴 Sistema Non Operativo")
```
