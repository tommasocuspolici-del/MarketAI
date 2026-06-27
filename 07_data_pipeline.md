# 05 — Dipendenze Pinnate e Stack Completo

## ⚠️ DIPENDENZE PINNATE — NON MODIFICARE MAI

Queste versioni sono state testate insieme. Qualsiasi modifica può causare crash silenziosi.

| Pacchetto | Versione | Motivo del pin |
|---|---|---|
| `yfinance` | `==0.2.54` | 0.2.55+ importa `websockets.asyncio.client` → crash all'avvio |
| `websockets` | `>=12.0,<13.0` | 13.x incompatibile con yfinance 0.2.54 |
| `pandera` | `>=0.18,<1.0` | Namespace split in 1.x; `shared/db/schemas.py` ha fallback |

**Come verificare le versioni attive:**
```bash
poetry show yfinance websockets pandera
```

**Se una versione risulta sbagliata dopo `poetry update` accidentale:**
```bash
poetry add yfinance==0.2.54
poetry add "websockets>=12.0,<13.0"
poetry add "pandera>=0.18,<1.0"
```

---

## Stack Completo v11.0.0

### Runtime e Tooling
| Pacchetto | Versione | Uso |
|---|---|---|
| Python | 3.12.x (via Poetry) | Runtime — MAI 3.14.x |
| Poetry | ^2.4 | Package manager |
| Ruff | ^0.4 | Linter/formatter |
| mypy (strict) | ^1.10 | Type checker |
| pytest + hypothesis + freezegun | ^8.1 | Test |
| bandit + safety | latest | Security scan |

### Database e Persistenza
| Pacchetto | Versione | Uso |
|---|---|---|
| DuckDB | ^0.10 | OLAP — dati storici massicci |
| SQLite + SQLAlchemy + Alembic | ^2.0 | OLTP — dati transazionali |
| diskcache | ^5.6 | Cache L1 TTL |
| pandera | >=0.18,<1.0 | Validazione DataFrame (PINNATO) |

### Data Sources
| Pacchetto | Versione | Uso |
|---|---|---|
| yfinance | ==0.2.54 | Prezzi (PINNATO) |
| websockets | >=12.0,<13.0 | WebSocket real-time (PINNATO) |
| pandas-datareader | ^0.10 | FRED (macro bulk) |
| sec-edgar-downloader | ^0.4 | Fondamentali USA |
| finnhub-python | ^1.4 | Prezzi real-time + news |
| alpha-vantage | ^2.3 | Prezzi alternativi |
| aiohttp + httpx | ^3.9 | HTTP async |

### Analisi e ML
| Pacchetto | Versione | Uso |
|---|---|---|
| numpy + scipy | ^1.26 | Calcolo numerico |
| statsmodels + arch | ^0.14 | Modelli statistici, GARCH |
| hmmlearn | ^0.3 | Regime detection (HMM) |
| pmdarima | ^2.0 | ARIMA automatico |
| scikit-learn + xgboost + shap | ^1.4 | ML classico |
| PyTorch + Lightning | ^2.2 | DL — CPU ONLY (ROCm instabile) |
| prophet | ^1.1 | Forecasting stagionale |
| VectorBT | ^0.26 | Backtesting vettorizzato |
| scipy.optimize + cvxpy | ^1.5 | Ottimizzazione portfolio |
| networkx | ^3.3 | Grafi correlazione |
| numba | ^0.59 | JIT acceleration |
| ta-lib + ta | ^0.4 | Indicatori tecnici |
| vaderSentiment | ^3.3 | NLP sentiment |

### UI e Presentazione
| Pacchetto | Versione | Uso |
|---|---|---|
| streamlit | latest pinned | Dashboard principale |
| plotly | ^5.20 | Grafici interattivi |
| pystray | ^0.19 | System tray (Management UI) |
| Pillow | ^10.0 | Icone PIL (Management UI) |
| pywebview | ^5.1 | UI nativa Windows (v15) |
| WeasyPrint + Jinja2 | ^62.0 | Report PDF |

### Infrastruttura
| Pacchetto | Versione | Uso |
|---|---|---|
| structlog | ^24.1 | Logging strutturato |
| pydantic v2 + python-dotenv | ^2.7 | Config e validazione |
| PyYAML | ^6.0 | Feature flags, config YAML |
| apscheduler | ^3.10 | Scheduler job |
| plyer | ^2.1 | Notifiche desktop |
| fastapi | ^0.111 | REST API (v14) |
| uvicorn | ^0.30 | ASGI server |
| psutil | ^5.9 | RAM check per N-BEATS |
| typer + rich | ^0.12 | CLI tools |
| ollama | latest | LLM narrativa (CPU/GPU, feature flag) |

---

## Cosa Aggiungere e Quando

Le seguenti dipendenze vengono aggiunte nelle sessioni specifiche pianificate:

| Sessione | Pacchetto da aggiungere | Note |
|---|---|---|
| v11 S4 | `pystray ^0.19`, `Pillow ^10.0` | Management UI — system tray |
| v12 S4 | `mkdocs-material ^9.5` | Documentazione |
| v14 S5 | `fastapi ^0.111`, `uvicorn[standard] ^0.30`, `httpx ^0.27` | FastAPI backend |
| v14 S1 | `psutil ^5.9` | RAM check N-BEATS |
| v15 S1 | `pywebview ^5.1` | UI nativa Windows |

**Regola:** Modificare pyproject.toml SOLO nelle sessioni pianificate nella roadmap. Mai aggiornare dipendenze casual.

---

## Dipendenze di Sviluppo (solo dev)

```toml
[tool.poetry.group.dev.dependencies]
pytest = "^8.1"
pytest-cov = "^5.0"
pytest-benchmark = "^4.0"
hypothesis = "^6.0"
freezegun = "^1.4"
mypy = "^1.10"
ruff = "^0.4"
bandit = "^1.7"
safety = "^3.0"
pyinstaller = "^6.0"   # solo per build exe (v11 S7, v15 S6)
```
