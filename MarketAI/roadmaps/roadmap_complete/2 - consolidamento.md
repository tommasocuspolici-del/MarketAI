# 🔵 ROADMAP — MarketAI v12.0.0 · Fase 1: Consolidamento Fondamenta
> **v11.0.0 → v12.0.0** · Testing · Logging · Data Provider Plugin System  
> Prerequisito: v11.0.0 completato (installer + management UI in `%APPDATA%\MarketAI\`)  
> Pianificazione: Claude Sonnet 4.6 · Implementazione: Claude Code Pro (Opus 4.8)  
> Sessioni: 5 sessioni · Durata stimata: 1–2h ciascuna · Totale: ~3 settimane

---

## 📊 Stato Pre-Fase 1

| Parametro | Valore |
|-----------|--------|
| Versione base | v11.0.0 (installer + management UI completi) |
| Python venv | **3.12.10** (Poetry) |
| Posizione progetto | `%APPDATA%\MarketAI\` |
| Test attuali | 3080+ passing · coverage ≥ 89.1% |
| Obiettivo coverage | ≥ 90% su moduli core; 100% su nuovi moduli |
| Sorgenti dati attive | yfinance (primary) · Alpha Vantage (fallback) |

---

## 🎯 Obiettivi v12.0.0

### Obbligatori

```
[OB-1] Data Provider Plugin System
        · Interfaccia astratta DataProvider (ABC)
        · Plugin: YFinanceProvider, AlphaVantageProvider, FinnhubProvider
        · ProviderRegistry con priorità e fallback automatico
        · Caching unificato per tutti i provider

[OB-2] Logging strutturato completo
        · Migrazione da print() residui a structlog
        · Log JSON rotanti (20 MB · 5 backup)
        · Correlazione richieste con request_id
        · Log separato per errori API e DB

[OB-3] Potenziamento test suite
        · Test di integrazione per ogni provider dati
        · Test su dati sintetici per pipeline fetch→clean→validate
        · GitHub Actions CI/CD automatico
        · Coverage badge nel README

[OB-4] Docstring e documentazione MkDocs
        · Docstring Google style su tutti i moduli pubblici
        · Sito MkDocs generabile con `make docs`
        · CONTRIBUTING.md con guide per aggiungere provider/modelli
```

### Facoltativi (solo se OB-1/2/3 completati)

```
[OPT-1] Gestore eventi societari (split, dividendi automatici)
[OPT-2] Badge coverage su README.md
```

---

## ⚠️ Vincoli Tecnici — LEGGERE PRIMA DI OGNI SESSIONE

```
CRITICO: Python venv deve essere 3.12.10 (non 3.14.x di sistema)
         poetry env info → verificare SEMPRE prima di modificare codice

DIPENDENZE PINNATE — NON MODIFICARE:
  yfinance   == 0.2.54   (0.2.55+ crashano con websockets)
  websockets >= 12.0,<13.0
  pandera    >= 0.18,<1.0

NUOVO in v12 — aggiungere a pyproject.toml SOLO nelle sessioni indicate:
  Sessione 1: finnhub-python ^1.4 (già presente? verificare)
  Sessione 4: mkdocs-material ^9.5

LAYER BOUNDARIES — non violare mai:
  engine/  NON importa da personal/
  personal/ NON importa da engine/analytics, risk, alpha_generation
  Nuovo DataProvider system → solo in engine/market_data/providers/
```

---

## 🧩 Anti-Pattern Vietati v12.0.0

```
❌ DataProvider che bypassa il ProviderRegistry
   → Tutti i fetch passano per ProviderRegistry.get()

❌ Fallback scritto con if/else inline nel fetcher
   → ProviderRegistry gestisce fallback automatico

❌ API key hardcoded nel DataProvider
   → Sempre da .env via os.getenv()

❌ Test che chiama API reale senza mock
   → Usare pytest-mock; test integration separati con marker @pytest.mark.integration

❌ Logging con print() in qualsiasi modulo
   → from shared.logger import get_logger sempre

❌ Log che contiene valori di API key o dati personali
   → Loggare solo nomi/tipi, mai valori sensibili

❌ Coverage che scende sotto 89.1%
   → pytest --cov-fail-under=89 nel CI

❌ pyproject.toml modificato fuori da sessioni pianificate
   → Solo nelle sessioni 1 e 4

❌ Sessione Opus senza regression test iniziale
   → Obbligatorio: 0 failed prima di modificare qualsiasi file
```

---

## 📅 SESSIONE 1 — Data Provider: Interfaccia e YFinance (1–2h)

**Obiettivo:** Creare la struttura base del plugin system e migrare yfinance

**NON toccare:** `engine/market_data/fetchers/` esistenti, `pyproject.toml` (tranne aggiunta finnhub)

**Prompt di apertura Opus:**
```
Leggi CLAUDE.md completamente.
Task: Sessione 1 — Data Provider Plugin System (interfaccia + YFinanceProvider)
Inizia con: poetry run pytest -m regression -q --tb=short → deve dare 0 failed
NON modificare fetcher esistenti. Crea solo nuovi file in engine/market_data/providers/
```

**File da creare:**

```
engine/market_data/providers/
  __init__.py
  base_provider.py          ← DataProvider ABC + DataProviderError
  registry.py               ← ProviderRegistry con priorità e fallback
  yfinance_provider.py      ← wrapper yfinance con interfaccia standard
  cache_mixin.py            ← CacheMixin condiviso tra provider

tests/engine/providers/
  __init__.py
  test_base_provider.py     ← test interfaccia e contratti
  test_registry.py          ← test priorità, fallback, registrazione
  test_yfinance_provider.py ← test con mock yfinance
  fixtures/
    sample_ohlcv.py         ← DataFrame sintetico OHLCV per test
```

**Struttura base_provider.py:**
```python
# engine/market_data/providers/base_provider.py
"""DataProvider ABC — interfaccia comune per tutte le sorgenti dati.

Regola: ogni provider implementa get_history() e get_info().
        Il ProviderRegistry si occupa di routing e fallback.
        MAI chiamare un provider direttamente dalle pagine UI.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

@dataclass
class ProviderConfig:
    """Configurazione di un provider (letta da config/data_sources.yaml)."""
    name: str
    priority: int                    # 1 = massima priorità
    enabled: bool = True
    cache_ttl_seconds: int = 900     # 15 minuti default
    rate_limit_rpm: int = 60
    extra: dict = field(default_factory=dict)

class DataProvider(ABC):
    """Interfaccia comune per tutti i provider di dati finanziari."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificatore univoco del provider (es. 'yfinance', 'finnhub')."""
        ...

    @abstractmethod
    def get_history(
        self,
        symbol: str,
        start: str,          # YYYY-MM-DD
        end: str,            # YYYY-MM-DD
        interval: str = "1d" # "1m", "1h", "1d", "1wk", "1mo"
    ) -> pd.DataFrame:
        """
        Scarica storico OHLCV per un simbolo.
        Ritorna DataFrame con colonne: Open, High, Low, Close, Volume
        Index: DatetimeIndex UTC-aware.
        Raises:
            DataProviderError: se il fetch fallisce.
        """
        ...

    @abstractmethod
    def get_info(self, symbol: str) -> dict:
        """
        Ritorna metadati dello strumento (nome, settore, valuta, ecc.).
        Raises:
            DataProviderError: se il simbolo non esiste.
        """
        ...

    def is_available(self) -> bool:
        """Health check del provider (default: True). Override se necessario."""
        return True


class DataProviderError(Exception):
    """Errore del provider dati. Include provider name e simbolo."""
    def __init__(self, message: str, provider: str, symbol: str = "") -> None:
        super().__init__(message)
        self.provider = provider
        self.symbol = symbol
```

**Struttura registry.py:**
```python
# engine/market_data/providers/registry.py
"""ProviderRegistry: routing e fallback automatico tra provider.

Utilizzo:
    registry = ProviderRegistry.get_instance()
    df = registry.get_history("AAPL", "2020-01-01", "2024-01-01")
    # Tenta yfinance → se fallisce → Alpha Vantage → se fallisce → DataProviderError
"""
from __future__ import annotations
from typing import Optional
import structlog
from engine.market_data.providers.base_provider import DataProvider, DataProviderError

log = structlog.get_logger(__name__)

class ProviderRegistry:
    """Singleton. Gestisce priorità e fallback tra provider registrati."""
    _instance: Optional["ProviderRegistry"] = None

    def __init__(self) -> None:
        self._providers: list[DataProvider] = []   # ordinati per priorità

    @classmethod
    def get_instance(cls) -> "ProviderRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, provider: DataProvider, priority: int = 99) -> None:
        """Registra un provider. Priorità bassa = tentato prima."""
        self._providers.append(provider)
        self._providers.sort(key=lambda p: getattr(p, "_priority", priority))
        log.info("provider_registry.registered", provider=provider.name)

    def get_history(self, symbol: str, start: str, end: str, interval: str = "1d") -> pd.DataFrame:
        """Tenta i provider in ordine di priorità. Ritorna il primo successo."""
        errors = []
        for provider in self._providers:
            if not provider.is_available():
                continue
            try:
                df = provider.get_history(symbol, start, end, interval)
                log.info("provider_registry.success", provider=provider.name, symbol=symbol)
                return df
            except DataProviderError as e:
                log.warning("provider_registry.fallback", provider=provider.name, error=str(e))
                errors.append(e)
        raise DataProviderError(
            f"Tutti i provider hanno fallito per {symbol}: {errors}",
            provider="registry", symbol=symbol
        )
```

**Definition of Done — Sessione 1:**
```
□ engine/market_data/providers/base_provider.py: DataProvider ABC + DataProviderError
□ engine/market_data/providers/registry.py: ProviderRegistry singleton funzionante
□ engine/market_data/providers/yfinance_provider.py: get_history() + get_info()
□ YFinanceProvider: ritorna DataFrame con DatetimeIndex UTC-aware
□ tests/engine/providers/test_registry.py: priorità, fallback, provider unavailable
□ tests/engine/providers/test_yfinance_provider.py: mock completo (no chiamate reali)
□ pytest -m regression: 0 failed
□ mypy --strict su tutti i file in providers/: 0 errors
□ Coverage providers/: 100%
```

---

## 📅 SESSIONE 2 — Data Provider: Alpha Vantage + Finnhub (1–2h)

**Obiettivo:** Aggiungere due provider alternativi e testare il fallback automatico

**NON toccare:** `yfinance_provider.py`, fetcher esistenti, `pyproject.toml`

**Nota:** finnhub-python dovrebbe già essere in pyproject.toml (verificare con `poetry show | grep finnhub`). Se mancante, aggiungere in questa sessione.

**File da creare:**
```
engine/market_data/providers/
  alpha_vantage_provider.py   ← wrapper alpha_vantage con rate limit 5 RPM
  finnhub_provider.py         ← wrapper finnhub-python

tests/engine/providers/
  test_alpha_vantage_provider.py
  test_finnhub_provider.py
  test_fallback_chain.py       ← test fallback yfinance→AV→finnhub
```

**AlphaVantageProvider — Vincoli:**
```python
# Rate limit: 5 req/min (free tier) → sleep obbligatorio
# Usa RateLimitManager da shared/resilience/rate_limit_manager.py
# NON implementare rate limiting custom (violerebbe R28)

class AlphaVantageProvider(DataProvider):
    _priority = 2  # tentato dopo yfinance

    def get_history(self, symbol, start, end, interval="1d") -> pd.DataFrame:
        # 1. RateLimitManager.acquire("alpha_vantage")  ← obbligatorio
        # 2. alpha_vantage fetch
        # 3. Normalizza colonne → Open/High/Low/Close/Volume
        # 4. DatetimeIndex UTC-aware
        # 5. Filtra per [start, end]
```

**FinnhubProvider — Vincoli:**
```python
class FinnhubProvider(DataProvider):
    _priority = 3  # tentato per ultimo (candles API limitata nel free tier)

    def is_available(self) -> bool:
        # Verifica FINNHUB_API_KEY in .env → False se mancante
        return bool(os.getenv("FINNHUB_API_KEY"))
```

**test_fallback_chain.py:**
```python
def test_fallback_when_yfinance_fails(mock_providers):
    """Se yfinance fallisce, il registry usa Alpha Vantage."""
    mock_providers["yfinance"].get_history.side_effect = DataProviderError(...)
    mock_providers["av"].get_history.return_value = sample_ohlcv_df()

    result = registry.get_history("AAPL", "2023-01-01", "2024-01-01")
    assert not result.empty
    mock_providers["av"].get_history.assert_called_once()

def test_all_providers_fail_raises(mock_providers):
    """Se tutti falliscono → DataProviderError chiara."""
    for p in mock_providers.values():
        p.get_history.side_effect = DataProviderError(...)
    with pytest.raises(DataProviderError, match="Tutti i provider"):
        registry.get_history("INVALID", "2023-01-01", "2024-01-01")
```

**Definition of Done — Sessione 2:**
```
□ AlphaVantageProvider: usa RateLimitManager (verificato con mock)
□ FinnhubProvider: is_available() = False senza API key
□ Fallback chain testata: yfinance → AV → finnhub → DataProviderError
□ Tutti i test usano mock (nessuna chiamata API reale)
□ test_fallback_chain.py: almeno 5 scenari
□ pytest -m regression: 0 failed
□ Nessun provider supera il rate limit dichiarato in config/rate_limits.yaml
```

---

## 📅 SESSIONE 3 — Logging Strutturato e Test di Integrazione (1–2h)

**Obiettivo:** Completare il logging JSON, aggiungere test di integrazione per la pipeline dati

**NON toccare:** `shared/logger.py` (già presente), provider appena creati

**File da creare/modificare:**
```
shared/
  logging_config.py          ← configurazione JSON handler + rotation (NUOVO)

tests/integration/
  test_provider_pipeline.py  ← integrazione fetch→clean→validate (NUOVO)
  test_logging_output.py     ← verifica formato log JSON (NUOVO)

tests/
  conftest.py                ← aggiungere fixture synthetic_ohlcv_df
```

**logging_config.py:**
```python
# shared/logging_config.py
"""Configurazione logging strutturato JSON.

Setup:
    - Output: logs/market_ai.log (rotante, 20MB, 5 backup)
    - Errori API: logs/api_errors.log (separato)
    - Errori DB: logs/db_errors.log (separato)
    - Formato: JSON (facilmente parsabile da tool di monitoring)
    - request_id: aggiunto automaticamente via contextvars

Chiamare setup_logging() una sola volta all'avvio (in app_unified.py).
"""
import logging
import logging.handlers
from pathlib import Path

LOG_DIR = Path("logs")

def setup_logging(level: str = "INFO") -> None:
    """Configura logging strutturato JSON per tutto il progetto."""
    LOG_DIR.mkdir(exist_ok=True)
    # ... (implementazione completa JSON formatter + handlers)
```

**test_provider_pipeline.py (integrazione — NO chiamate reali):**
```python
@pytest.mark.integration
def test_full_pipeline_with_synthetic_data(synthetic_ohlcv_df):
    """
    Verifica fetch→clean→validate su dati sintetici.
    Non chiama API reali: usa un MockProvider con dati noti.
    """
    provider = MockProvider(return_df=synthetic_ohlcv_df)
    registry = ProviderRegistry()
    registry.register(provider, priority=1)

    df = registry.get_history("TEST", "2020-01-01", "2024-01-01")
    cleaner = DataCleaner()
    df_clean = cleaner.clean(df)
    # Pandera validation
    schema = OHLCVSchema()
    validated = schema.validate(df_clean)

    assert len(validated) > 0
    assert validated.index.tz is not None   # UTC-aware
    assert (validated["Close"] > 0).all()
```

**Definition of Done — Sessione 3:**
```
□ setup_logging(): log JSON su logs/market_ai.log, rotazione verificata
□ request_id propagato nei log (context variable)
□ Nessun print() residuo nei moduli engine/ e shared/ (grep verificato)
□ test_provider_pipeline.py: pipeline sintetica completa senza errori
□ test_logging_output.py: formato JSON valido parsabile
□ pytest -m integration: tutti i test passano (mock, no rete reale)
□ pytest -m regression: 0 failed
□ Coverage shared/logging_config.py: 100%
```

---

## 📅 SESSIONE 4 — GitHub Actions CI/CD e MkDocs (1–2h)

**Obiettivo:** Automatizzare test e generare documentazione navigabile

**NON toccare:** sorgenti del progetto, pyproject.toml (solo aggiunta mkdocs-material)

**File da creare:**
```
.github/
  workflows/
    ci.yml               ← test + coverage + mypy su ogni push/PR

docs/
  index.md               ← Home page documentazione
  architecture.md        ← Architettura a livelli con diagramma
  providers.md           ← Come aggiungere un nuovo DataProvider
  conventions.md         ← Le 32 regole v6.0
  contributing.md        ← Guida per contribuire

mkdocs.yml               ← Configurazione MkDocs Material
CONTRIBUTING.md          ← Guida rapida per sviluppatori (root del progetto)
```

**ci.yml — GitHub Actions:**
```yaml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install Poetry
        run: pip install poetry==2.4.1
      - name: Install dependencies
        run: poetry install --no-interaction
      - name: Regression tests (fast gate)
        run: poetry run pytest -m regression -q --tb=short
      - name: Full test suite with coverage
        run: poetry run pytest --cov --cov-fail-under=89 --tb=short
      - name: Type check
        run: poetry run mypy --strict engine/market_data/providers/
      - name: Lint
        run: poetry run ruff check .
```

**mkdocs.yml:**
```yaml
site_name: MarketAI Documentation
theme:
  name: material
  palette:
    scheme: slate
    primary: indigo
nav:
  - Home: index.md
  - Architettura: architecture.md
  - Data Providers: providers.md
  - Convenzioni: conventions.md
  - Contributing: contributing.md
```

**docs/providers.md — Template per aggiungere nuovo provider:**
```markdown
# Come aggiungere un Data Provider

## 1. Creare il file
`engine/market_data/providers/mio_provider.py`

## 2. Ereditare da DataProvider
```python
from engine.market_data.providers.base_provider import DataProvider

class MioProvider(DataProvider):
    _priority = 4   # tentato dopo gli altri

    @property
    def name(self) -> str:
        return "mio_provider"

    def get_history(self, symbol, start, end, interval="1d") -> pd.DataFrame:
        # La tua implementazione
        ...
```

## 3. Registrare nel registry
(in scripts/init_providers.py o all'avvio dell'app)
```

**Definition of Done — Sessione 4:**
```
□ .github/workflows/ci.yml: pipeline verde su push di test
□ mkdocs build: 0 errori, sito navigabile
□ docs/providers.md: guida completa con esempio
□ CONTRIBUTING.md: presente e leggibile
□ README.md: badge coverage aggiunto (link a CI)
□ poetry run mkdocs serve: funzionante in locale
□ pyproject.toml: mkdocs-material aggiunto (unica modifica consentita)
□ pytest -m regression: 0 failed
```

---

## 📅 SESSIONE 5 — Docstring, Bug Fix e Validazione Finale (1–2h)

**Obiettivo:** Completare docstring, risolvere warning CI, validare coverage complessiva

**NON toccare:** architettura già implementata

**Attività:**
```
1. Audit docstring — moduli prioritari:
   engine/market_data/providers/*.py   → 100% docstring
   shared/resilience/*.py              → 100% docstring
   engine/analytics/pipeline.py        → docstring + type hints completi

2. Fix warning mypy residui (se presenti):
   Eseguire: poetry run mypy --strict engine/ shared/ > mypy_report.txt
   Correggere top 10 errori per priorità

3. Aggiornare tests/fixtures/mock_builders.py:
   Aggiungere MockDataProvider factory
   Aggiungere synthetic_ohlcv_df con distribuzioni realistiche

4. Verifica finale coverage:
   pytest --cov --cov-report=html
   Identificare moduli sotto 80% → aggiungere test mancanti

5. Aggiornare CLAUDE.md → sezione "Moduli Chiave":
   Aggiungere ProviderRegistry nella sezione Database/Fetch
```

**Checklist validazione manuale:**
```
PROVIDER SYSTEM:
□ ProviderRegistry.get_history("AAPL", "2023-01-01", "2024-01-01") → DataFrame non vuoto
□ Fallback funziona: disabilitare yfinance → AV risponde
□ is_available() = False senza API key Finnhub → skip automatico

LOGGING:
□ Avvio app → logs/market_ai.log creato automaticamente
□ Fetch API → log entry con provider name, symbol, durata ms
□ Errore fetch → log entry in logs/api_errors.log

CI/CD:
□ Push su GitHub → GitHub Actions si avvia automaticamente
□ Coverage badge visibile nel README

DOCUMENTAZIONE:
□ mkdocs build → 0 errori
□ docs/providers.md: guida leggibile da chi non conosce il progetto
```

**Definition of Done — Sessione 5 (= Definition of Done Fase 1):**
```
□ mypy --strict engine/market_data/providers/: 0 errors
□ ruff check .: 0 warnings
□ pytest --cov --cov-fail-under=89: verde
□ GitHub Actions CI: pipeline verde su tutti i push
□ ProviderRegistry: fallback chain funzionante con mock
□ Logging JSON: formato verificato, nessun print() residuo
□ MkDocs: sito navigabile con almeno 4 pagine
□ CLAUDE.md: aggiornato con sezione DataProvider
□ Nessuna regressione su test esistenti
```

---

## 📁 Struttura File Finale v12.0.0

```
%APPDATA%\MarketAI\
├── engine/
│   └── market_data/
│       └── providers/              ★ NUOVO
│           ├── __init__.py
│           ├── base_provider.py    ← DataProvider ABC
│           ├── registry.py         ← ProviderRegistry
│           ├── cache_mixin.py
│           ├── yfinance_provider.py
│           ├── alpha_vantage_provider.py
│           └── finnhub_provider.py
├── shared/
│   └── logging_config.py           ★ NUOVO
├── tests/
│   ├── engine/
│   │   └── providers/              ★ NUOVO
│   │       ├── test_base_provider.py
│   │       ├── test_registry.py
│   │       ├── test_yfinance_provider.py
│   │       ├── test_alpha_vantage_provider.py
│   │       ├── test_finnhub_provider.py
│   │       └── test_fallback_chain.py
│   └── integration/
│       ├── test_provider_pipeline.py ★ NUOVO
│       └── test_logging_output.py    ★ NUOVO
├── .github/
│   └── workflows/
│       └── ci.yml                  ★ NUOVO
├── docs/                           ★ NUOVO
│   ├── index.md
│   ├── architecture.md
│   ├── providers.md
│   ├── conventions.md
│   └── contributing.md
├── logs/                           ★ NUOVO (generato a runtime)
│   ├── market_ai.log
│   ├── api_errors.log
│   └── db_errors.log
├── mkdocs.yml                      ★ NUOVO
└── CONTRIBUTING.md                 ★ NUOVO
```

---

## 📊 Metriche di Successo v12.0.0

| Metrica | Target |
|---------|--------|
| Coverage globale | ≥ 90% |
| Coverage engine/market_data/providers/ | 100% |
| mypy --strict su providers/ | 0 errors |
| Fallback chain: yfinance→AV→Finnhub | funzionante con mock |
| CI/CD GitHub Actions | Verde su ogni push |
| MkDocs build | 0 errori |
| Log JSON formato | Parsabile con jq |
| Nessun print() in engine/ e shared/ | Verificato con grep |
| Test regression: 0 failed | Sempre |

---

## 📝 Template Prompt Apertura Sessione Opus

```
Ciao. Leggi completamente CLAUDE.md prima di scrivere qualsiasi codice.

=== SESSIONE N — [nome sessione] ===

Contesto ambiente:
- Progetto in: %APPDATA%\MarketAI\
- Python: 3.12.10 (venv Poetry — NON usare 3.14.x di sistema)
- poetry run pytest -m regression → [N passed / 0 failed] ← eseguito ora

Task di questa sessione:
[descrizione specifica da questa roadmap]

File da creare:
- [lista da questa roadmap]

NON toccare:
- Fetcher esistenti in engine/market_data/fetchers/
- pyproject.toml (salvo eccezioni indicate)
- Dipendenze pinnate: yfinance==0.2.54, websockets, pandera

Definition of Done:
[copiare dalla sezione corrispondente]

Inizia con: poetry run pytest -m regression -q --tb=short
Poi procedi con il task.
```

---

*MarketAI v12.0.0 · Roadmap Fase 1 — Consolidamento Fondamenta*  
*Pianificazione: Claude Sonnet 4.6 · Implementazione: Claude Code Pro (Opus 4.8)*  
*Prerequisito: v11.0.0 completato · Durata stimata: 3 settimane · 5 sessioni da 1–2h*
