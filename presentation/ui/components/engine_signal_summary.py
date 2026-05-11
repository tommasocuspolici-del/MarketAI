"""engine_signal_summary — Settimana 6.

Box giornaliero con composite score e breakdown componenti.
"""
from __future__ import annotations
from typing import Optional


def render_engine_signal_summary(st, composite_signal) -> None:
    """Renderizza il box composite score con breakdown.

    Args:
        st:               Modulo streamlit.
        composite_signal: EngineCompositeSignal dal MacroRepository (None → placeholder).
    """
    if composite_signal is None:
        st.info("🔬 Composite Signal non ancora calcolato. "
                "Avvia lo scheduler per generare il segnale giornaliero.")
        return

    score   = composite_signal.composite_score
    action  = composite_signal.recommended_action
    conf    = composite_signal.confidence

    action_cfg = {
        "BUY":    ("#10B981", "🟢", "BUY"),
        "HOLD":   ("#6B7280", "⚪", "HOLD"),
        "REDUCE": ("#EF4444", "🔴", "REDUCE"),
    }
    color, icon, label = action_cfg.get(action, ("#6B7280", "⚪", action))

    # Score bar: -1 → 0 → +1
    bar_pct = int((score + 1) / 2 * 100)
    bar_color = "#10B981" if score > 0.3 else ("#EF4444" if score < -0.3 else "#F59E0B")

    st.markdown(
        f'<div style="border:2px solid {color};border-radius:10px;padding:16px;margin-bottom:8px">'
        f'<div style="display:flex;justify-content:space-between;align-items:center">'
        f'<div><span style="font-size:2rem">{icon}</span> '
        f'<span style="font-size:1.4rem;font-weight:700;color:{color}">{label}</span></div>'
        f'<div style="text-align:right">'
        f'<div style="font-size:0.8rem;color:#9CA3AF">Composite Score</div>'
        f'<div style="font-size:1.8rem;font-weight:700;color:{bar_color}">{score:+.3f}</div>'
        f'<div style="font-size:0.72rem;color:#9CA3AF">Confidence: {conf}</div>'
        f'</div></div>'
        f'<div style="background:#374151;border-radius:4px;height:8px;margin-top:10px">'
        f'<div style="background:{bar_color};width:{bar_pct}%;height:8px;border-radius:4px"></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # Breakdown componenti
    import json
    breakdown_json = composite_signal.component_breakdown_json
    if breakdown_json:
        try:
            breakdown = json.loads(breakdown_json)
            if breakdown:
                cols = st.columns(len(breakdown))
                for col, (comp, val) in zip(cols, breakdown.items()):
                    bcolor = "#10B981" if val > 0.1 else ("#EF4444" if val < -0.1 else "#6B7280")
                    col.markdown(
                        f'<div style="text-align:center">'
                        f'<div style="font-size:0.7rem;color:#9CA3AF">{comp.upper()}</div>'
                        f'<div style="font-size:1rem;font-weight:700;color:{bcolor}">{val:+.2f}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
        except (json.JSONDecodeError, AttributeError):
            pass
