# MarketAI — Component Library Reference

**v8.2.0** · `presentation/ui/components/`

All components extend `BaseComponent` (ABC). The `to_html()` method is pure and testable without Streamlit. The `render()` method is `# pragma: no cover` and calls Streamlit internals.

---

## BaseComponent

```python
from presentation.ui.components.base import BaseComponent

class MyComponent(BaseComponent):
    def to_html(self) -> str: ...
    def render(self) -> None: ...  # pragma: no cover
```

---

## KpiCard

Displays a metric with optional delta and quality indicator.

```python
from presentation.ui.components.kpi_card import KpiCard

card = KpiCard(
    title="Sharpe Ratio",
    value=1.42,
    unit="",
    delta=0.15,          # optional — shown as +0.15
    delta_label="vs 1y", # optional suffix for delta
    quality_flag="ok",   # "ok" | "low_ic" | "insufficient_data"
    icon="📊",           # optional emoji prefix
    tooltip="Risk-adjusted return",
)
card.render()            # Streamlit st.metric
html = card.to_html()   # pure HTML for testing
```

**Quality dots:** `●` (ok) · `◐` (low_ic) · `○` (insufficient_data) · `◌` (unknown)

---

## SignalBadge

Displays a signal value ∈ [-1, 1] with direction label and color.

```python
from presentation.ui.components.signal_badge import SignalBadge

badge = SignalBadge(
    name="Technical Composite",
    value=0.42,
    confidence=0.85,      # [0,1]
    ic_estimate=0.072,    # Information Coefficient, optional
    quality_flag="ok",    # "ok" | "low_ic" | "insufficient_data"
)
badge.render()
```

**Direction thresholds (strict):**
| Range | Label |
|-------|-------|
| v > 0.3 | RIALZISTA |
| v > 0.05 | lieve ↑ |
| v > -0.05 | NEUTRO |
| v > -0.3 | lieve ↓ |
| else | RIBASSISTA |

**Colors:** mapped via `TOKENS.colors.signal_color(value)` — never hardcoded.

---

## EmptyState

Consistent empty/loading/error placeholder.

```python
from presentation.ui.components.empty_state import EmptyState

EmptyState(
    title="Nessun dato disponibile",
    hint="Esegui il job scheduler per popolare il DB.",
    severity="info",   # "info" | "warning" | "error" | "loading"
    icon="⏳",         # optional override
).render()
```

**Severity mapping:** `info` → `st.info` · `warning` → `st.warning` · `error` → `st.error` · `loading` → `st.info` with ⏳

---

## StatusDot

System status indicator for data sources, APIs, services.

```python
from presentation.ui.components.status_dot import StatusDot

StatusDot(
    label="FRED API",
    status="ok",              # "ok" | "degraded" | "error" | "unknown"
    detail="Connected, 120ms latency",
    last_update="2026-05-21 10:00",
).render()
```

**Dots:** 🟢 ok · 🟡 degraded · 🔴 error · ⚪ unknown

---

## SectionHeader

Consistent page section header with optional subtitle.

```python
from presentation.ui.components.section_header import SectionHeader

SectionHeader(
    title="Composite Signal",
    icon="📊",
    subtitle="Basato su 7 componenti, aggiornato ogni ora",
    ttl=3600,  # optional cache TTL display
).render()
```

---

## ICBreakdownBar

Per-signal IC table for K1 Composite Signal and C1 Custom Indicators.

```python
from presentation.ui.components.ic_breakdown_bar import ICBreakdownBar

signals = {
    "technical_composite": (0.42, 0.08, "ok"),       # (value, ic_estimate, quality_flag)
    "macro_conviction":    (-0.15, 0.05, "ok"),
    "vix_signal":          (0.60, None,  "insufficient_data"),
}
bar = ICBreakdownBar(
    signals=signals,
    composite_value=0.31,
    regime="transition",
)
bar.render()
html = bar.to_html()  # table with per-signal bars
```

---

## ChartFactory

Static factory for all Plotly charts. **Never use `px.line` or `go.Figure()` inline in pages.**

```python
from presentation.ui.chart_theme import ChartFactory, regime_shade, event_markers

# Time series
fig = ChartFactory.time_series(df, x_col="date", y_col="value", title="S&P 500 12M")

# Signal breakdown (horizontal bars)
fig = ChartFactory.signal_breakdown(
    signals={"macro": (0.4, 0.07), "vix": (-0.3, 0.05)},  # (value, ic)
    regime="bull",
)

# Correlation heatmap
fig = ChartFactory.correlation_heatmap(corr_df)  # DataFrame with asset names as index/columns

# Pie chart
fig = ChartFactory.pie_allocation(labels=["SPY", "TLT", "GLD"], values=[0.6, 0.3, 0.1])

# Overlays
fig = regime_shade(fig, regime_df, date_col="date", regime_col="regime")
fig = event_markers(fig, [{"date": "2026-01-15", "label": "FED", "color": "blue"}])
```

---

## Design Tokens

All colors, typography, spacing come from `TOKENS`. **No hardcoded values in pages.**

```python
from presentation.ui.design_tokens import TOKENS

# Color helpers
TOKENS.colors.signal_color(0.42)          # → "#5cba86" (bull)
TOKENS.colors.regime_color("stress")       # → "#a32d2d"
TOKENS.colors.ic_color(0.02, "low_ic")    # → "#ba7517"

# Direct token access
TOKENS.colors.accent_primary             # brand primary
TOKENS.colors.bg_secondary              # chart background
TOKENS.typography.font_main             # system font stack
TOKENS.spacing.section_gap             # px between sections
```

**Signal color thresholds:**
| Value | Color token |
|-------|-------------|
| v > 0.5 | `signal_strong_bull` (#2d7a4f) |
| v > 0.1 | `signal_bull` (#5cba86) |
| v > -0.1 | `signal_neutral` (#888780) |
| v > -0.5 | `signal_bear` (#d85a30) |
| else | `signal_strong_bear` (#a32d2d) |

---

## EmptyState Usage Pattern

Every page tab that can have no data must use `EmptyState`:

```python
from presentation.ui.components import EmptyState

def _render_results_tab(st, tokens):
    data = _load_data()
    if not data:
        EmptyState(
            "Nessun risultato",
            hint="Configura i parametri e clicca 'Esegui'.",
        ).render()
        return
    # ... render actual content
```

---

## Page Pattern

Every page follows this structure:

```python
# ruff: noqa: N999
from __future__ import annotations
from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

def _load_data(...) -> ...:      # pure, testable, no Streamlit
    try:
        ...
    except Exception:
        return fallback

def body_page(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st
    # refresh button (mandatory)
    cols = st.columns([4, 1])
    with cols[1]:
        if st.button("🔄 Aggiorna", key="px_refresh"):
            st.cache_data.clear()
            st.rerun()
    # tabs
    tab1, tab2 = st.tabs(["Tab A", "Tab B"])
    with tab1:
        @st.cache_data(ttl=CACHE_TTL.BACKTESTING)
        def _cached(): return _load_data()
        data = _cached()
        if not data:
            EmptyState("Nessun dato").render()
        else:
            ...

if __name__ == "__main__":  # pragma: no cover
    render_page("Page Title", "📊", body_page)
```

---

## Naming Conventions

| Pattern | Purpose |
|---------|---------|
| `_load_*(...)` | Pure functions — testable, no Streamlit, return data or empty fallback |
| `_render_*(st, ...)` | Streamlit renderers — `# pragma: no cover` |
| `body_*(tokens)` | Page entry point — `# pragma: no cover` |
| `SK.*` | Session state keys — never use string literals |
| `CACHE_TTL.*` | Cache TTLs — never use numeric literals |
