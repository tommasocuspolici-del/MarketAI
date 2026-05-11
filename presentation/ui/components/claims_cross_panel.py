"""claims_cross_panel — Settimana 6.

Panel Claims 4wk MA + CPI YoY + regime label con colore.
"""
from __future__ import annotations
from typing import Optional


def render_claims_cross_panel(st, signal) -> None:
    """Renderizza il panel Claims/Inflation.

    Args:
        st:     Modulo streamlit.
        signal: ClaimsInflationSignal dal MacroRepository (può essere None).
    """
    if signal is None:
        st.info("📋 Dati Claims/Inflation non ancora disponibili.")
        return

    regime_cfg = {
        "goldilocks":  ("🟢", "#10B981", "Goldilocks: mercato del lavoro solido, inflazione moderata"),
        "stagflation": ("🔴", "#EF4444", "Stagflazione: claims in salita + inflazione elevata"),
        "overheating": ("🟡", "#F59E0B", "Surriscaldamento: labor market troppo teso"),
        "recession":   ("🟣", "#7C3AED", "Recession Watch: claims in forte salita"),
        "neutral":     ("⚪", "#6B7280", "Neutro: segnali misti"),
    }
    icon, color, desc = regime_cfg.get(signal.regime_label, ("⚪", "#6B7280", "N/D"))

    col1, col2, col3 = st.columns(3)
    with col1:
        icsa = signal.icsa_4wk_ma
        st.metric("Claims 4wk MA", f"{icsa:,.0f}" if icsa else "N/D",
                  delta=f"{signal.icsa_yoy_change_pct*100:+.1f}% YoY"
                  if signal.icsa_yoy_change_pct is not None else None)
    with col2:
        cpi = signal.cpi_yoy
        st.metric("CPI YoY", f"{cpi:.1f}%" if cpi else "N/D")
    with col3:
        score = signal.regime_score
        st.metric("Regime Score", f"{score:+.2f}")

    st.markdown(
        f'<div style="background:{color}22;border-left:4px solid {color};'
        f'padding:8px 12px;border-radius:4px;margin-top:8px">'
        f'{icon} <b>{signal.regime_label.upper()}</b> — {desc}</div>',
        unsafe_allow_html=True,
    )
