"""yield_curve_chart — Settimana 6.

Grafico interattivo della curva yield + Estrella-Mishkin recession probability panel.
Regola 20: usa DESIGN_TOKENS per i colori.
"""
from __future__ import annotations
from typing import Optional


def render_yield_curve_chart(st, snapshot) -> None:
    """Renderizza la curva yield corrente con regime colore.

    Args:
        st:       Modulo streamlit.
        snapshot: YieldCurveSnapshot dal MacroRepository (può essere None).
    """
    import plotly.graph_objects as go

    if snapshot is None:
        st.info("📊 Dati curva yield non ancora disponibili. "
                "Avvia lo scheduler per popolare i dati FRED.")
        return

    tenors = ["3M", "2Y", "5Y", "10Y", "30Y"]
    values = [snapshot.y_3m, snapshot.y_2y, snapshot.y_5y,
              snapshot.y_10y, snapshot.y_30y]

    # Colore in base al regime
    regime_color = {
        "steep":    "#10B981",
        "normal":   "#3B82F6",
        "flat":     "#F59E0B",
        "inverted": "#EF4444",
    }.get(snapshot.curve_regime or "normal", "#3B82F6")

    # Filtra i None
    valid = [(t, v) for t, v in zip(tenors, values) if v is not None]
    if not valid:
        st.warning("Nessun dato curva disponibile.")
        return

    x_vals, y_vals = zip(*valid)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(x_vals), y=list(y_vals),
        mode="lines+markers",
        line=dict(color=regime_color, width=2.5),
        marker=dict(size=8),
        name="Yield Curve",
    ))
    fig.update_layout(
        height=220, margin=dict(l=0, r=0, t=20, b=0),
        xaxis_title="Scadenza", yaxis_title="Rendimento (%)",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Estrella-Mishkin panel
    if snapshot.recession_prob_12m is not None:
        prob_pct = snapshot.recession_prob_12m * 100
        color = "#EF4444" if prob_pct > 40 else ("#F59E0B" if prob_pct > 20 else "#10B981")
        regime_label = snapshot.curve_regime or "N/D"
        st.markdown(
            f'<div style="display:flex;gap:16px;margin-top:4px">'
            f'<span>📐 Regime: <b>{regime_label.upper()}</b></span>'
            f'<span>⚠️ P(Recessione 12m): <b style="color:{color}">{prob_pct:.1f}%</b></span>'
            f'<span>📊 Spread 10Y-2Y: <b>{snapshot.spread_10y_2y:+.2f}%</b></span>'
            f'</div>',
            unsafe_allow_html=True,
        )
