"""Composite Score Gauge — componente Plotly riutilizzabile per score [-1, +1].

Usato da K1_Markets.py (CompositeSignalV3) e da qualsiasi altra pagina che
abbia bisogno di visualizzare un punteggio normalizzato in [-1, 1].

REGOLA 20: zero colori hardcoded — tutti da DesignTokens.
  · Zona negativa   → tokens.colors.negative (rosso)
  · Zona neutra     → tokens.colors.warning  (giallo/ambra)
  · Zona positiva   → tokens.colors.positive (verde)

API pubblica:
  · build_composite_gauge_figure()  → Plotly Figure (gauge circolare)
  · build_breakdown_bar_figure()    → Plotly Figure (barre orizzontali)
  · score_to_action()               → 'BUY' | 'HOLD' | 'REDUCE'
  · score_to_color()                → colore token dalla zona del punteggio
  · render_composite_gauge()        → Streamlit render completo (gauge + badge)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "9.0.0"
__all__ = [
    "build_composite_gauge_figure",
    "build_breakdown_bar_figure",
    "score_to_action",
    "score_to_color",
    "render_composite_gauge",
]

# Soglie azione — identiche a CompositeSignalAggregator (Regola 7: nessun magic number)
_BUY_THRESHOLD:    float = 0.30
_REDUCE_THRESHOLD: float = -0.30


def _hex_to_rgba(hex_color: str, alpha: float = 0.20) -> str:
    """Converte colore HEX (#RRGGBB) in rgba() con alpha specificato.

    ANTI-REGRESSIONE: Plotly non accetta #RRGGBBAA (8 hex digits) come
    colore CSS valido. Usare sempre rgba() per i colori con opacity.
    Sicuro: il hex_color proviene da DesignTokens, non da input utente.
    """
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"rgba({r},{g},{b},{alpha})"
    return hex_color  # fallback: colore solido se formato non riconosciuto


def score_to_action(score: float) -> str:
    """Converte uno score [-1, 1] nell'azione raccomandata.

    Restituisce 'BUY', 'HOLD' o 'REDUCE' con le stesse soglie
    del CompositeSignalAggregator (Regola 7).
    """
    if score >= _BUY_THRESHOLD:
        return "BUY"
    if score <= _REDUCE_THRESHOLD:
        return "REDUCE"
    return "HOLD"


def score_to_color(score: float, tokens: DesignTokens) -> str:
    """Restituisce il colore corretto dal token per una zona dello score.

    REGOLA 20: mai hardcoded — usa tokens.colors.*
    """
    if score > _BUY_THRESHOLD:
        return tokens.colors.positive
    if score < _REDUCE_THRESHOLD:
        return tokens.colors.negative
    return tokens.colors.warning


def build_composite_gauge_figure(
    score: float,
    tokens: DesignTokens,
    title: str = "Composite Signal",
    height: int = 280,
) -> Any:
    """Costruisce un gauge Plotly circolare per un composite score [-1, +1].

    Args:
        score:  Valore da visualizzare in [-1, 1]. Valori fuori range vengono
                clampati silenziosamente.
        tokens: DesignTokens — tutti i colori e stili (Regola 20).
        title:  Titolo del gauge.
        height: Altezza in pixel del chart.

    Returns:
        Plotly Figure object (importato lazily per evitare dipendenza hard).
    """
    import plotly.graph_objects as go

    # Clampa il valore — difensivo (non lanciare eccezione per score leggermente fuori range)
    clamped = max(-1.0, min(1.0, float(score)))

    # REGOLA 20: colori tutti da tokens
    neg_c  = tokens.colors.negative
    warn_c = tokens.colors.warning
    pos_c  = tokens.colors.positive
    bar_c  = score_to_color(clamped, tokens)

    # Zone colorate con 25% opacity (hex + "40")
    # ANTI-REGRESSIONE: il suffisso "40" è il valore hex per alpha=0.25.
    # Se il colore base è già con alpha, questo approccio non funziona —
    # assicurarsi che tokens.colors.* restituiscano colori RGB/HEX solidi.
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=clamped,
        number={
            "valueformat": "+.3f",
            "font": {
                "size": 38,
                "color": bar_c,
                "family": tokens.plotly.font_family,
            },
        },
        title={
            "text": title,
            "font": {
                "size": 14,
                "color": tokens.plotly.font_color,
                "family": tokens.plotly.font_family,
            },
        },
        gauge={
            "axis": {
                "range": [-1.0, 1.0],
                "tickvals": [-1.0, -0.5, 0.0, 0.5, 1.0],
                "ticktext": ["−1", "−0.5", "0", "+0.5", "+1"],
                "tickfont": {
                    "size": 11,
                    "color": tokens.plotly.font_color,
                },
            },
            "bar": {"color": bar_c, "thickness": 0.28},
            "bgcolor": tokens.plotly.plot_bgcolor,
            "steps": [
                {"range": [-1.0, _REDUCE_THRESHOLD], "color": _hex_to_rgba(neg_c)},
                {"range": [_REDUCE_THRESHOLD, _BUY_THRESHOLD], "color": _hex_to_rgba(warn_c)},
                {"range": [_BUY_THRESHOLD, 1.0],  "color": _hex_to_rgba(pos_c)},
            ],
            "threshold": {
                "line": {"color": bar_c, "width": 3},
                "thickness": 0.80,
                "value": clamped,
            },
        },
    ))

    fig.update_layout(
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        height=height,
        margin={"l": 30, "r": 30, "t": 60, "b": 20},
    )
    return fig


def build_breakdown_bar_figure(
    breakdown: dict[str, float],
    tokens: DesignTokens,
    title: str = "Breakdown componenti",
    height: int = 260,
) -> Any:
    """Costruisce un bar chart orizzontale per il breakdown dei componenti.

    Args:
        breakdown: {component_name: score_value} — valori in [-1, 1].
        tokens:    DesignTokens (Regola 20).
        title:     Titolo del chart.
        height:    Altezza in pixel.

    Returns:
        Plotly Figure con barre orizzontali colorate per zona.
    """
    import plotly.graph_objects as go

    if not breakdown:
        # Ritorna figura vuota con messaggio
        fig = go.Figure()
        fig.update_layout(
            title=title,
            template=tokens.plotly.template,
            paper_bgcolor=tokens.plotly.paper_bgcolor,
            height=height,
            annotations=[{
                "text": "Nessun dato disponibile",
                "xref": "paper", "yref": "paper",
                "x": 0.5, "y": 0.5, "showarrow": False,
                "font": {"color": tokens.plotly.font_color, "size": 14},
            }],
        )
        return fig

    labels = [k.replace("_", " ").title() for k in breakdown.keys()]
    values = list(breakdown.values())
    # REGOLA 20: colori dai token
    bar_colors = [score_to_color(v, tokens) for v in values]

    fig = go.Figure(go.Bar(
        x=values,
        y=labels,
        orientation="h",
        marker_color=bar_colors,
        text=[f"{v:+.3f}" for v in values],
        textposition="outside",
        textfont={
            "size": 11,
            "color": tokens.plotly.font_color,
            "family": tokens.plotly.font_family,
        },
    ))

    fig.update_layout(
        title={"text": title, "font": {"size": 13}},
        xaxis={
            "range": [-1.1, 1.1],
            "zeroline": True,
            "zerolinecolor": tokens.plotly.grid_color,
            "zerolinewidth": 1.5,
            "gridcolor": tokens.plotly.grid_color,
        },
        yaxis={"tickfont": {"size": 11}},
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={"family": tokens.plotly.font_family, "color": tokens.plotly.font_color},
        height=height,
        margin={"l": 110, "r": 70, "t": 40, "b": 20},
    )
    return fig


def render_composite_gauge(
    st: Any,
    score: float,
    tokens: DesignTokens,
    *,
    action: str | None = None,
    confidence: str | None = None,
    breakdown: dict[str, float] | None = None,
    title: str = "Composite Signal v3",
) -> None:  # pragma: no cover
    """Renderizza gauge + badge azione + breakdown in Streamlit.

    Args:
        st:         Modulo streamlit.
        score:      Score [-1, 1].
        tokens:     DesignTokens.
        action:     Stringa 'BUY'|'HOLD'|'REDUCE' (se None → calcolata dallo score).
        confidence: 'HIGH'|'MEDIUM'|'LOW' (se None → non mostrata).
        breakdown:  Dict {component: value} per il breakdown chart.
        title:      Titolo del gauge.
    """
    action_resolved  = action or score_to_action(score)
    bar_color        = score_to_color(score, tokens)

    action_icons = {"BUY": "🟢", "HOLD": "⚪", "REDUCE": "🔴"}
    icon = action_icons.get(action_resolved, "⚪")

    col_gauge, col_info = st.columns([3, 2])

    with col_gauge:
        fig = build_composite_gauge_figure(score, tokens, title=title)
        st.plotly_chart(fig, use_container_width=True)

    with col_info:
        st.markdown(
            f"<div style='padding:16px'>"
            f"<div style='font-size:2.2rem;font-weight:700;color:{bar_color}'>"
            f"{icon} {action_resolved}"
            f"</div>"
            f"<div style='font-size:1.4rem;color:{bar_color};margin-top:8px'>"
            f"{score:+.4f}"
            f"</div>"
            + (
                f"<div style='font-size:0.85rem;color:{tokens.colors.text_secondary};"
                f"margin-top:6px'>Confidence: {confidence}</div>"
                if confidence else ""
            )
            + "</div>",
            unsafe_allow_html=True,
        )

    if breakdown:
        fig_bd = build_breakdown_bar_figure(breakdown, tokens)
        st.plotly_chart(fig_bd, use_container_width=True)
