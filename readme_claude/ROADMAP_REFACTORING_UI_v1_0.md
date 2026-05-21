# MarketAI — Roadmap Refactoring & UI
## Component Library Completa · Rebuild Pagine · Design System
### Versione 1.0 — Maggio 2026
### Calibrata su Questionario Utente · Approccio Aggressivo

> **Parte da:** ROADMAP_CODE_QUALITY_v1_0 completata (v8.0.0 → v8.1.0)
> **Baseline:** v8.1.0 · 887 test · ≥ 95% coverage · 32 convenzioni attive
> **Target:** v8.2.0 — Component Library · Design System · UI rebuilt
> **Timeline:** 12 sessioni · 6 blocchi
> **Integra:** ROADMAP_FINAL_v1_0_IMPROVED (Fasi 5–11 in corso)

---

## 📋 CONFIGURAZIONE DA QUESTIONARIO

| Priorità sezioni | Pain points | UI | Codice | Approccio |
|---|---|---|---|---|
| 1. S0/S2 Infrastruttura | Navigazione confusa | Design coerente | Separa UI da logica | **Aggressivo** |
| 2. Mercato E1/K1/M* | Grafici piatti | Navigazione | Component library | 12 sessioni |
| 3. Analytics Q* | Pagine lente | Charts avanzati | — | — |
| 4. Portfolio P* | — | Componenti | — | — |
| 5. News N*/M7 | — | Loading/errori | — | — |

---

## 🔗 DOVE PARTE QUESTA ROADMAP

### Già completato da CODE_QUALITY v1_0 (NON rifare):
- `SK.*` session_keys — chiavi session_state tipizzate
- `CACHE_TTL.*` — TTL centralizzati per `@st.cache_data`
- `OP_CONFIG.*` — costanti operative da YAML
- `CurrencyConverter` — conversioni GBX/EUR→USD centralizzate
- `InstrumentRegistry` — mapping ticker su DuckDB
- `ErrorPolicy` — pattern error handling uniforme
- `try/except ImportError` silenzioso — rimosso da tutti i moduli
- Split `etoro_importer.py` + `live_market_service.py` — file < 300 righe

### Non ancora fatto (scope di questa roadmap):
- Nessuna component library condivisa tra le pagine
- Nessun design system formale (DESIGN_TOKENS parziale)
- Navigazione sidebar piatta (nessun raggruppamento logico)
- Ogni pagina è monolitica: data loading + rendering mischati
- Grafici senza tema consistente, senza regime shading
- Nessun test dedicato alla UI
- Stubs mancanti per le pagine delle Fasi 5-8 di ROADMAP_FINAL

---

## 🔄 INTEGRAZIONE CON ROADMAP_FINAL_v1_0_IMPROVED

Questa roadmap deve costruire l'infrastruttura UI che abilita le pagine future. Per ogni fase di ROADMAP_FINAL che produce una nuova pagina, questa roadmap crea lo **stub + component wiring**:

| Fase FINAL | Nuove pagine | Cosa crea questa roadmap |
|---|---|---|
| Fase 5 | — | `StatusDot` per nuove sorgenti in S0 |
| Fase 6 | N1 News Feed · N2 News Analysis | Stub completo con component library |
| Fase 7 | A1 Market Q&A · box K1 LLM | Stub A1 + box placeholder in K1 |
| Fase 8 | M7 IB Consensus | Stub con tabella + heatmap |
| Fase 10 | S2 Settings espanso | **Rebuild completo S2** con 7 sezioni |

**Regola:** ogni stub deve essere funzionante con dati mock, pronto per essere collegato ai backend reali durante le Fasi 5-11.

### K1 Composite Signal — Integrazione Signal Bus (v5_IMPROVED)
K1 viene rebuilt per mostrare il breakdown a 7+3 componenti:
- 7 componenti base (Technical, Macro, Labour, Sentiment, Valuation, Surprise, Volatility)
- 3 custom quality indicators (SignalConfidenceTracker, RegimeSignalFilter, ConsensusValidator)
- IC (Information Coefficient) per ogni componente
- Box "Analisi del Giorno" (placeholder LLM + template fallback)

---

## 🏗️ ARCHITETTURA TARGET — PAGE/COMPONENT PATTERN

### Il problema del pattern attuale

```python
# Pattern attuale — ogni pagina fa tutto (esempio P2, ~500 righe)
def body_portafoglio_etoro(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st
    # fetch data (logica business nel rendering)
    data = get_db_connection().query("SELECT ...")
    fx = CurrencyConverter().to_usd(...)
    # render (misto con la logica)
    st.metric("Valore", f"€{data.total:.0f}")
    col1, col2 = st.columns(2)
    fig = px.pie(...)
    st.plotly_chart(fig)
    # altro fetch + render mescolati
```

### Il pattern target (approccio aggressivo)

```python
# Pattern target — separazione netta load/render + componenti typed

# 1. DATA LOADER (testabile, no Streamlit)
def _load_portfolio_data(db: DuckDBManager) -> PortfolioSnapshot:
    """Carica e valida i dati del portfolio. NON importa streamlit."""
    raw = db.query(_PORTFOLIO_QUERY)
    return PortfolioSnapshot.from_dataframe(raw)   # Pandera schema

# 2. RENDERER (pragma: no cover, usa component library)
def _render_overview(snap: PortfolioSnapshot, tokens: DesignTokens) -> None:
    # pragma: no cover
    import streamlit as st
    from presentation.ui.components import KpiCard, ChartFactory, DataTable
    from presentation.ui.layout import two_column

    with two_column(ratio=[1, 2]) as (left, right):
        with left:
            KpiCard("Valore totale", snap.total_value_eur,
                    unit="€", delta=snap.pnl_pct,
                    quality_flag=snap.data_quality).render()
        with right:
            ChartFactory.pie_allocation(snap.positions).render()
    DataTable(snap.positions_df).render()

# 3. PAGE ENTRY POINT (< 30 righe, orchestration only)
@page_layout(title="Portfolio eToro", icon="ti-briefcase",
             cache_key="portfolio_overview", ttl=CACHE_TTL.PORTFOLIO_TOTALS)
def body_portafoglio_etoro(tokens: DesignTokens) -> None:  # pragma: no cover
    snap = _load_portfolio_data(get_db_connection())
    if snap.is_empty:
        EmptyState("Portfolio vuoto", hint="Importa le posizioni dalla tab Import").render()
        return
    _render_overview(snap, tokens)
```

**Benefici misurabili:**
- `_load_portfolio_data()` è testabile senza Streamlit → +coverage
- `_render_overview()` è < 30 righe → leggibile
- `body_portafoglio_etoro()` è < 30 righe → orchestrazione pura
- `KpiCard`, `ChartFactory`, `DataTable` usate in 10+ pagine → zero duplicazione

---

## 🗺️ NUOVA STRUTTURA NAVIGAZIONE

**Pain point #1:** "Difficile trovare la sezione giusta nella sidebar"

### Struttura attuale (piatta, ~35 voci)
```
Home · E1 · K1 · M1 · M2 · M3 · M4 · M5 · M6 · P1 · P2 · P3 ... (35 voci senza gerarchia)
```

### Struttura target (gerarchica, ricercabile)

```
┌─ SIDEBAR ─────────────────────────────────────────┐
│  🔍 Cerca pagina...         [input]                │
│                                                    │
│  📊 DASHBOARD               [K1 — active]          │
│  └── K1 Composite Signal ●                        │
│                                                    │
│  ▼ MERCATO                                        │
│  ├── E1 Market Overview                            │
│  └── M1-M6 Indicatori ›    [submenu 6 voci]       │
│                                                    │
│  ▼ ANALISI AVANZATA                               │
│  ├── Q1-Q8 Backtesting & Stress ›                 │
│  └── Q9-Q14 Correlazioni & Strategy ›             │
│                                                    │
│  ▼ PORTFOLIO                                      │
│  ├── P1 Panoramica                                 │
│  ├── P2 Posizioni eToro                            │
│  └── P3-P10 ›              [submenu 8 voci]       │
│                                                    │
│  ▼ INTELLIGENCE (★ in arrivo)                     │
│  ├── N1 News Feed           [placeholder]          │
│  ├── N2 News Analysis       [placeholder]          │
│  ├── M7 IB Consensus        [placeholder]          │
│  └── A1 Market Q&A          [placeholder]          │
│                                                    │
│  ▼ SISTEMA                                        │
│  ├── S0 Health Monitor                             │
│  └── S2 Impostazioni                              │
│                                                    │
│  ─────────────────────────────────────            │
│  v8.2.0 · 🟢 OPERATIONAL  [status pill]           │
└────────────────────────────────────────────────────┘
```

**Funzionalità sidebar:**
- Ricerca fuzzy sulle 35+ pagine (filtra in tempo reale)
- Indicatore pagina attiva (dot colorato)
- Badge "★ in arrivo" per pagine stub
- System status pill (OPERATIONAL / DEGRADED / DOWN) da S0
- Espansione/collasso persistente via `SK.SIDEBAR_*`

---

## 📁 STRUTTURA DIRECTORY — NUOVI FILE

```
presentation/
├── ui/
│   ├── design_tokens.py           ♻ ESTESO (era parziale)
│   ├── session_keys.py            ✓ già in CODE_QUALITY
│   ├── cache_policy.py            ✓ già in CODE_QUALITY
│   ├── layout.py                  ★ NUOVO — page_layout decorator + helpers
│   ├── chart_theme.py             ★ NUOVO — Plotly template da DesignTokens
│   ├── sidebar_nav.py             ★ NUOVO — navigazione gerarchica
│   └── components/
│       ├── __init__.py            ★ NUOVO — ComponentRegistry
│       ├── base.py                ★ NUOVO — BaseComponent ABC
│       ├── kpi_card.py            ★ NUOVO — metrica con delta
│       ├── signal_badge.py        ★ NUOVO — segnale [-1,1] tipizzato
│       ├── regime_pill.py         ★ NUOVO — etichetta regime mercato
│       ├── trend_sparkline.py     ★ NUOVO — mini chart inline
│       ├── chart_factory.py       ★ NUOVO — factory grafici Plotly
│       ├── data_table.py          ★ NUOVO — DataFrame styled + sort
│       ├── status_dot.py          ★ NUOVO — 🟢/🟡/🔴 con tooltip
│       ├── alert_card.py          ★ NUOVO — alert con severity
│       ├── section_header.py      ★ NUOVO — header pagina consistente
│       ├── empty_state.py         ★ NUOVO — empty/loading/error state
│       └── ic_breakdown_bar.py    ★ NUOVO — IC bar per Signal Bus (v5)
│
├── dashboard_engine/
│   └── pages/
│       ├── K1_Composite_Signal.py  ♻ REBUILT — Signal Bus breakdown
│       ├── E1_Market_Overview.py   ♻ REBUILT — KpiCard grid
│       ├── S0_Health.py            ♻ REBUILT — nuovi status + LLM
│       ├── S2_Settings.py          ♻ REBUILT — 7 sezioni FINAL Phase10
│       ├── M1_Macro_Signals.py     ♻ RESTYLED — chart theme
│       ├── [M2-M6]                 ♻ RESTYLED (identico pattern M1)
│       ├── [Q1-Q14]               ♻ RESTYLED — chart + filtri
│       ├── [P1-P10]               ♻ REBUILT — component pattern
│       ├── N1_News_Feed.py         ★ STUB — component library pronta
│       ├── N2_News_Analysis.py     ★ STUB
│       ├── M7_IB_Consensus.py      ★ STUB
│       └── A1_Market_QA.py         ★ STUB (LLM Phase 7)
│
└── sidebar.py                      ♻ REBUILT — usa sidebar_nav.py

tests/
└── ui/
    ├── test_components/
    │   ├── test_kpi_card.py
    │   ├── test_signal_badge.py
    │   ├── test_chart_factory.py
    │   ├── test_data_table.py
    │   ├── test_empty_state.py
    │   └── test_ic_breakdown_bar.py
    ├── test_layout.py
    └── test_sidebar_nav.py
```

---

## 🔵 BLOCCO A — Design Foundation (Sessioni 1–2)
> Prerequisito per tutti i blocchi successivi. Nessuna pagina viene rebuilt prima che la foundation sia completa e testata.

### Sessione 1 — DesignTokens + Layout + Sidebar

#### 1.A — `presentation/ui/design_tokens.py` (esteso)

```python
# presentation/ui/design_tokens.py — v8.2.0
"""Design token system per MarketAI dashboard.

Convenzione (Rule 20): zero colori/spacing hardcoded nelle pagine.
Tutti i valori estetici passano da qui.
"""
from __future__ import annotations
from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class _Colors:
    # Segnali [-1, 1]
    signal_strong_bull:  str = "#2d7a4f"   # verde scuro
    signal_bull:         str = "#5cba86"   # verde chiaro
    signal_neutral:      str = "#888780"   # grigio
    signal_bear:         str = "#d85a30"   # arancio/rosso
    signal_strong_bear:  str = "#a32d2d"   # rosso scuro

    # Regime mercato
    regime_bull:         str = "#5cba86"
    regime_bear:         str = "#d85a30"
    regime_stress:       str = "#a32d2d"
    regime_transition:   str = "#ba7517"

    # IC quality
    ic_ok:               str = "#5cba86"
    ic_low:              str = "#ba7517"
    ic_degraded:         str = "#d85a30"
    ic_unknown:          str = "#888780"

    # Sistema
    operational:         str = "#5cba86"
    degraded:            str = "#ba7517"
    down:                str = "#a32d2d"

    # Chart
    chart_primary:       str = "#534ab7"   # c-purple-600
    chart_secondary:     str = "#1d9e75"   # c-teal-400
    chart_accent:        str = "#ba7517"   # c-amber-600
    chart_negative:      str = "#d85a30"   # c-coral-400

    # Regime shading (semi-transparent per overlay su grafici)
    shade_bull:          str = "rgba(93,186,134,0.08)"
    shade_bear:          str = "rgba(216,90,48,0.10)"
    shade_stress:        str = "rgba(163,45,45,0.15)"


@dataclass(frozen=True)
class _Typography:
    font_main:    str = "system-ui, -apple-system, sans-serif"
    font_mono:    str = "'Menlo','Consolas',monospace"
    size_h1:      int = 22
    size_h2:      int = 18
    size_h3:      int = 16
    size_body:    int = 16
    size_caption: int = 13
    size_small:   int = 12
    weight_normal: int = 400
    weight_bold:   int = 500


@dataclass(frozen=True)
class _Spacing:
    xs:  int = 4
    sm:  int = 8
    md:  int = 16
    lg:  int = 24
    xl:  int = 32
    rad_sm:  int = 6
    rad_md:  int = 8
    rad_lg:  int = 12


@dataclass(frozen=True)
class DesignTokens:
    colors:     _Colors     = field(default_factory=_Colors)
    typography: _Typography = field(default_factory=_Typography)
    spacing:    _Spacing    = field(default_factory=_Spacing)

    def signal_color(self, value: float) -> str:
        """Restituisce il colore corretto per un segnale ∈ [-1,1]."""
        v = float(np.clip(value, -1.0, 1.0))
        if v > 0.5:  return self.colors.signal_strong_bull
        if v > 0.1:  return self.colors.signal_bull
        if v > -0.1: return self.colors.signal_neutral
        if v > -0.5: return self.colors.signal_bear
        return self.colors.signal_strong_bear

    def regime_color(self, regime: str) -> str:
        """Restituisce il colore del regime di mercato."""
        return {
            "bull":       self.colors.regime_bull,
            "bear":       self.colors.regime_bear,
            "stress":     self.colors.regime_stress,
            "transition": self.colors.regime_transition,
        }.get(regime.lower(), self.colors.signal_neutral)

    def ic_color(self, ic: float | None, flag: str = "ok") -> str:
        if flag == "low_ic":    return self.colors.ic_low
        if flag == "degraded":  return self.colors.ic_degraded
        if ic is None:          return self.colors.ic_unknown
        return self.colors.ic_ok


TOKENS = DesignTokens()
```

#### 1.B — `presentation/ui/layout.py` — Page Layout Decorator

```python
# presentation/ui/layout.py
"""Decoratore page_layout: wrappa ogni funzione di pagina.

Responsabilità:
  - Autenticazione (Rule 32: STREAMLIT_AUTH_TOKEN)
  - Error boundary: nessun traceback all'utente
  - SectionHeader automatico (titolo + icona)
  - Bottone "Aggiorna" che invalida la cache
  - Loading spinner durante il primo caricamento
  - Timestamp ultimo aggiornamento

Uso:
    @page_layout(title="Market Overview", icon="ti-chart-line")
    def body_market_overview(tokens: DesignTokens) -> None:  # pragma: no cover
        ...
"""
from __future__ import annotations
import functools
from typing import Callable
from presentation.ui.design_tokens import TOKENS, DesignTokens
from presentation.ui.session_keys import SK


def page_layout(
    title: str,
    icon: str,                      # Tabler icon name (es. "ti-chart-line")
    cache_key: str | None = None,
    ttl: int = 300,
    requires_auth: bool = True,
) -> Callable:
    """Decoratore per funzioni di pagina Streamlit."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> None:
            # pragma: no cover
            import streamlit as st
            from presentation.ui.components.section_header import SectionHeader
            from presentation.ui.components.empty_state import EmptyState

            # Auth check (Rule 32)
            if requires_auth and not _check_auth():
                st.stop()
                return

            SectionHeader(title=title, icon=icon, ttl=ttl).render()

            try:
                fn(*args, **kwargs)
            except Exception as exc:
                # ErrorPolicy: nessun traceback esposto all'utente
                from shared.resilience.error_policy import apply_error_policy
                from shared.logger import get_logger
                log = get_logger(__name__)
                log.error("page.render_failed", page=title, error=str(exc), exc_info=True)
                EmptyState(
                    title="Pagina non disponibile",
                    hint=f"Errore caricando '{title}'. Riprova o controlla S0 Health.",
                    severity="error",
                ).render()

        return wrapper
    return decorator


def _check_auth() -> bool:
    """Verifica autenticazione via STREAMLIT_AUTH_TOKEN o st.secrets."""
    import os, streamlit as st
    token = os.getenv("STREAMLIT_AUTH_TOKEN")
    if token:
        input_token = st.session_state.get(SK.AUTH_TOKEN, "")
        return input_token == token
    return True   # Se token non configurato → nessuna auth richiesta
```

#### 1.C — `presentation/ui/sidebar_nav.py` — Navigazione Gerarchica

```python
# presentation/ui/sidebar_nav.py
"""Navigazione sidebar gerarchica con ricerca e status pill.

Sostituisce il file sidebar.py esistente.
Struttura: Dashboard → Mercato → Analisi Avanzata → Portfolio → Intelligence → Sistema

Usa SK.SIDEBAR_* per persistere lo stato espansione/collasso.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from presentation.ui.session_keys import SK
from presentation.ui.design_tokens import TOKENS


@dataclass
class NavPage:
    """Singola voce di navigazione."""
    id: str
    label: str
    icon: str                        # Tabler icon name
    page_file: str                   # Nome del file pagina
    is_stub: bool = False            # True per pagine future (badge "★ in arrivo")
    badge: str | None = None         # Badge opzionale es. "NEW"


@dataclass
class NavGroup:
    """Gruppo di voci di navigazione."""
    id: str
    label: str
    icon: str
    pages: list[NavPage] = field(default_factory=list)
    expanded_by_default: bool = False


NAV_STRUCTURE: list[NavGroup | NavPage] = [
    NavPage("dashboard", "Dashboard", "ti-layout-dashboard", "K1_Composite_Signal"),

    NavGroup("mercato", "Mercato", "ti-chart-line", expanded_by_default=True, pages=[
        NavPage("e1", "Market Overview", "ti-eye", "E1_Market_Overview"),
        NavPage("m1", "Macro Conviction", "ti-world", "M1_Macro_Signals"),
        NavPage("m2", "VIX & Volatility", "ti-wave-saw-tool", "M2_VIX_Signals"),
        NavPage("m3", "Labour Market", "ti-users", "M3_Labour_Market"),
        NavPage("m4", "Yield Curve", "ti-chart-dots", "M4_Yield_Curve"),
        NavPage("m5", "Economic Surprise", "ti-bolt", "M5_Economic_Surprise"),
        NavPage("m6", "Valuation P/E", "ti-calculator", "M6_Valuation_PE"),
    ]),

    NavGroup("analytics", "Analisi Avanzata", "ti-math-function", pages=[
        NavPage("q1", "Backtesting", "ti-player-play", "Q1_Backtesting"),
        NavPage("q2", "Stress Test", "ti-alert-triangle", "Q2_Stress_Test"),
        NavPage("q3", "Correlazioni", "ti-arrows-split", "Q3_Correlations"),
        NavPage("q4", "Portfolio Optimizer", "ti-adjustments", "Q4_Optimizer"),
        NavPage("q5", "Sentiment Analysis", "ti-mood-happy", "Q5_Sentiment"),
        NavPage("q11", "Options Analytics", "ti-currency-dollar", "Q11_Options"),
        NavPage("q12", "Multi-Timeframe", "ti-clock", "Q12_MultiTimeframe"),
        NavPage("q14", "Strategy Lab", "ti-flask", "Q14_Strategy_Lab"),
    ]),

    NavGroup("portfolio", "Portfolio", "ti-briefcase", pages=[
        NavPage("p1", "Panoramica", "ti-home", "P1_Overview"),
        NavPage("p2", "Posizioni eToro", "ti-table", "P2_Portafoglio_eToro"),
        NavPage("p3", "Import Manuale", "ti-upload", "P3_Manual_Entry"),
        NavPage("p4", "Profilo Investitore", "ti-user", "P4_Investor_Profile"),
        NavPage("p5", "Risk Analysis", "ti-shield", "P5_Risk_Analysis"),
        NavPage("p10", "Obiettivi", "ti-target", "P10_Goals"),
    ]),

    NavGroup("intelligence", "Intelligence", "ti-brain", pages=[
        NavPage("n1", "News Feed", "ti-news", "N1_News_Feed",
                is_stub=True, badge="Fase 6"),
        NavPage("n2", "News Analysis", "ti-chart-pie", "N2_News_Analysis",
                is_stub=True, badge="Fase 6"),
        NavPage("m7", "IB Forecast", "ti-building-bank", "M7_IB_Consensus",
                is_stub=True, badge="Fase 8"),
        NavPage("a1", "Market Q&A", "ti-message-dots", "A1_Market_QA",
                is_stub=True, badge="Fase 7"),
        NavPage("c1", "Custom Indicators", "ti-tools", "C1_Custom_Indicators"),
    ]),

    NavGroup("sistema", "Sistema", "ti-settings", pages=[
        NavPage("s0", "Health Monitor", "ti-activity", "S0_Health"),
        NavPage("s2", "Impostazioni", "ti-adjustments", "S2_Settings"),
    ]),
]


class SidebarNavigator:
    """Renderizza la navigazione gerarchica nella sidebar Streamlit."""

    def render(self) -> None:  # pragma: no cover
        import streamlit as st
        from shared.monitoring.system_status import get_system_status

        status = get_system_status()   # OPERATIONAL / DEGRADED / DOWN
        status_color = {
            "OPERATIONAL": TOKENS.colors.operational,
            "DEGRADED":    TOKENS.colors.degraded,
            "DOWN":        TOKENS.colors.down,
        }.get(status, TOKENS.colors.degraded)

        # Quick search
        query = st.sidebar.text_input(
            "", placeholder="🔍 Cerca pagina...",
            key=SK.SIDEBAR_SEARCH, label_visibility="collapsed",
        )

        # Navigation groups
        for item in NAV_STRUCTURE:
            if isinstance(item, NavPage):
                self._render_page_link(item, query)
            else:
                self._render_group(item, query)

        # System status pill at bottom
        st.sidebar.markdown("---")
        st.sidebar.markdown(
            f'<div style="font-size:12px;color:{status_color};text-align:center">'
            f'● {status.title()}'
            f'</div>',
            unsafe_allow_html=True,
        )

    def _render_group(self, group: NavGroup, query: str) -> None:  # pragma: no cover
        import streamlit as st
        key = f"{SK.SIDEBAR_EXPANDED_PREFIX}{group.id}"
        matching = [p for p in group.pages if not query or query.lower() in p.label.lower()]
        if not matching:
            return
        with st.sidebar.expander(
            f"{group.label}",
            expanded=st.session_state.get(key, group.expanded_by_default),
        ):
            for page in matching:
                self._render_page_link(page, query)

    @staticmethod
    def _render_page_link(page: NavPage, query: str) -> None:  # pragma: no cover
        import streamlit as st
        if query and query.lower() not in page.label.lower():
            return
        label = page.label
        if page.is_stub and page.badge:
            label = f"{label} · _{page.badge}_"
        st.sidebar.page_link(f"pages/{page.page_file}.py", label=label,
                             icon=f":{page.icon.replace('ti-','').replace('-','_')}:")
```

### Sessione 2 — Component Library Core (6 componenti fondamentali)

#### 2.A — `presentation/ui/components/base.py`

```python
# presentation/ui/components/base.py
"""BaseComponent: classe base per tutti i componenti UI."""
from __future__ import annotations
from abc import ABC, abstractmethod


class BaseComponent(ABC):
    """Classe base astratta per componenti UI Streamlit.

    Ogni componente:
      - Ha un metodo render() che chiama Streamlit (pragma: no cover)
      - Ha un metodo to_html() testabile senza Streamlit
      - Usa solo DESIGN_TOKENS per valori estetici

    Test pattern:
        comp = KpiCard("Valore", 1234.5, unit="€")
        assert "1.234" in comp.to_html()   # testabile senza Streamlit
        assert "€" in comp.to_html()
    """

    @abstractmethod
    def render(self) -> None:
        """Renderizza il componente in Streamlit. pragma: no cover."""
        ...

    @abstractmethod
    def to_html(self) -> str:
        """Restituisce una rappresentazione HTML testabile senza Streamlit."""
        ...
```

#### 2.B — `presentation/ui/components/kpi_card.py`

```python
# presentation/ui/components/kpi_card.py
"""KpiCard: metric display con delta, tooltip e quality flag.

Il componente più usato nella dashboard: compare in E1, K1, P1, S0, M1-M6.
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np

from presentation.ui.components.base import BaseComponent
from presentation.ui.design_tokens import TOKENS


@dataclass
class KpiCard(BaseComponent):
    """Metrica con etichetta, valore, delta e indicatore qualità.

    Args:
        title:       Etichetta breve (≤ 20 caratteri consigliati)
        value:       Valore numerico o stringa preformattata
        unit:        Unità di misura (€, %, bps, ecc.)
        delta:       Variazione percentuale (positivo = verde, negativo = rosso)
        delta_label: Descrizione della variazione (es. "vs 1 settimana")
        quality_flag: "ok"|"low_ic"|"insufficient_data"|"stale" (da Signal Bus)
        icon:        Tabler icon name opzionale
        tooltip:     Testo tooltip hover

    Example:
        KpiCard("Valore Portfolio", 45230.0, unit="€",
                delta=2.3, delta_label="vs ieri").render()
    """
    title:        str
    value:        float | str
    unit:         str = ""
    delta:        float | None = None
    delta_label:  str = ""
    quality_flag: str = "ok"
    icon:         str = ""
    tooltip:      str = ""

    def _format_value(self) -> str:
        if isinstance(self.value, str):
            return self.value
        v = float(self.value)
        if abs(v) >= 1_000_000:
            return f"{v/1_000_000:.1f}M"
        if abs(v) >= 1_000:
            return f"{v:,.0f}"
        return f"{v:.2f}"

    def _quality_indicator(self) -> str:
        flags = {
            "ok":                "●",
            "low_ic":            "◐",
            "insufficient_data": "○",
            "stale":             "◌",
        }
        return flags.get(self.quality_flag, "○")

    def to_html(self) -> str:
        """Restituisce HTML del componente — testabile senza Streamlit."""
        delta_str = ""
        if self.delta is not None:
            sign = "+" if self.delta >= 0 else ""
            delta_str = f'{sign}{self.delta:.1f}%'
            if self.delta_label:
                delta_str += f" {self.delta_label}"
        quality = self._quality_indicator()
        return (
            f'<div class="kpi-card">'
            f'<span class="kpi-title">{self.title}</span>'
            f'<span class="kpi-value">{self._format_value()}{self.unit}</span>'
            f'<span class="kpi-delta">{delta_str}</span>'
            f'<span class="kpi-quality">{quality}</span>'
            f'</div>'
        )

    def render(self) -> None:  # pragma: no cover
        import streamlit as st
        delta_color = (
            "normal" if self.delta is None
            else "off" if abs(self.delta) < 0.01
            else "normal" if self.delta > 0 else "inverse"
        )
        help_text = self.tooltip or None
        st.metric(
            label=f"{self.title} {self._quality_indicator()}",
            value=f"{self._format_value()}{self.unit}",
            delta=f"{self.delta:+.1f}% {self.delta_label}".strip() if self.delta else None,
            delta_color=delta_color,
            help=help_text,
        )
```

#### 2.C — `presentation/ui/components/signal_badge.py`

```python
# presentation/ui/components/signal_badge.py
"""SignalBadge: visualizza un segnale [-1,1] con colore e label.

Usato in: K1 (breakdown componenti), E1 (segnali laterali), S0 (signal quality).
"""
from __future__ import annotations
from dataclasses import dataclass

import numpy as np

from presentation.ui.components.base import BaseComponent
from presentation.ui.design_tokens import TOKENS


@dataclass
class SignalBadge(BaseComponent):
    """Badge colorato per segnale ∈ [-1, 1].

    Args:
        name:         Nome del segnale (es. "Technical Composite")
        value:        Valore [-1, 1]
        confidence:   Confidenza [0, 1]
        ic_estimate:  IC stimato (Information Coefficient)
        quality_flag: Flag qualità dal AlphaDecayMonitor

    Example:
        SignalBadge("Technical", 0.42, confidence=0.85, ic_estimate=0.07).render()
    """
    name:         str
    value:        float
    confidence:   float = 1.0
    ic_estimate:  float | None = None
    quality_flag: str = "ok"

    @property
    def direction(self) -> str:
        v = float(np.clip(self.value, -1.0, 1.0))
        if v > 0.3:   return "RIALZISTA"
        if v > 0.05:  return "lieve ↑"
        if v > -0.05: return "NEUTRO"
        if v > -0.3:  return "lieve ↓"
        return "RIBASSISTA"

    @property
    def color(self) -> str:
        return TOKENS.signal_color(self.value)

    def to_html(self) -> str:
        ic_str = f"IC:{self.ic_estimate:.3f}" if self.ic_estimate is not None else ""
        return (
            f'<span class="signal-badge" style="color:{self.color}">'
            f'{self.name}: {self.value:+.3f} ({self.direction}) {ic_str}'
            f'</span>'
        )

    def render(self) -> None:  # pragma: no cover
        import streamlit as st
        ic_str = f" · IC {self.ic_estimate:.3f}" if self.ic_estimate is not None else ""
        conf_str = f" · conf. {self.confidence:.0%}" if self.confidence < 0.9 else ""
        flag_icon = {"ok":"●","low_ic":"◐","insufficient_data":"○"}.get(self.quality_flag,"○")
        st.markdown(
            f'<div style="padding:6px 10px;border-radius:6px;'
            f'background:rgba(0,0,0,0.05);margin-bottom:4px">'
            f'<span style="font-size:13px;color:{self.color}">'
            f'{flag_icon} <strong>{self.name}</strong>: '
            f'{self.value:+.3f} · {self.direction}{ic_str}{conf_str}'
            f'</span></div>',
            unsafe_allow_html=True,
        )
```

#### 2.D — `presentation/ui/chart_theme.py` — Tema Plotly Uniforme

```python
# presentation/ui/chart_theme.py
"""Tema Plotly e factory chart per MarketAI.

Ogni grafico nella dashboard deve usare questo tema — zero config Plotly inline.

Funzionalità chiave:
  1. Tema base da DESIGN_TOKENS (colori, font, spacing)
  2. regime_shade(): aggiunge shading colorato per regime mercato
  3. event_markers(): aggiunge annotazioni per eventi (Fed, NFP, ecc.)
  4. Formato asse Y automatico (K/M/€/%)
"""
from __future__ import annotations
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from presentation.ui.design_tokens import TOKENS


def get_base_layout(**overrides: Any) -> dict:
    """Layout Plotly base consistente con DESIGN_TOKENS."""
    return {
        "font":            {"family": TOKENS.typography.font_main, "size": 13},
        "plot_bgcolor":    "rgba(0,0,0,0)",
        "paper_bgcolor":   "rgba(0,0,0,0)",
        "margin":          {"t": 40, "b": 30, "l": 50, "r": 20},
        "xaxis":           {"showgrid": False, "linecolor": "#cccccc", "tickfont": {"size": 11}},
        "yaxis":           {"gridcolor": "rgba(200,200,200,0.2)", "tickfont": {"size": 11}},
        "hovermode":       "x unified",
        "legend":          {"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "left", "x": 0},
        **overrides,
    }


def regime_shade(
    fig: go.Figure,
    regime_df: pd.DataFrame,
    date_col: str = "date",
    regime_col: str = "regime",
) -> go.Figure:
    """Aggiunge shading semitrasparente per ogni regime sul grafico.

    Args:
        fig:        Figura Plotly da aggiornare.
        regime_df:  DataFrame con colonne date e regime (bull/bear/stress/transition).
        date_col:   Nome colonna date.
        regime_col: Nome colonna regime.

    Returns:
        Figura aggiornata con vrect per ogni periodo di regime.
    """
    if regime_df.empty:
        return fig

    shade_colors = {
        "bull":       TOKENS.colors.shade_bull,
        "bear":       TOKENS.colors.shade_bear,
        "stress":     TOKENS.colors.shade_stress,
        "transition": "rgba(186,117,23,0.06)",
    }

    # Raggruppa periodi consecutivi dello stesso regime
    df = regime_df.sort_values(date_col).copy()
    df["group"] = (df[regime_col] != df[regime_col].shift()).cumsum()

    for _, grp in df.groupby("group"):
        regime = grp[regime_col].iloc[0]
        color = shade_colors.get(regime)
        if color is None:
            continue
        fig.add_vrect(
            x0=grp[date_col].min(),
            x1=grp[date_col].max(),
            fillcolor=color,
            layer="below",
            line_width=0,
        )
    return fig


def event_markers(
    fig: go.Figure,
    events: list[dict],   # [{"date": "2024-03-20", "label": "FOMC", "color": "#888"}]
) -> go.Figure:
    """Aggiunge linee verticali annotate per eventi chiave."""
    for ev in events:
        fig.add_vline(
            x=ev["date"],
            line_width=1,
            line_dash="dot",
            line_color=ev.get("color", "#888780"),
            annotation_text=ev.get("label", ""),
            annotation_position="top left",
            annotation_font_size=10,
        )
    return fig


class ChartFactory:
    """Factory per tutti i tipi di grafico usati nella dashboard."""

    @staticmethod
    def time_series(
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        title: str = "",
        color: str | None = None,
        y_format: str = "number",      # "number"|"percent"|"currency"
        regime_df: pd.DataFrame | None = None,
        events: list[dict] | None = None,
    ) -> go.Figure:
        """Time series standard con regime shading e event markers opzionali."""
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df[x_col], y=df[y_col],
            mode="lines",
            line={"color": color or TOKENS.colors.chart_primary, "width": 2},
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2f}</b><extra></extra>",
        ))

        tick_format = {
            "percent":  ".1%",
            "currency": ",.0f",
            "number":   ".2f",
        }.get(y_format, ".2f")

        layout = get_base_layout(title={"text": title, "font": {"size": 14}})
        layout["yaxis"]["tickformat"] = tick_format
        fig.update_layout(**layout)

        if regime_df is not None and not regime_df.empty:
            regime_shade(fig, regime_df)
        if events:
            event_markers(fig, events)
        return fig

    @staticmethod
    def signal_breakdown(
        signals: dict[str, tuple[float, float | None]],   # {name: (value, ic)}
        regime: str = "transition",
        title: str = "Composite Signal — Breakdown",
    ) -> go.Figure:
        """Barre orizzontali per breakdown Composite Signal.

        Args:
            signals: {nome_segnale: (valore, ic_estimate)}
            regime:  Regime corrente (per titolo e colore dominante)
            title:   Titolo del grafico

        Usato in K1_Composite_Signal.py
        """
        names  = list(signals.keys())
        values = [v for v, _ in signals.values()]
        colors = [TOKENS.signal_color(v) for v in values]

        fig = go.Figure(go.Bar(
            y=names, x=values,
            orientation="h",
            marker_color=colors,
            hovertemplate="<b>%{y}</b>: %{x:+.3f}<extra></extra>",
            text=[f"{v:+.3f}" for v in values],
            textposition="auto",
        ))
        fig.add_vline(x=0, line_width=1, line_color="rgba(128,128,128,0.4)")
        layout = get_base_layout(title={"text": title, "font": {"size": 14}})
        layout["xaxis"].update({"range": [-1.1, 1.1], "tickformat": "+.1f"})
        fig.update_layout(**layout)
        return fig

    @staticmethod
    def correlation_heatmap(
        corr_matrix: pd.DataFrame,
        title: str = "Matrice Correlazioni",
        fmt: str = ".2f",
    ) -> go.Figure:
        """Heatmap correlazioni con scala divergente RdYlGn."""
        fig = go.Figure(go.Heatmap(
            z=corr_matrix.values,
            x=list(corr_matrix.columns),
            y=list(corr_matrix.index),
            colorscale="RdYlGn",
            zmin=-1, zmax=1,
            text=[[f"{v:{fmt}}" for v in row] for row in corr_matrix.values],
            texttemplate="%{text}",
            hovertemplate="<b>%{y}</b> vs <b>%{x}</b>: %{z:.3f}<extra></extra>",
        ))
        fig.update_layout(**get_base_layout(title={"text": title, "font": {"size": 14}}))
        return fig

    @staticmethod
    def pie_allocation(
        labels: list[str],
        values: list[float],
        title: str = "Allocazione",
    ) -> go.Figure:
        """Pie chart per composizione portfolio."""
        fig = go.Figure(go.Pie(
            labels=labels, values=values,
            textinfo="label+percent",
            hovertemplate="<b>%{label}</b>: %{value:.1f}%<extra></extra>",
            marker_colors=[
                TOKENS.colors.chart_primary,
                TOKENS.colors.chart_secondary,
                TOKENS.colors.chart_accent,
                "#7f77dd", "#5dcaa5", "#ef9f27",
            ][:len(labels)],
        ))
        fig.update_layout(**get_base_layout(title={"text": title, "font": {"size": 14}},
                                             showlegend=True))
        return fig
```

#### 2.E — `presentation/ui/components/empty_state.py`

```python
# presentation/ui/components/empty_state.py
"""EmptyState: gestione unificata di stati vuoti, loading, errori."""
from __future__ import annotations
from dataclasses import dataclass
from presentation.ui.components.base import BaseComponent


@dataclass
class EmptyState(BaseComponent):
    """Componente unificato per stati non-dati.

    Args:
        title:    Titolo dello stato (es. "Nessun dato disponibile")
        hint:     Suggerimento azione per l'utente
        severity: "info"|"warning"|"error"|"loading"
        icon:     Tabler icon override (opzionale)

    Example:
        EmptyState("Portfolio vuoto",
                   hint="Importa le posizioni dalla tab Import",
                   severity="info").render()
    """
    title:    str
    hint:     str = ""
    severity: str = "info"     # "info"|"warning"|"error"|"loading"
    icon:     str = ""

    _ICONS = {
        "info":    "ti-info-circle",
        "warning": "ti-alert-triangle",
        "error":   "ti-x-circle",
        "loading": "ti-loader",
    }

    def to_html(self) -> str:
        icon = self.icon or self._ICONS.get(self.severity, "ti-info-circle")
        return f'<div class="empty-state severity-{self.severity}"><i class="{icon}"></i><h3>{self.title}</h3><p>{self.hint}</p></div>'

    def render(self) -> None:  # pragma: no cover
        import streamlit as st
        handlers = {
            "info":    st.info,
            "warning": st.warning,
            "error":   st.error,
            "loading": lambda m: st.info(f"⏳ {m}"),
        }
        msg = f"**{self.title}**\n\n{self.hint}" if self.hint else f"**{self.title}**"
        handlers.get(self.severity, st.info)(msg)
```

**Definition of Done — Blocco A:**
```
□ DesignTokens: tutte le funzioni token-based (signal_color, regime_color, ic_color)
□ page_layout: decorator funzionante su almeno 1 pagina demo
□ SidebarNavigator: tutti i 5 gruppi presenti + ricerca funzionante
□ BaseComponent: ABC con render() e to_html() implementati
□ KpiCard: to_html() testabile senza Streamlit + render() su demo
□ SignalBadge: 5 livelli di direction corretti (test unitario)
□ ChartFactory.signal_breakdown: barre orizzontali con colori corretti
□ ChartFactory.time_series: con e senza regime_shade (test fixture DuckDB)
□ EmptyState: tutti e 4 i severity levels renderizzano correttamente
□ test_kpi_card.py: coverage ≥ 90% su to_html()
□ test_signal_badge.py: direction corretto per 10 valori campione
□ test_chart_factory.py: chart ritorna Figure valida su fixture
□ ruff + mypy --strict: 0 errori sui nuovi file
□ Tutti gli 887 test esistenti passano (zero regressioni)
```

---

## 🟢 BLOCCO B — Infrastructure UI: S0 & S2 (Sessioni 3–4)
> Priorità #1 del questionario. Le pagine di infrastruttura sono usate ogni sessione.

### Sessione 3 — S0 Health Monitor Rebuild

**S0 è il pannello di controllo del sistema.** Con le Fasi 5-11 di ROADMAP_FINAL che aggiungono nuovi motori (Signal Bus, LLM, News Engine, IB Forecast), S0 deve essere rebuilt per mostrare tutti i nuovi componenti.

**Nuovo layout S0 (a tab):**
```
Tab 1: Sorgenti Dati    → DataSourceManager status (Fase 5) + StatusDot per ogni fonte
Tab 2: Motori Analitici → Composite Signal v3, Labour, Valuation, Correlations
Tab 3: Signal Quality   → IC per ogni segnale (da AlphaDecayMonitor) + quality flags
Tab 4: LLM Status       → Ollama (mistral:7b-q4), latenza, modello caricato
Tab 5: News & IB        → News Engine status, IB Forecast stage (regex vs LLM)
Tab 6: Scheduler        → Job status, ultima esecuzione, prossima esecuzione
Tab 7: System Log       → Ultimi 50 log strutturati (dal logger)
```

**`StatusDot` component (nuovo):**
```python
@dataclass
class StatusDot(BaseComponent):
    """Indicatore stato con colore e tooltip (🟢/🟡/🔴)."""
    label: str
    status: str       # "ok"|"degraded"|"error"|"unknown"
    detail: str = ""  # Dettaglio per tooltip
    last_update: str = ""

    _COLORS = {"ok": "🟢", "degraded": "🟡", "error": "🔴", "unknown": "⚪"}

    def to_html(self) -> str:
        dot = self._COLORS.get(self.status, "⚪")
        return f'<span title="{self.detail}">{dot} {self.label}</span>'
```

**Definition of Done — Sessione 3:**
```
□ S0: 7 tab presenti, ognuno carica senza crash con DB vuoto
□ Tab 3 (Signal Quality): IC per ogni segnale da AlphaDecayMonitor visibile
□ Tab 4 (LLM): mostra "Non configurato" se Ollama non attivo (no crash)
□ Tab 5 (News): mostra placeholder se Fase 6 non ancora implementata
□ StatusDot: to_html() testabile + tutti i 4 status corretti
□ test_status_dot.py: coverage ≥ 90%
□ S0 caricamento < 2s (tutti i dati cached con CACHE_TTL.* appropriati)
```

### Sessione 4 — S2 Settings Rebuild (7 sezioni da ROADMAP_FINAL Phase 10)

**S2 implementa le 7 sezioni di S2_Settings.py da ROADMAP_FINAL_v1_0_IMPROVED §10.2:**

```
Sezione 1: API Keys & Connessioni
  - Campo per ogni API key (FINNHUB_API_KEY, FRED_API_KEY, ecc.)
  - Bottone "Test connessione" → StatusDot live
  - Rate limit configurabili

Sezione 2: Feature Flags
  - Toggle visuale per ogni flag in feature_flags.yaml
  - Descrizione per ogni feature (cosa fa, quando abilitare)
  - Badge "⚠ Riavvio suggerito" dopo modifica

Sezione 3: LLM Configuration
  - Status hardware (RAM, GPU, disco)
  - Modello Ollama selezionato (default: mistral:7b-q4)
  - Bottone "Test inference" con timer
  - Bottone "Download modello" (ollama pull)
  - Fallback: template deterministico se Ollama non disponibile

Sezione 4: Data Retention
  - Config retention per ogni tipo di dato (YAML → slider)
  - Visualizzazione spazio DB (DuckDB + SQLite in MB)
  - Bottone "Pulisci dati vecchi" con preview

Sezione 5: Scheduler
  - Toggle on/off per ogni job scheduler
  - Orari configurabili (cron expression → human readable)
  - Log ultime 5 esecuzioni per job

Sezione 6: Backup & Restore
  - Backup manuale immediato (bottone)
  - Lista backup con timestamp e dimensione
  - Restore da backup selezionato
  - Config backup automatico

Sezione 7: Notifiche
  - Toggle notifiche desktop
  - Soglie alert configurabili (slider)
  - Bottone "Test notifica"
```

**Definition of Done — Sessione 4:**
```
□ S2: 7 sezioni presenti con navigation tab
□ Sezione 2 (Feature Flags): tutti i flag da feature_flags.yaml visualizzati
□ Sezione 3 (LLM): mostra mistral:7b-q4 status + test inference funzionante
□ Sezione 6 (Backup): backup manuale crea file in backups/ directory
□ S2 non crasha se un'API key è mancante (graceful degradation)
□ Ogni campo modifica aggiorna il YAML corrispondente (non solo session state)
□ S2 caricamento < 1.5s
```

---

## 🟡 BLOCCO C — Mercato & Analisi (Sessioni 5–7)
> Priorità #2. Include il rebuild critico di K1 con Signal Bus breakdown.

### Sessione 5 — E1 Market Overview Rebuild

E1 è la pagina più visitata. Rebuild completo con KpiCard grid:

```
NUOVO LAYOUT E1:
  ┌── KPI ROW ─────────────────────────────────────────────────────────┐
  │  KpiCard(S&P500) | KpiCard(VIX) | KpiCard(Yield10Y) | KpiCard(DXY) │
  │  KpiCard(EUR/USD)| KpiCard(Gold) | KpiCard(Oil WTI) | KpiCard(BTC) │
  └────────────────────────────────────────────────────────────────────┘
  ┌── MAIN CHARTS ──────────────────────────────────┬── SIGNALS ───────┐
  │  Tab 1: S&P500 12M (con regime shading)         │ Composite v3 box │
  │  Tab 2: Macro conviction heatmap 6M             │ SignalBadge ×7   │
  │  Tab 3: Sector performance (barre)              │ Regime: [pill]   │
  └─────────────────────────────────────────────────┴──────────────────┘
```

- Tutti gli 8 KPI usando `KpiCard` component
- Charts via `ChartFactory` con regime shading da DB
- Lazy tab loading: solo il tab attivo fa query DuckDB

**Definition of Done — Sessione 5:**
```
□ E1: 8 KpiCard con delta (valore attuale vs chiusura precedente)
□ Tab S&P500: regime shading visibile su grafico (4 regimi)
□ Lazy tab: Tab 2 e Tab 3 non fanno query DB finché non vengono aperti
□ E1 caricamento < 2s (KPI da LiveMarketService cached)
□ Nessun valore hardcoded nel rendering (tutto da DESIGN_TOKENS)
```

### Sessione 6 — K1 Composite Signal Rebuild (Signal Bus v5 integration)

**K1 è la pagina più importante analiticamente.** Rebuild per integrare il Signal Bus da ROADMAP_v5_IMPROVED:

```
NUOVO LAYOUT K1:

  ┌── GAUGE + DIREZIONE ──────────────────────────────────────────────┐
  │  [Gauge -1 → +1]  COMPOSITE: +0.34 ▲ MODERATO                    │
  │  Regime: [BULL PILL]  Aggiornato: 14:32  Quality: 🟢 8/10 segnali │
  └───────────────────────────────────────────────────────────────────┘

  ┌── BREAKDOWN 7 COMPONENTI ─────────────────────────────────────────┐
  │  ChartFactory.signal_breakdown(signals_dict)                       │
  │  ← barre orizzontali colorate per valore, con IC accanto al nome  │
  │                                                                    │
  │  Technical   ████████░░  +0.42  IC: 0.08 🟢                       │
  │  Macro       ██████░░░░  +0.28  IC: 0.11 🟢                       │
  │  Labour      ████░░░░░░  +0.15  IC: 0.06 🟢                       │
  │  Sentiment   ██████████  +0.55  IC: 0.05 🟡                       │
  │  Valuation   ░░░░██░░░░  -0.20  IC: 0.09 🟢                       │
  │  Surprise    ████████░░  +0.35  IC: 0.07 🟢                       │
  │  Volatility  ████████░░  +0.32  IC: 0.12 🟢                       │
  └───────────────────────────────────────────────────────────────────┘

  ┌── QUALITY INDICATORS (Custom Indicators #7-10 da v5) ─────────────┐
  │  Signal Confidence:   [score 0.72/1.0]  8 segnali OK, 2 low_ic   │
  │  Regime Filter:       [composite filtrato: +0.29]  5/7 IC ok      │
  │  Consensus Validator: [3/7 concordano → RIALZISTA lieve]          │
  └───────────────────────────────────────────────────────────────────┘

  ┌── ANALISI DEL GIORNO ─────────────────────────────────────────────┐
  │  📝 Generata da: [Template fallback | Ollama mistral:7b-q4]        │
  │  "Il segnale composito è moderatamente rialzista grazie al         │
  │   contributo positivo di sentiment (+0.55) e volatility (+0.32)   │
  │   nonostante la valutazione sia elevata (-0.20)..."                │
  │  [Aggiorna] [Mostra dettagli]                                      │
  └───────────────────────────────────────────────────────────────────┘

  ┌── TREND 30G (sparkline) ──────────────────────────────────────────┐
  │  [ChartFactory.time_series composite_signal, 30gg, regime shading]│
  └───────────────────────────────────────────────────────────────────┘
```

**`ICBreakdownBar` component (specifico per K1):**
```python
@dataclass
class ICBreakdownBar(BaseComponent):
    """Barra breakdown con IC annotation per il Composite Signal."""
    signals: dict[str, tuple[float, float | None, str]]  # {name: (value, ic, quality_flag)}
    composite_value: float
    regime: str = "transition"

    def to_html(self) -> str:
        rows = [
            f'<tr><td>{name}</td><td>{val:+.3f}</td>'
            f'<td>{f"IC:{ic:.3f}" if ic else "—"}</td></tr>'
            for name, (val, ic, _) in self.signals.items()
        ]
        return f'<table>{"".join(rows)}</table>'

    def render(self) -> None:  # pragma: no cover
        import streamlit as st
        fig = ChartFactory.signal_breakdown(
            {name: (val, ic) for name, (val, ic, _) in self.signals.items()},
            regime=self.regime,
        )
        st.plotly_chart(fig, use_container_width=True)
```

**Definition of Done — Sessione 6:**
```
□ K1: gauge composite [-1,+1] visibile con regime label
□ K1: breakdown 7 componenti con IC + quality flag per ognuno
□ K1: quality indicators section (3 custom indicators da v5)
□ K1: box "Analisi del Giorno" con template fallback (LLM box pronto per Fase 7)
□ K1: trend 30gg con regime shading
□ ICBreakdownBar: to_html() testabile, 7 segnali corretti
□ K1 caricamento < 2s (tutti i segnali da SignalRegistry cached)
```

### Sessione 7 — M1-M6 Pages Standardization

Tutte le 6 pagine M* vengono portate allo stesso standard visivo:
- Header: `SectionHeader` con icona e timestamp aggiornamento
- Charts: `ChartFactory.time_series` con regime shading da DB
- KPI summary: `KpiCard` grid (2-3 card per pagina)
- Empty state: `EmptyState` se dati non disponibili

Pattern identico replicato su: M1 (Macro), M2 (VIX), M3 (Labour), M4 (Yield), M5 (Surprise), M6 (Valuation P/E)

**Definition of Done — Sessione 7:**
```
□ Tutte le 6 pagine M* usano ChartFactory.time_series (no px.line inline)
□ Regime shading presente su tutti i grafici time-series M*
□ SectionHeader con icon + timestamp su ogni pagina M*
□ EmptyState("Dati non disponibili") su tutte se DB vuoto
□ Nessuna pagina M* supera 150 righe
□ Pattern _load/_render implementato su M1 (le altre seguono lo stesso template)
```

---

## 🟠 BLOCCO D — Analytics & Quant (Sessioni 8–9)
> Priorità #3. Pagine computazionalmente pesanti — focus su performance + chart quality.

### Sessione 8 — Q1-Q8: Backtesting, Stress, Correlazioni base

**Pain point specifico:** pagine lente. Interventi di performance:
- `@st.cache_data(ttl=CACHE_TTL.BACKTESTING_RESULTS)` su tutte le funzioni di caricamento
- Lazy tab loading: backtest run solo su tab attivo
- Progress bar durante calcoli pesanti (VectorBT, stress scenarios)
- Grafici: `ChartFactory.time_series` + `ChartFactory.correlation_heatmap`

```python
# Pattern per pagine di calcolo pesante (Q1-Q8)
@page_layout(title="Backtesting", icon="ti-player-play")
def body_backtesting(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st
    tab_run, tab_results, tab_history = st.tabs(["Esegui", "Risultati", "Storico"])

    with tab_run:
        _render_backtest_form()   # Form parametri

    with tab_results:
        if SK.BACKTEST_RESULT in st.session_state:
            result = st.session_state[SK.BACKTEST_RESULT]
            _render_backtest_results(result, tokens)   # Charts + stats
        else:
            EmptyState("Nessun backtest eseguito",
                       hint="Configura i parametri e clicca 'Esegui'").render()

    with tab_history:
        history = _load_backtest_history()   # cached
        DataTable(history).render()
```

**Definition of Done — Sessione 8:**
```
□ Q1-Q8: ogni pagina < 200 righe
□ @st.cache_data presente su tutte le funzioni _load_*
□ EmptyState su tutti i tab risultati quando non ci sono dati
□ Nessun grafico inline (tutti via ChartFactory)
□ Progress bar durante i calcoli > 2s
□ Q3 Correlazioni: usa ChartFactory.correlation_heatmap (4 tab × 4 regimi)
```

### Sessione 9 — Q9-Q14: Strategy Lab, Custom Indicators, Options, MTF

- Q14 Strategy Lab: bottone "Walk-Forward" con progress bar + risultato in DataTable
- Q11 Options: Greeks table via DataTable + vol surface via ChartFactory
- Q12 Multi-Timeframe: confidence bar tramite SignalBadge per ogni timeframe
- C1 Custom Indicators: IC Dashboard tab con SignalBadge per ogni indicatore

**Definition of Done — Sessione 9:**
```
□ Q14: walk-forward progress bar funzionante
□ Q11: vol surface renderizzato da ChartFactory
□ C1: tab "Quality" con SignalBadge per ogni indicatore custom (IC visibile)
□ Tutte le Q/C pages: < 200 righe
□ ruff + mypy: 0 errori su tutti i file Q/C
```

---

## 🔴 BLOCCO E — Portfolio (Sessioni 10–11)
> Priorità #4. Pagine personali — focus su chiarezza dati e UX import.

### Sessione 10 — P1-P5: Overview, Posizioni, Import

**P2 (posizioni eToro) → rebuild più profondo:**
- Tabella posizioni: `DataTable` con sort/filter
- Import status: `StatusDot` per ogni sorgente (API eToro, XLSX)
- InstrumentRegistry widget (già pianificato in CODE_QUALITY, ora con styling component library)
- KpiCard grid (4 card: valore totale, P&L, allocazione, risk score)

```python
# P2 — pattern target (< 150 righe)
@page_layout(title="Portfolio eToro", icon="ti-briefcase")
def body_portafoglio_etoro(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st
    tab_overview, tab_positions, tab_import, tab_registry = st.tabs([
        "Panoramica", "Posizioni", "Import", "Gestione Ticker"
    ])
    with tab_overview:
        snap = _load_portfolio_snapshot()
        _render_portfolio_overview(snap, tokens)
    with tab_positions:
        positions = _load_positions()
        DataTable(positions, sortable=True, filterable=True).render()
    with tab_import:
        _render_import_section()
    with tab_registry:
        _render_instrument_registry()   # Da CODE_QUALITY §4.C, ora con DataTable
```

**Definition of Done — Sessione 10:**
```
□ P2: 4 tab operativi, ognuno < 50 righe
□ P2 Tab Posizioni: DataTable con sort su P&L%
□ P2 Tab Import: StatusDot per API + XLSX
□ P1 Overview: KpiCard grid con valore totale + P&L
□ Tutte le P1-P5: < 150 righe
□ Caricamento P2 < 2.5s (posizioni cached PORTFOLIO_TOTALS TTL)
```

### Sessione 11 — P6-P10 + Risk Profile + Goals

- P4 Profilo Investitore: form con slider + `KpiCard` per risk score
- P5 Risk Analysis: `ChartFactory.time_series` per VaR + stress exposure
- P10 Goals: progress bar via Streamlit native + KpiCard per ogni obiettivo

**Definition of Done — Sessione 11:**
```
□ P4: risk score aggiornato in tempo reale (slider → KpiCard)
□ P5: VaR chart con regime shading visibile
□ P10: progress bar verso ogni obiettivo visibile
□ Tutte P6-P10: < 150 righe
□ InvestorProfile sempre caricato prima di qualsiasi rendering (Rule 22)
```

---

## ⚪ BLOCCO F — Quality, Stubs, Documentation (Sessione 12)
> Chiusura roadmap. Stubs per ROADMAP_FINAL Fasi 6-8. UI test suite. Release v8.2.0.

### Stub Pages per ROADMAP_FINAL (componenti pronti, backend mock)

```python
# N1_News_Feed.py — STUB completo con component library
@page_layout(title="News Feed", icon="ti-news")
def body_news_feed(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st
    from presentation.ui.components.empty_state import EmptyState
    from presentation.ui.components.status_dot import StatusDot

    EmptyState(
        title="News Engine non ancora attivo",
        hint="Sarà disponibile con la Fase 6 (News Engine). "
             "I componenti UI sono pronti: attiva il feature flag 'news_engine_enabled'.",
        severity="info",
    ).render()

    # Preview dei componenti che verranno usati (con dati mock)
    if st.toggle("Mostra preview con dati demo"):
        _render_news_feed_demo(tokens)   # Mock data, componenti reali

# Identico pattern per N2_News_Analysis, M7_IB_Consensus, A1_Market_QA
```

### UI Test Suite

```
tests/ui/ (nuovo directory):
  test_components/
    test_kpi_card.py:        to_html() + 5 scenari valore + quality flags
    test_signal_badge.py:    5 direction levels + IC formatting
    test_chart_factory.py:   time_series, breakdown, heatmap, pie — Figure valide
    test_data_table.py:      DataTable su fixture DataFrame
    test_empty_state.py:     4 severity levels, to_html()
    test_ic_breakdown_bar.py: 7 segnali, composite corretto
  test_layout.py:            page_layout decorator + auth check
  test_sidebar_nav.py:       navigazione + ricerca fuzzy + stub badges
  test_chart_theme.py:       regime_shade, event_markers, get_base_layout
  test_design_tokens.py:     signal_color, regime_color, ic_color boundary
```

**Regola test UI:** ogni component testa `to_html()` senza mock Streamlit. Il `render()` è `pragma: no cover` — testato solo tramite `to_html()`.

### Definition of Done — Blocco F (= DoD del Progetto)

```
□ N1, N2, M7, A1: stub operative con EmptyState + preview demo
□ tests/ui/: ≥ 80 nuovi test, tutti verdi
□ Coverage engine/: invariata (≥ 95%)
□ Coverage presentation/ui/components/: ≥ 90%
□ mypy --strict: 0 errori su tutti i file nuovi
□ ruff: 0 warnings
□ Nessuna pagina > 200 righe (esclusi file test)
□ Ogni pagina rebuilt usa page_layout decorator
□ Nessun colore hardcoded nelle pagine (tutto via TOKENS.*)
□ Sidebar: ricerca fuzzy funzionante su tutti i 35+ voci
□ CHANGELOG.md: v8.1.0 → v8.2.0
□ docs/COMPONENTS.md: documentazione della component library
□ Totale test: ≥ 967 (887 esistenti + ~80 nuovi UI)
```

---

## ⚡ PERFORMANCE STRATEGY

**Pain point #3:** "Pagine lente o molti ricaricamenti"

### Interventi sistematici (implementati in ogni blocco):

```python
# 1. Lazy tab loading — nessuna query prima che il tab sia aperto
def _render_tabs_lazy(tabs_data: dict[str, callable]) -> None:  # pragma: no cover
    import streamlit as st
    tabs = st.tabs(list(tabs_data.keys()))
    for tab, loader in zip(tabs, tabs_data.values()):
        with tab:
            loader()   # Solo questo tab esegue la query

# 2. Progressive loading — mostra scheletro mentre carica
@st.cache_data(ttl=CACHE_TTL.MARKET_KPI, show_spinner="Caricamento dati...")
def _load_market_kpis() -> list[KpiData]: ...

# 3. Background preload — dati critici pre-caricati dallo scheduler
# Scheduler job: ogni 55s → LiveMarketService.refresh_now() → cache warm

# 4. Fragment refresh — solo le sezioni che cambiano si ricaricano
@st.fragment(run_every="60s")
def _live_kpi_section() -> None:  # pragma: no cover
    """Aggiorna solo i KPI ogni 60s senza ricaricare la pagina intera."""
    kpis = _load_market_kpis()
    for kpi in kpis:
        KpiCard(**kpi.__dict__).render()
```

### Target di performance per pagina:

| Pagina | Target attuale | Target v8.2.0 |
|---|---|---|
| K1 Composite Signal | ~4s | < 2s (SignalRegistry cache) |
| E1 Market Overview | ~3s | < 2s (LiveMarketService cache) |
| P2 Posizioni eToro | ~5s | < 2.5s (lazy tabs) |
| Q3 Correlazioni | ~8s | < 3s (BACKTESTING_RESULTS cache) |
| S0 Health | ~2s | < 1s (status cached 30s) |
| S2 Settings | ~1s | < 1s (YAML read only) |

---

## 🧪 UI TEST STRATEGY

**Pattern per componenti testabili senza Streamlit:**

```python
# test_kpi_card.py
class TestKpiCard:
    def test_format_large_number(self):
        card = KpiCard("Test", 1_234_567.0, unit="€")
        assert "1.2M" in card.to_html()

    def test_format_thousands(self):
        card = KpiCard("Test", 4_523.0)
        assert "4,523" in card.to_html()

    def test_quality_flag_ok_shows_full_dot(self):
        card = KpiCard("Test", 1.0, quality_flag="ok")
        assert "●" in card.to_html()

    def test_quality_flag_low_ic_shows_half_dot(self):
        card = KpiCard("Test", 1.0, quality_flag="low_ic")
        assert "◐" in card.to_html()

    def test_positive_delta_in_html(self):
        card = KpiCard("Test", 100.0, delta=2.5)
        assert "+2.5%" in card.to_html()

class TestSignalBadge:
    @pytest.mark.parametrize("value,expected", [
        (0.8, "RIALZISTA"), (0.2, "lieve ↑"), (0.0, "NEUTRO"),
        (-0.2, "lieve ↓"), (-0.8, "RIBASSISTA"),
    ])
    def test_direction_thresholds(self, value, expected):
        badge = SignalBadge("test", value)
        assert badge.direction == expected

    def test_ic_in_html_when_present(self):
        badge = SignalBadge("test", 0.5, ic_estimate=0.08)
        assert "IC:0.080" in badge.to_html()

class TestChartFactory:
    def test_time_series_returns_figure(self, sample_ohlcv_df):
        fig = ChartFactory.time_series(sample_ohlcv_df, "date", "close")
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1

    def test_signal_breakdown_has_correct_bar_count(self):
        signals = {f"sig_{i}": (0.3 * i - 1.0, 0.05) for i in range(7)}
        fig = ChartFactory.signal_breakdown(signals)
        assert len(fig.data[0]["y"]) == 7
```

---

## 📅 TIMELINE — 12 SESSIONI

```
Sessione  1 → Blocco A: DesignTokens + layout.py + sidebar_nav.py + chart_theme.py
Sessione  2 → Blocco A: Component library core (KpiCard, SignalBadge, ChartFactory,
                         EmptyState, DataTable, StatusDot, RegimePill, ICBreakdownBar)
──────────────────────────────────────────────────────────────────────────────────
GO/NO-GO A: 887 test ✓ + mypy 0 err ✓ + component tests verdi ✓
──────────────────────────────────────────────────────────────────────────────────
Sessione  3 → Blocco B: S0 Health rebuild (7 tab) con Signal Bus + LLM + News status
Sessione  4 → Blocco B: S2 Settings rebuild (7 sezioni FINAL Phase 10)
──────────────────────────────────────────────────────────────────────────────────
GO/NO-GO B: S0 < 1s ✓ · S2 modifica YAML funzionante ✓ · LLM section ok ✓
──────────────────────────────────────────────────────────────────────────────────
Sessione  5 → Blocco C: E1 Market Overview rebuild (KpiCard grid, lazy tabs)
Sessione  6 → Blocco C: K1 Composite Signal rebuild (Signal Bus, IC, LLM box)
Sessione  7 → Blocco C: M1-M6 pages standardization (chart theme, regime shading)
──────────────────────────────────────────────────────────────────────────────────
GO/NO-GO C: K1 breakdown 7+3 componenti ✓ · E1 < 2s ✓ · regime shading visibile ✓
──────────────────────────────────────────────────────────────────────────────────
Sessione  8 → Blocco D: Q1-Q8 (backtesting, stress, correlazioni — performance + charts)
Sessione  9 → Blocco D: Q9-Q14 (strategy lab, options, MTF, custom indicators)
──────────────────────────────────────────────────────────────────────────────────
GO/NO-GO D: Q3 correlazioni < 3s ✓ · nessuna Q page > 200 righe ✓
──────────────────────────────────────────────────────────────────────────────────
Sessione 10 → Blocco E: P1-P5 (overview, posizioni, import — DataTable, KpiCard)
Sessione 11 → Blocco E: P6-P10 (risk profile, goals — form + KpiCard)
──────────────────────────────────────────────────────────────────────────────────
GO/NO-GO E: P2 < 2.5s ✓ · DataTable sort/filter funzionante ✓
──────────────────────────────────────────────────────────────────────────────────
Sessione 12 → Blocco F: UI test suite + stubs N1/N2/M7/A1 + docs + v8.2.0
──────────────────────────────────────────────────────────────────────────────────
RELEASE: v8.2.0 — Component Library · Design System · UI rebuilt
TOTALE: 12 sessioni · ~80 test nuovi · ≥ 967 test totali
```

---

## 📊 METRICHE DI SUCCESSO — v8.2.0

| Metrica | Baseline v8.1.0 | Target v8.2.0 |
|---|---|---|
| Test totali | 887 | ≥ 967 (+80 UI tests) |
| Coverage presentation/ui/components/ | 0% | ≥ 90% |
| Coverage globale | ≥ 95% | ≥ 95% (invariata) |
| mypy errors | 0 | 0 (invariato) |
| Pagine > 200 righe | 15+ | 0 |
| Colori hardcoded nelle pagine | 30+ | 0 (tutti TOKENS.*) |
| Pagine senza EmptyState | 20+ | 0 |
| Componenti condivisi (component library) | 0 | 13 |
| E1 caricamento | ~3s | < 2s |
| K1 caricamento | ~4s | < 2s |
| P2 caricamento | ~5s | < 2.5s |
| Navigazione sidebar | Piatta, 35 voci | Gerarchica, ricercabile |
| K1 breakdown Signal Bus | Non presente | 7+3 componenti con IC |
| LLM box in K1 | Non presente | Box pronto (template o Ollama) |
| Stubs N1/N2/M7/A1 | Assenti | Presenti con preview demo |
| Pagine con regime shading | 0 | ≥ 12 (tutti i time-series) |

---

## ⚠️ RISCHI

| # | Rischio | Prob | Impatto | Mitigazione |
|---|---|---|---|---|
| R1 | Split pagine introduce import circolari | Media | Alto | Test import immediato dopo ogni split; facade backward-compatible |
| R2 | st.fragment() non disponibile in versione Streamlit usata | Media | Medio | Feature flag `enable_fragment_refresh`; fallback a @st.cache_data TTL |
| R3 | ChartFactory troppo rigida per casi edge nei grafici | Alta | Basso | Metodo `custom()` su ChartFactory per override; non forza il factory su tutto |
| R4 | K1 Signal Bus integration richiede Fase 5 (v5_IMPROVED) completata | Alta | Medio | K1 mostra placeholder se Signal Bus non attivo; componentizzato per upgrade |
| R5 | Sidebar navigation incompatibile con st.pages structure attuale | Media | Medio | Test in staging; rollback sidebar.py se necessario |
| R6 | Coverage components < 90% per Streamlit render() | Bassa | Basso | to_html() sempre implementato; render() è pragma no cover per design |

---

## 📌 PROMPT PROSSIMA SESSIONE

```
Continuo lo sviluppo di MarketAI Professional Edition.
Stato: v8.1.0 (887 test, ≥ 95% coverage)
CODE_QUALITY v1.0 completata (SK.*, CACHE_TTL.*, OP_CONFIG.*, CurrencyConverter, ErrorPolicy, splits)

Roadmap attiva: ROADMAP_REFACTORING_UI_v1_0.md
Approccio: Aggressivo · 12 sessioni · Component Library completa

PROSSIMO TASK: Blocco A — Sessione 1
  1. presentation/ui/design_tokens.py: estendere con signal_color(), regime_color(), ic_color()
  2. presentation/ui/layout.py: page_layout() decorator con auth + error boundary
  3. presentation/ui/chart_theme.py: get_base_layout() + regime_shade() + event_markers()
  4. presentation/ui/sidebar_nav.py: SidebarNavigator con 5 gruppi + ricerca
  5. Test: test_design_tokens.py (signal_color boundaries) + test_sidebar_nav.py

Vincoli: zero regressioni · zero colori hardcoded · 887 test devono continuare a passare
Cartella progetto: C:\Users\Q256254\Documents\market-ai\MarketAI 1.0
```

---

*MarketAI — Roadmap Refactoring & UI v1.0*
*Approccio Aggressivo · Calibrata su questionario · Parte da CODE_QUALITY v1.0 (v8.1.0)*
*Integra ROADMAP_FINAL_v1_0_IMPROVED (Fasi 5-11) e ROADMAP_v5_IMPROVED (Signal Bus)*
*12 sessioni · 6 blocchi · ~80 test UI nuovi · Target: v8.2.0*
*Segue 32 Convenzioni ROADMAP v6.0 obbligatorie*
*⚠️ Disclaimer: Software a scopo informativo. Non costituisce consulenza finanziaria.*
