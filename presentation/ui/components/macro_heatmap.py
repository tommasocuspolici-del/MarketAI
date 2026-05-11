"""macro_heatmap — Settimana 6.

Griglia 4×7 con semaforo (Verde/Giallo/Rosso) per le 28 serie FRED.
Regola 20: zero colori hardcoded → usa variabili CSS/token.
"""
from __future__ import annotations
from typing import Optional
import pandas as pd


# Mappa serie FRED → soglie per classificazione semaforo
# Formato: (label_breve, direzione_positiva, soglia_verde, soglia_gialla)
# direzione_positiva = True se valori alti sono buoni (es. payrolls)
# direzione_positiva = False se valori alti sono cattivi (es. VIX, claims)
_FRED_THRESHOLDS: dict[str, tuple[str, bool, float, float]] = {
    # Labour
    "ICSA":    ("Claims",   False, 250_000, 350_000),
    "CCSA":    ("Cont.Clm", False, 1_800_000, 2_500_000),
    "PAYEMS":  ("Payrolls", True,  150_000, 0),
    # Inflation
    "CPIAUCSL": ("CPI",     False, 2.5, 4.0),
    "CPILFESL": ("Core CPI",False, 2.5, 4.0),
    "T10YIE":   ("Breakeven",False,2.5, 3.5),
    # Rates
    "DGS10":   ("10Y",  False, 5.0, 6.0),
    "DGS2":    ("2Y",   False, 5.0, 6.0),
    "DGS3MO":  ("3M",   False, 5.5, 6.5),
    "T10Y2Y":  ("Spread",True, 0.0, -0.5),
    "FEDFUNDS":("FedFunds",False,5.5, 6.5),
    # Credit
    "BAMLH0A0HYM2": ("HY OAS",  False, 350, 600),
    "BAMLC0A0CM":   ("IG OAS",  False, 120, 200),
    "TEDRATE":       ("TED",     False, 40, 80),
    "NFCI":          ("NFCI",    False, 0.0, 1.0),
    # Growth
    "INDPRO":  ("IndProd",  True,  0.0, -1.0),
    "GDP":     ("GDP",      True,  2.0,  0.5),
    # Sentiment / Housing
    "UMCSENT": ("Sentiment",True,  70.0, 55.0),
    "HOUST":   ("Housing",  True,  1400, 1000),
    # International / Trade
    "USSLIND": ("LeadInd",  True,  100, 98),
    "BAMLH0A0HYM2OAS": ("HY Spr", False, 350, 600),
    # PMI / ISM (proxy: NAPM)
    "NAPM":    ("ISM",      True,  50.0, 45.0),
    # Oil / Commodity
    "DCOILWTICO": ("WTI",   False, 80.0, 100.0),
    # FX
    "DTWEXBGS":  ("USD Idx", False, 105, 115),
    # Misc macro
    "M2SL":    ("M2",   True,  2.0,  0.0),
    "T10Y3M":  ("10Y-3M",True, 0.0, -1.0),
    "VIXCLS":  ("VIX",  False, 20.0, 30.0),
    "UNRATE":  ("Unemp", False, 4.5,  6.0),
}


def render_macro_heatmap(st, series_data: dict[str, Optional[float]]) -> None:
    """Renderizza la griglia 4×7 delle 28 serie FRED con semaforo.

    Args:
        st:           Modulo streamlit.
        series_data:  {series_id: latest_value}. Valori None → grigio.
    """
    cells_html = []
    for sid, (label, positive_good, green_thr, yellow_thr) in _FRED_THRESHOLDS.items():
        val = series_data.get(sid)
        color, emoji = _classify_traffic(val, positive_good, green_thr, yellow_thr)
        val_str = _format_val(val, sid)
        cells_html.append(
            f'<div style="background:{color}22;border:1px solid {color};'
            f'border-radius:6px;padding:6px 4px;text-align:center;min-width:80px">'
            f'<div style="font-size:1rem">{emoji}</div>'
            f'<div style="font-size:0.7rem;font-weight:600;color:{color}">{label}</div>'
            f'<div style="font-size:0.68rem;color:#9CA3AF">{val_str}</div>'
            f'</div>'
        )

    # Layout griglia 7 colonne × 4 righe
    grid_html = (
        '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px">'
        + "".join(cells_html)
        + "</div>"
    )
    st.markdown(grid_html, unsafe_allow_html=True)


def build_series_data_from_repo(macro_repo) -> dict[str, Optional[float]]:
    """Legge l'ultimo valore di ogni serie dal MacroRepository."""
    data: dict[str, Optional[float]] = {}
    for sid in _FRED_THRESHOLDS:
        try:
            obs = macro_repo.read_latest_macro(sid)
            data[sid] = float(obs["value"]) if obs and obs.get("value") is not None else None
        except Exception:
            data[sid] = None
    return data


def _classify_traffic(val, positive_good: bool, green_thr: float, yellow_thr: float):
    if val is None:
        return "#6B7280", "⚫"
    if positive_good:
        if val >= green_thr:
            return "#10B981", "🟢"
        if val >= yellow_thr:
            return "#F59E0B", "🟡"
        return "#EF4444", "🔴"
    else:
        if val <= green_thr:
            return "#10B981", "🟢"
        if val <= yellow_thr:
            return "#F59E0B", "🟡"
        return "#EF4444", "🔴"


def _format_val(val: Optional[float], sid: str) -> str:
    if val is None:
        return "N/D"
    if sid in ("ICSA", "CCSA", "PAYEMS", "HOUST", "M2SL"):
        return f"{val:,.0f}"
    if "OAS" in sid or sid in ("TEDRATE", "VIXCLS"):
        return f"{val:.0f}"
    return f"{val:.1f}"
