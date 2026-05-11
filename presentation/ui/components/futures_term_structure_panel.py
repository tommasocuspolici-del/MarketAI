"""futures_term_structure_panel — Settimana 6.

Panel roll yield con indicatore term structure e freccia direzionale.
"""
from __future__ import annotations
from typing import Optional


def render_futures_term_structure_panel(st, analyses: list) -> None:
    """Renderizza il panel term structure per tutti i futures analizzati.

    Args:
        st:       Modulo streamlit.
        analyses: Lista di CommodityAnalysis (può essere vuota).
    """
    if not analyses:
        st.info("📈 Dati futures non ancora disponibili. Avvia lo scheduler.")
        return

    ts_icon = {
        "backwardation": ("⬆️", "#10B981", "Backwardation"),
        "flat":          ("➡️", "#6B7280", "Flat"),
        "contango":      ("⬇️", "#EF4444", "Contango"),
    }
    regime_color = {
        "bullish":               "#10B981",
        "backwardation_squeeze": "#059669",
        "neutral":               "#6B7280",
        "bearish":               "#EF4444",
        "contango_trap":         "#DC2626",
    }

    cols = st.columns(len(analyses))
    for col, analysis in zip(cols, analyses):
        ts = analysis.roll_result.term_structure.value
        icon, color, label = ts_icon.get(ts, ("➡️", "#6B7280", ts))
        r_color = regime_color.get(analysis.regime.value, "#6B7280")
        roll_pct = analysis.roll_result.roll_yield_22d * 100
        ann_pct  = analysis.roll_result.roll_yield_annual * 100
        with col:
            st.markdown(
                f'<div style="border:1px solid {color};border-radius:8px;padding:10px;text-align:center">'
                f'<div style="font-weight:700;font-size:1rem">{analysis.ticker}</div>'
                f'<div style="font-size:1.8rem">{icon}</div>'
                f'<div style="color:{color};font-size:0.8rem"><b>{label}</b></div>'
                f'<div style="font-size:0.75rem;margin-top:4px">'
                f'Roll 22d: <b>{roll_pct:+.2f}%</b><br>'
                f'Ann: <b>{ann_pct:+.1f}%</b></div>'
                f'<div style="margin-top:6px">'
                f'<span style="background:{r_color};color:white;padding:2px 6px;'
                f'border-radius:4px;font-size:0.7rem">{analysis.regime.value.upper()}</span>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
