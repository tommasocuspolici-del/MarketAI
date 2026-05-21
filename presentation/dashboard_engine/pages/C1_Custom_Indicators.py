# ruff: noqa: N999
"""C1 — Custom Indicators (Blocco D).

3 tab: Libreria · DSL Editor · Quality (SignalBadge per IC per indicatore).
Pattern: _load_*() pure + body_custom_indicators() Streamlit.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState, SignalBadge
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_custom_indicators"]


def _load_indicator_list() -> list[dict]:
    """Carica tutti gli indicatori dalla registry (YAML + runtime)."""
    try:
        from custom_indicators.registry import get_indicator_registry
        registry = get_indicator_registry()
        return [
            {
                "id":          d.id,
                "name":        d.name,
                "active":      d.active,
                "output_type": d.output_type,
                "type":        "library" if d.library_class else "dsl",
                "description": d.description,
            }
            for d in registry.list_all()
        ]
    except Exception:
        return []


def _load_ic_scores() -> dict[str, float | None]:
    """Carica IC stimato per ogni indicatore da AlphaDecayMonitor."""
    try:
        from shared.alpha_decay_monitor import AlphaDecayMonitor
        monitor = AlphaDecayMonitor()
        indicators = _load_indicator_list()
        scores: dict[str, float | None] = {}
        for ind in indicators:
            state = monitor.get_state(ind["id"])
            scores[ind["id"]] = state.ic_estimate if state else None
        return scores
    except Exception:
        return {}


def _validate_dsl_expression(expression: str) -> tuple[bool, str]:
    """Valida una espressione DSL. Ritorna (ok, messaggio)."""
    try:
        from custom_indicators.dsl.validator import DSLValidator
        validator = DSLValidator()
        ok = validator.validate(expression)
        return ok, "✅ Espressione valida" if ok else "❌ Sintassi non valida"
    except ImportError:
        from custom_indicators.dsl.evaluator import DSLEvaluator
        ok = DSLEvaluator().is_safe(expression)
        return ok, "✅ Espressione sicura" if ok else "❌ Espressione non sicura"
    except Exception as exc:
        return False, f"❌ Errore validazione: {exc}"


def body_custom_indicators(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    render_section_header("🔧 Custom Indicators", "Libreria pre-built · DSL Editor · IC Quality Dashboard")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="c1_refresh"):
            st.cache_data.clear()
            st.rerun()

    tab_library, tab_dsl, tab_quality = st.tabs(["📚 Libreria", "✏️ DSL Editor", "📊 Quality (IC)"])

    with tab_library:
        _render_library_tab(st, tokens)

    with tab_dsl:
        _render_dsl_tab(st, tokens)

    with tab_quality:
        _render_quality_tab(st, tokens)


def _render_library_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    import pandas as pd

    @st.cache_data(ttl=CACHE_TTL.STATIC)
    def _cached() -> list[dict]:
        return _load_indicator_list()

    indicators = _cached()

    if not indicators:
        EmptyState(
            "Nessun indicatore registrato",
            hint="Aggiungi indicatori in config/custom_indicators.yaml o registrali via codice.",
        ).render()
        return

    render_section_header(f"Indicatori registrati ({len(indicators)})")

    filter_type = st.selectbox("Filtro tipo", ["Tutti", "library", "dsl"], key="c1_filter")
    filtered = [i for i in indicators if filter_type == "Tutti" or i["type"] == filter_type]

    df = pd.DataFrame(filtered)[["name", "id", "type", "active", "output_type", "description"]]
    df.columns = ["Nome", "ID", "Tipo", "Attivo", "Output", "Descrizione"]
    st.dataframe(df, use_container_width=True, hide_index=True)


def _render_dsl_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    render_section_header("✏️ DSL Editor")
    st.info(
        "Il DSL permette di definire segnali custom con espressioni matematiche sicure. "
        "Usa variabili di contesto come `vix`, `macro_conviction`, `sentiment_score`."
    )

    expression = st.text_area(
        "Espressione DSL",
        value="vix > 25 and macro_conviction < -0.2",
        height=100,
        key="c1_dsl_expr",
        help="Espressione booleana o float. Es: (macro_conviction + sentiment_score) / 2",
    )

    if st.button("✅ Valida", key="c1_validate"):
        ok, msg = _validate_dsl_expression(expression)
        if ok:
            st.success(msg)
        else:
            st.error(msg)

    st.caption("Variabili disponibili: `vix`, `macro_conviction`, `sentiment_score`, `labour_signal`, "
               "`yield_spread`, `cape_ratio`, `correlation_signal`")


def _render_quality_tab(st, tokens: DesignTokens) -> None:  # pragma: no cover
    @st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION)
    def _cached_indicators() -> list[dict]:
        return _load_indicator_list()

    @st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION)
    def _cached_ic() -> dict:
        return _load_ic_scores()

    indicators = _cached_indicators()
    ic_scores = _cached_ic()

    if not indicators:
        EmptyState("Nessun indicatore disponibile", hint="Popola config/custom_indicators.yaml.").render()
        return

    render_section_header("📊 IC Quality Dashboard")
    st.caption("IC (Information Coefficient): correlazione Spearman tra segnale e forward returns. "
               "Target: IC > 0.05. IC < 0.02 → segnale degradato.")

    active = [i for i in indicators if i["active"]]
    if not active:
        EmptyState("Nessun indicatore attivo", severity="warning").render()
        return

    for ind in active:
        ic = ic_scores.get(ind["id"])
        quality_flag = "ok" if ic is not None and abs(ic) >= 0.05 else (
            "low_ic" if ic is not None else "insufficient_data"
        )
        value = float(ic) if ic is not None else 0.0
        badge = SignalBadge(
            name=ind["name"],
            value=max(-1.0, min(1.0, value * 10)),  # IC [-0.1,0.1] → [-1,1] per visualizzazione
            confidence=1.0,
            ic_estimate=ic,
            quality_flag=quality_flag,
        )
        col_b, col_info = st.columns([3, 2])
        with col_b:
            badge.render()
        with col_info:
            ic_str = f"{ic:.4f}" if ic is not None else "N/D (< 30 obs)"
            st.caption(f"ID: `{ind['id']}` · Tipo: {ind['type']} · IC: {ic_str}")


if __name__ == "__main__":  # pragma: no cover
    render_page("Custom Indicators", "🔧", body_custom_indicators)
