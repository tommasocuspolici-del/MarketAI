# ruff: noqa: N999
"""K1 — Composite Signal Dashboard (v8.2.0).

La pagina più importante analiticamente. Mostra:
  1. Gauge composito [-1, +1] + direzione + regime pill
  2. Breakdown 7 componenti con IC e quality flag (ICBreakdownBar)
  3. Quality indicators: SignalConfidenceTracker + ConsensusValidator
  4. Analisi del Giorno (template deterministico | Ollama se attivo)
  5. Trend 30 giorni con regime shading (ChartFactory)

Design: _load_*() puri e testabili · _render_*() pragma: no cover.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pandas as pd

from presentation.ui.components import EmptyState, ICBreakdownBar, KpiCard, SignalBadge
from presentation.ui.layout import setup_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "8.2.0"
__all__ = ["body_k1_composite"]

# Signal name → display label mapping (7 components)
_COMPONENT_LABELS: dict[str, str] = {
    "technical_composite":    "Technical",
    "macro_conviction":       "Macro",
    "labour_regime_signal":   "Labour",
    "sentiment_composite":    "Sentiment",
    "valuation_signal":       "Valuation",
    "economic_surprise_index": "Surprise",
    "vix_signal":             "Volatility",
}


# ─────────────────────────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ComponentRow:
    name: str
    label: str
    value: float
    ic_estimate: float | None
    quality_flag: str


@dataclass
class CompositeSnapshot:
    """Full snapshot of the composite signal and its components."""
    composite_value: float
    regime: str
    components: list[ComponentRow] = field(default_factory=list)
    n_signals_ok: int = 0
    n_signals_total: int = 0
    confidence_score: float = 0.0
    consensus_direction: str = "NEUTRO"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def direction_label(self) -> str:
        v = self.composite_value
        if v > 0.5:   return "FORTEMENTE RIALZISTA"
        if v > 0.2:   return "MODERATAMENTE RIALZISTA"
        if v > 0.05:  return "LIEVEMENTE RIALZISTA"
        if v > -0.05: return "NEUTRO"
        if v > -0.2:  return "LIEVEMENTE RIBASSISTA"
        if v > -0.5:  return "MODERATAMENTE RIBASSISTA"
        return "FORTEMENTE RIBASSISTA"


# ─────────────────────────────────────────────────────────────────────────────
# Data loaders — pure, testable without Streamlit
# ─────────────────────────────────────────────────────────────────────────────

def _load_composite_snapshot() -> CompositeSnapshot:
    """Load composite signal + component breakdown from SignalRegistry.

    Returns CompositeSnapshot with composite_value=0.0 (neutral) if the
    registry has no signals yet — never raises.
    """
    from shared.signal_registry import get_signal_registry
    from shared.alpha_decay_monitor import AlphaDecayMonitor

    registry = get_signal_registry()
    monitor = AlphaDecayMonitor()
    stale_set = set(registry.stale_signals())

    components: list[ComponentRow] = []
    values_for_composite: list[float] = []

    for sig_name, label in _COMPONENT_LABELS.items():
        sig = registry.get(sig_name)
        if sig is None:
            continue
        is_stale = sig_name in stale_set
        try:
            ic, flag = monitor.check_decay(sig_name)
        except Exception:
            ic, flag = None, "insufficient_data"
        if is_stale:
            flag = "stale"

        components.append(ComponentRow(
            name=sig_name, label=label,
            value=sig.value, ic_estimate=ic, quality_flag=flag,
        ))
        if not is_stale:
            values_for_composite.append(sig.value)

    composite_value = float(sum(values_for_composite) / len(values_for_composite)) if values_for_composite else 0.0
    composite_value = max(-1.0, min(1.0, composite_value))

    # Quality metrics
    n_ok = sum(1 for c in components if c.quality_flag == "ok")
    n_total = len(components)

    # Confidence score from custom indicator
    confidence = 0.0
    try:
        from custom_indicators.library.signal_confidence_tracker import SignalConfidenceTracker
        snap = SignalConfidenceTracker(monitor).compute()
        confidence = snap.overall_score
    except Exception:
        confidence = n_ok / n_total if n_total > 0 else 0.0

    # Consensus direction
    consensus = "NEUTRO"
    try:
        from custom_indicators.library.consensus_signal_validator import ConsensusSignalValidator
        vals = {c.label: c.value for c in components}
        result = ConsensusSignalValidator().compute(vals)
        consensus = result.consensus_direction if hasattr(result, "consensus_direction") else "NEUTRO"
    except Exception:
        bullish = sum(1 for c in components if c.value > 0.05)
        bearish = sum(1 for c in components if c.value < -0.05)
        if bullish > bearish and bullish >= 3:
            consensus = "RIALZISTA"
        elif bearish > bullish and bearish >= 3:
            consensus = "RIBASSISTA"

    # Derive regime from VIX if available
    from presentation.dashboard_engine.pages.E1_Market_Overview import _derive_regime
    vix_component = next((c for c in components if c.name == "vix_signal"), None)
    vix_hint = None
    if vix_component:
        vix_hint = vix_component.value * -30 + 20   # rough back-transform vix_signal → VIX level
    regime = _derive_regime(vix_hint) if vix_hint else "transition"

    return CompositeSnapshot(
        composite_value=composite_value,
        regime=regime,
        components=components,
        n_signals_ok=n_ok,
        n_signals_total=n_total,
        confidence_score=confidence,
        consensus_direction=consensus,
    )


def _build_narrative_template(snap: CompositeSnapshot) -> str:
    """Generate a deterministic narrative description of the composite signal.

    This is the fallback when Ollama is not active. Pure function — testable.
    """
    direction = snap.direction_label
    cv = snap.composite_value

    strongest = max(snap.components, key=lambda c: abs(c.value), default=None)
    weakest   = min(snap.components, key=lambda c: c.value, default=None)

    top_pos = sorted(snap.components, key=lambda c: c.value, reverse=True)[:2]
    top_neg = sorted(snap.components, key=lambda c: c.value)[:2]

    pos_str = " e ".join(f"{c.label} ({c.value:+.2f})" for c in top_pos if c.value > 0)
    neg_str = " e ".join(f"{c.label} ({c.value:+.2f})" for c in top_neg if c.value < 0)

    parts = [
        f"Il segnale composito è {direction.lower()} con valore {cv:+.3f}.",
    ]
    if pos_str:
        parts.append(f"I contributi positivi principali provengono da {pos_str}.")
    if neg_str:
        parts.append(f"I contributi negativi principali provengono da {neg_str}.")
    parts.append(
        f"Qualità del sistema: {snap.n_signals_ok}/{snap.n_signals_total} segnali OK "
        f"(confidence score: {snap.confidence_score:.0%})."
    )
    parts.append(f"Consensus: {snap.consensus_direction}.")

    return " ".join(parts)


def _load_composite_history(days: int = 30) -> pd.DataFrame:
    """Load composite signal history from DuckDB signal_snapshots table.

    Returns DataFrame with columns [date, value] or empty DataFrame.
    """
    try:
        from shared.db.duckdb_client import DuckDBClient
        client = DuckDBClient()
        sql = """
            SELECT ts AS date, value
            FROM signal_snapshots
            WHERE signal_name = 'composite_signal'
              AND ts >= now() - INTERVAL ? DAYS
            ORDER BY ts
        """
        df = client.query(sql, [days])
        if df is None or df.empty:
            return pd.DataFrame(columns=["date", "value"])
        return df[["date", "value"]].reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=["date", "value"])


# ─────────────────────────────────────────────────────────────────────────────
# Renderers — pragma: no cover
# ─────────────────────────────────────────────────────────────────────────────

def _render_gauge(st, snap: CompositeSnapshot, tokens: DesignTokens) -> None:  # pragma: no cover
    """Top section: composite value + direction + regime pill."""
    import plotly.graph_objects as go

    regime_color = tokens.colors.regime_color(snap.regime)
    signal_color = tokens.colors.signal_color(snap.composite_value)

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=snap.composite_value,
        number={"font": {"color": signal_color, "size": 36}, "suffix": ""},
        delta={"reference": 0, "relative": False, "valueformat": "+.3f"},
        gauge={
            "axis": {"range": [-1, 1], "tickwidth": 1, "tickcolor": tokens.colors.text_muted},
            "bar":  {"color": signal_color, "thickness": 0.25},
            "steps": [
                {"range": [-1, -0.5], "color": tokens.colors.signal_strong_bear},
                {"range": [-0.5, -0.1], "color": tokens.colors.signal_bear},
                {"range": [-0.1, 0.1],  "color": tokens.colors.signal_neutral},
                {"range": [0.1, 0.5],   "color": tokens.colors.signal_bull},
                {"range": [0.5, 1],     "color": tokens.colors.signal_strong_bull},
            ],
            "threshold": {"line": {"color": "white", "width": 4}, "value": snap.composite_value},
        },
        title={"text": f"Composite Signal<br><sup>{snap.direction_label}</sup>"},
    ))
    fig.update_layout(
        height=250, margin=dict(t=60, b=20, l=30, r=30),
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        font=dict(color=tokens.colors.text_primary),
    )
    st.plotly_chart(fig, use_container_width=True)

    cols = st.columns(3)
    with cols[0]:
        st.markdown(
            f'**Regime:** <span style="color:{regime_color};font-weight:600">'
            f'{snap.regime.upper()}</span>',
            unsafe_allow_html=True,
        )
    with cols[1]:
        quality_icon = "🟢" if snap.confidence_score > 0.7 else ("🟡" if snap.confidence_score > 0.4 else "🔴")
        st.markdown(f"**Qualità:** {quality_icon} {snap.n_signals_ok}/{snap.n_signals_total} segnali OK")
    with cols[2]:
        ts_str = snap.timestamp.strftime("%H:%M")
        st.caption(f"Aggiornato: {ts_str}")


def _render_breakdown(st, snap: CompositeSnapshot) -> None:  # pragma: no cover
    """Section 2: ICBreakdownBar with 7 components."""
    signals = {c.label: (c.value, c.ic_estimate, c.quality_flag) for c in snap.components}
    ICBreakdownBar(signals=signals, composite_value=snap.composite_value, regime=snap.regime).render()


def _render_quality_indicators(st, snap: CompositeSnapshot) -> None:  # pragma: no cover
    """Section 3: Quality indicators (3 custom indicators)."""
    st.markdown("#### Quality Indicators")
    cols = st.columns(3)

    with cols[0]:
        score = snap.confidence_score
        icon = "🟢" if score > 0.7 else ("🟡" if score > 0.4 else "🔴")
        KpiCard("Signal Confidence", f"{score:.0%}", quality_flag="ok" if score > 0.7 else "low_ic").render()
        st.caption(f"{icon} {snap.n_signals_ok} ok · {snap.n_signals_total - snap.n_signals_ok} degradati")

    with cols[1]:
        KpiCard("Regime Filter", snap.regime.upper()).render()
        st.caption("Pesi adattati al regime corrente")

    with cols[2]:
        KpiCard("Consensus", snap.consensus_direction).render()
        bullish = sum(1 for c in snap.components if c.value > 0.05)
        bearish = sum(1 for c in snap.components if c.value < -0.05)
        st.caption(f"{bullish}↑ rialzisti · {bearish}↓ ribassisti")


def _render_narrative(st, snap: CompositeSnapshot) -> None:  # pragma: no cover
    """Section 4: Analisi del Giorno."""
    st.markdown("#### 📝 Analisi del Giorno")

    # Try Ollama first
    narrative = None
    source = "template"

    try:
        from shared.feature_flags import is_enabled
        if is_enabled("llm_engine_enabled") and is_enabled("llm_narrative_generator"):
            import urllib.request, json
            prompt = (
                f"Analisi mercato breve (max 3 frasi) in italiano. "
                f"Segnale composito: {snap.composite_value:+.3f} ({snap.direction_label}). "
                f"Regime: {snap.regime}. Confidence: {snap.confidence_score:.0%}."
            )
            payload = json.dumps({
                "model": "mistral:7b-q4",
                "prompt": prompt,
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/generate", data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
                narrative = result.get("response", "").strip()
                source = "Ollama mistral:7b-q4"
    except Exception:
        pass

    if not narrative:
        narrative = _build_narrative_template(snap)

    st.caption(f"Generata da: {source}")
    st.info(narrative)

    with st.expander("Dettaglio componenti", expanded=False):
        for comp in sorted(snap.components, key=lambda c: abs(c.value), reverse=True):
            SignalBadge(
                name=comp.label, value=comp.value,
                ic_estimate=comp.ic_estimate, quality_flag=comp.quality_flag,
            ).render()


def _render_trend(st, tokens: DesignTokens) -> None:  # pragma: no cover
    """Section 5: Composite signal 30-day trend."""
    from presentation.ui.chart_theme import ChartFactory

    df = _load_composite_history(days=30)
    if df.empty:
        EmptyState(
            "Storico composito non disponibile",
            hint="Il trend si popola dopo che il pipeline analitico ha girato almeno 2 volte.",
            severity="info",
        ).render()
        return

    fig = ChartFactory.time_series(
        df, x_col="date", y_col="value",
        title="Composite Signal — Trend 30 giorni",
        color=tokens.colors.chart_primary,
    )
    st.plotly_chart(fig, use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def body_k1_composite(tokens: DesignTokens) -> None:  # pragma: no cover
    """K1 Composite Signal — orchestrator < 30 righe."""
    import streamlit as st

    h_col, r_col = st.columns([5, 1])
    with h_col:
        st.markdown("## 🎯 Composite Signal")
    with r_col:
        if st.button("🔄 Aggiorna", key="k1_refresh"):
            st.cache_data.clear()
            st.rerun()

    snap = _load_composite_snapshot()

    if snap.n_signals_total == 0:
        EmptyState(
            "Nessun segnale disponibile",
            hint="Avvia il pipeline analitico per calcolare i segnali componenti.",
            severity="warning",
        ).render()
        return

    _render_gauge(st, snap, tokens)
    st.divider()
    _render_breakdown(st, snap)
    st.divider()
    _render_quality_indicators(st, snap)
    st.divider()
    _render_narrative(st, snap)
    st.divider()
    _render_trend(st, tokens)


if __name__ == "__main__":  # pragma: no cover
    tokens = setup_page("K1 Composite Signal", icon="🎯")
    body_k1_composite(tokens)
