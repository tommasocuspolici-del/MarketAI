"""MetricCard component — Rule 33 (EXPLAIN_EVERY_METRIC).

Sostituisce ``st.metric`` puro: ogni metrica mostrata include nome esteso
(dal glossario) e tooltip auto-generato con descrizione, interpretazione,
range tipico e (per utenti Expert) formula.

Esempio d'uso::

    from presentation.ui.components.metric_card import render_metric_card

    render_metric_card(
        tokens=tokens,
        term="VIX",
        value=18.4,
        delta=+1.2,
        format_spec=".1f",
        unit_override=None,  # se None, usa unit dal glossario
    )

Il rendering si adatta automaticamente al livello utente (Beginner /
Intermediate / Expert) configurato in session_state['user_level'].
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from shared.glossary import GlossaryEntry, get_glossary

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.2.0"

__all__ = [
    "MetricSpec",
    "render_metric_card",
    "render_metric_row",
]

# Default level per gli utenti che non hanno ancora scelto.
_DEFAULT_LEVEL = "intermediate"


@dataclass(frozen=True, slots=True)
class MetricSpec:
    """Specifica di una metrica da renderizzare.

    Args:
        term: Chiave del glossario (es. "VIX", "Sharpe", "Max DD").
        value: Valore numerico o stringa già formattata.
        delta: Variazione opzionale rispetto al periodo precedente.
        format_spec: Formato Python per il valore (es. ".2f", ",.0f").
        unit_override: Forza un'unità diversa da quella del glossario.
        delta_pct: Se True, il delta è interpretato come percentuale.
    """

    term: str
    value: float | str
    delta: float | None = None
    format_spec: str = ".2f"
    unit_override: str | None = None
    delta_pct: bool = False


def _get_user_level() -> str:
    """Recupera il livello utente da Streamlit session_state, o default."""
    try:
        import streamlit as st
        return st.session_state.get("user_level", _DEFAULT_LEVEL)
    except ImportError:
        return _DEFAULT_LEVEL


def _format_value(value: float | str, fmt: str) -> str:
    """Formatta il valore con il fmt fornito, gracefully."""
    if isinstance(value, str):
        return value
    try:
        return format(value, fmt)
    except (ValueError, TypeError):
        return str(value)


def _format_delta(delta: float, *, as_pct: bool) -> tuple[str, str]:
    """Ritorna (testo_delta, hint_colore)."""
    if as_pct:
        text = f"{delta * 100:+.2f}%"
    else:
        text = f"{delta:+.2f}"
    if delta > 0:
        color_hint = "positive"
    elif delta < 0:
        color_hint = "negative"
    else:
        color_hint = "neutral"
    return text, color_hint


def _build_card_html(
    *,
    tokens: Any,
    entry: GlossaryEntry,
    value_str: str,
    unit: str,
    delta_text: str | None,
    delta_color: str,
    delta_unavailable: bool = False,
) -> str:
    """Costruisce HTML della card. Funzione pura, testabile.

    v7.2 (fix B4): se ``delta_unavailable=True`` mostra esplicitamente
    "variazione N/D" invece di non mostrare nulla. Cosi' l'utente capisce
    che e' un dato MANCANTE, non semplicemente "uguale a prima".
    """
    # Estrazione palette: tollera diverse strutture DesignTokens.
    primary = getattr(getattr(tokens, "colors", tokens), "primary", "#3b82f6")
    text_main = getattr(getattr(tokens, "colors", tokens), "text", "#0f172a")
    text_muted = getattr(getattr(tokens, "colors", tokens), "text_secondary", "#64748b")

    color_map = {
        "positive": getattr(getattr(tokens, "colors", tokens), "positive", "#16a34a"),
        "negative": getattr(getattr(tokens, "colors", tokens), "negative", "#dc2626"),
        "neutral": text_muted,
    }
    delta_html = ""
    if delta_text is not None:
        delta_html = (
            f'<div style="font-size:0.8rem;color:{color_map[delta_color]};'
            f'font-weight:500;">{delta_text}</div>'
        )
    elif delta_unavailable:
        # v7.2: indichiamo dato mancante invece di lasciare vuoto
        delta_html = (
            f'<div style="font-size:0.7rem;color:{text_muted};'
            f'font-style:italic;">variazione N/D</div>'
        )

    unit_str = f"<span style='color:{text_muted};font-size:0.85rem;'> {unit}</span>" if unit else ""

    return (
        '<div style="padding:0.75rem 1rem;border-radius:8px;'
        'background:rgba(148,163,184,0.06);'
        'border:1px solid rgba(148,163,184,0.18);'
        'min-height:88px;">'
        f'<div style="display:flex;align-items:baseline;gap:6px;'
        f'flex-wrap:wrap;margin-bottom:4px;">'
        f'<span style="font-weight:700;font-size:0.85rem;color:{primary};'
        f'letter-spacing:0.02em;">{entry.term}</span>'
        f'<span style="font-size:0.7rem;color:{text_muted};'
        f'line-height:1.1;">{entry.full_name}</span>'
        f'</div>'
        f'<div style="font-size:1.4rem;font-weight:700;color:{text_main};'
        f'line-height:1.2;">{value_str}{unit_str}</div>'
        f'{delta_html}'
        '</div>'
    )


def render_metric_card(
    tokens: DesignTokens,
    term: str,
    value: float | str,
    *,
    delta: float | None = None,
    format_spec: str = ".2f",
    unit_override: str | None = None,
    delta_pct: bool = False,
    show_delta_unavailable: bool = False,
) -> None:  # pragma: no cover -- Streamlit-rendered
    """Renderizza una metric card explainable (Rule 33).

    Args:
        tokens: DesignTokens (per coerenza visiva con il resto del tema).
        term: Chiave del glossario. Se assente, usa stub.
        value: Valore numerico o stringa pre-formattata.
        delta: Variazione opzionale.
        format_spec: Formato Python per il valore.
        unit_override: Forza un'unità diversa da quella del glossario.
        delta_pct: Se True, formatta delta come percentuale.
        show_delta_unavailable: Se True E delta is None, mostra "variazione
            N/D" invece di lasciare vuoto. Default False per backward compat.
    """
    glossary = get_glossary()
    entry = glossary.get_or_stub(term)
    user_level = _get_user_level()

    value_str = _format_value(value, format_spec)
    unit = unit_override if unit_override is not None else entry.unit

    delta_text: str | None = None
    delta_color = "neutral"
    if delta is not None:
        delta_text, delta_color = _format_delta(delta, as_pct=delta_pct)

    html = _build_card_html(
        tokens=tokens,
        entry=entry,
        value_str=value_str,
        unit=unit,
        delta_text=delta_text,
        delta_color=delta_color,
        delta_unavailable=show_delta_unavailable and delta is None,
    )

    try:
        import streamlit as st
        st.markdown(html, unsafe_allow_html=True)
        # Tooltip via expander leggero — sempre disponibile, ma compatto.
        # Per Beginner aggiungiamo anche il caption inline visibile.
        if user_level == "beginner" and entry.description:
            st.caption(f"ⓘ {entry.description}")
        elif entry.description:
            with st.expander("ⓘ Cos'è?", expanded=False):
                st.markdown(entry.tooltip_text(level=user_level))
    except ImportError:
        return


# v7.2 (fix B4): default cols_per_row=4. Su viewport 1080p (~1920px),
# 4 cards per riga = 480px ciascuna -> font readable, delta visibile.
# 8 cards per riga (vecchio comportamento) = 240px -> KPI illeggibile.
_DEFAULT_COLS_PER_ROW = 4


def render_metric_row(
    tokens: DesignTokens,
    metrics: list[MetricSpec | dict[str, Any]],
    *,
    cols_per_row: int = _DEFAULT_COLS_PER_ROW,
    show_delta_unavailable: bool = True,
) -> None:  # pragma: no cover -- Streamlit-rendered
    """Renderizza una griglia orizzontale di metric cards in righe.

    v7.2 (fix B4): la griglia viene splittata in righe da ``cols_per_row``
    colonne (default 4) per evitare card troppo strette su viewport 1080p.
    Se passi 8 metriche con default cols_per_row=4, otterrai 2 righe da 4.

    Args:
        tokens: DesignTokens.
        metrics: Lista di MetricSpec o dict (backward compat con pagine v6).
        cols_per_row: Numero di colonne per riga (default 4). Min 1, max 8.
        show_delta_unavailable: Se True, le metric con delta=None mostrano
            "variazione N/D" invece di restare vuote. Default True (era
            comportamento implicito False prima della v7.2).
    """
    try:
        import streamlit as st
    except ImportError:
        return

    if not metrics:
        return

    # Clamp per evitare valori assurdi (es. cols_per_row=0 -> divisione 0)
    cpr = max(1, min(int(cols_per_row), 8))

    for i in range(0, len(metrics), cpr):
        chunk = metrics[i : i + cpr]
        # Sempre cpr colonne anche se l'ultima riga e' parziale: cosi'
        # le card mantengono la stessa larghezza delle righe complete.
        cols = st.columns(cpr)
        for col, m in zip(cols[: len(chunk)], chunk, strict=True):
            with col:
                if isinstance(m, MetricSpec):
                    render_metric_card(
                        tokens,
                        m.term,
                        m.value,
                        delta=m.delta,
                        format_spec=m.format_spec,
                        unit_override=m.unit_override,
                        delta_pct=m.delta_pct,
                        show_delta_unavailable=show_delta_unavailable,
                    )
                else:
                    render_metric_card(
                        tokens,
                        term=str(m.get("term", m.get("label", ""))),
                        value=m.get("value", "—"),
                        delta=m.get("delta"),
                        format_spec=str(m.get("format_spec", ".2f")),
                        unit_override=m.get("unit_override"),
                        delta_pct=bool(m.get("delta_pct", False)),
                        show_delta_unavailable=show_delta_unavailable,
                    )
