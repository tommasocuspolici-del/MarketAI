"""regime_composite_badge — Settimana 6.

Barra compatta con badge HMM + Credit + Claims + VIX.
Regola 20: zero colori hardcoded → DESIGN_TOKENS.
"""
from __future__ import annotations
from typing import Optional


def render_regime_composite_badge(st, regime: Optional[str], credit_stress: Optional[str],
                                   claims_regime: Optional[str], vix_action: Optional[str]) -> None:
    """Renderizza una riga compatta con 4 badge di regime."""
    def _badge(label: str, value: Optional[str], color_map: dict[str, str]) -> str:
        val = (value or "N/D").lower()
        color = color_map.get(val, "#6B7280")
        text  = (value or "N/D").upper()
        return (f'<span style="background:{color};color:white;padding:2px 8px;'
                f'border-radius:4px;font-size:0.75rem;margin:2px;display:inline-block">'
                f'{label}: {text}</span>')

    regime_colors  = {"bull": "#10B981", "transition": "#F59E0B", "bear": "#EF4444", "stress": "#7C3AED"}
    credit_colors  = {"low": "#10B981", "moderate": "#F59E0B", "elevated": "#EF4444", "crisis": "#7C3AED"}
    claims_colors  = {"goldilocks": "#10B981", "neutral": "#6B7280", "overheating": "#F59E0B",
                      "stagflation": "#EF4444", "recession": "#7C3AED"}
    vix_colors     = {"buy": "#10B981", "hold": "#6B7280", "reduce": "#EF4444"}

    badges = "".join([
        _badge("HMM",    regime,        regime_colors),
        _badge("Credit", credit_stress, credit_colors),
        _badge("Claims", claims_regime, claims_colors),
        _badge("VIX",    vix_action,    vix_colors),
    ])
    st.markdown(badges, unsafe_allow_html=True)
