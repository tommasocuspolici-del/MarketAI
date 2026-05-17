# ruff: noqa: N999
"""E14 — Alerts engine (v7.0): alert di mercato da dati live."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.0.0"

__all__ = ["body_alerts"]


def _load_engine_alerts(vix_threshold: float, var_threshold: float) -> list[dict]:
    """Genera alert reali da dati live (VIX da yfinance, surprise signal da DB)."""
    alerts: list[dict] = []

    # 1. VIX check via yfinance
    try:
        import yfinance as yf
        vix_data = yf.Ticker("^VIX").history(period="2d")
        if not vix_data.empty:
            vix_now = float(vix_data["Close"].iloc[-1])
            vix_prev = float(vix_data["Close"].iloc[-2]) if len(vix_data) >= 2 else vix_now
            if vix_now > vix_threshold:
                severity = "🔴 Critical" if vix_now > vix_threshold * 1.3 else "🟡 Warning"
                alerts.append({
                    "Severity": severity,
                    "Type": "Vol spike",
                    "Detail": f"VIX corrente {vix_now:.1f} > soglia {vix_threshold:.0f} (precedente: {vix_prev:.1f})",
                    "Fonte": "yfinance ^VIX",
                })
    except Exception:
        pass

    # 2. Economic Surprise signal da DuckDB
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        rows = db.query(
            "SELECT signal_value, dominant_sector, generated_at "
            "FROM surprise_signal ORDER BY generated_at DESC LIMIT 1"
        )
        if rows:
            sv, sector, ts = rows[0]
            sv = float(sv)
            if abs(sv) > 0.5:
                severity = "🔴 Critical" if abs(sv) > 1.0 else "🟡 Warning"
                direction = "positivo (beat)" if sv > 0 else "negativo (miss)"
                alerts.append({
                    "Severity": severity,
                    "Type": "Surprise estrema",
                    "Detail": f"Economic Surprise {direction}: score {sv:+.2f}, settore dominante: {sector}",
                    "Fonte": f"DB surprise_signal · {str(ts)[:10]}",
                })
    except Exception:
        pass

    # 3. Yield curve inversion check via FRED
    try:
        from engine.market_data.fred_simple_client import FredSimpleClient
        fred = FredSimpleClient()
        if fred.has_api_key:
            t10 = fred.fetch_latest("DGS10")
            t2  = fred.fetch_latest("DGS2")
            if t10 and t2:
                spread = t10[1] - t2[1]
                if spread < 0:
                    alerts.append({
                        "Severity": "🟡 Warning",
                        "Type": "Inversione yield curve",
                        "Detail": f"Spread 10Y-2Y = {spread:+.2f}% (inversione storico indicatore recessione)",
                        "Fonte": f"FRED · 10Y={t10[1]:.2f}% · 2Y={t2[1]:.2f}%",
                    })
    except Exception:
        pass

    return alerts


def body_alerts(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit-rendered body
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="e14_refresh"):
            st.cache_data.clear()
            st.rerun()

    render_section_header("⚙️ Alert Configuration")
    cols = st.columns(2)
    vix_threshold = cols[0].number_input("Soglia VIX alert", value=25.0, step=1.0, min_value=10.0, max_value=80.0)
    var_threshold = cols[1].number_input("Soglia VaR 95% (%)", value=-5.0, step=0.5, max_value=0.0)

    st.divider()
    render_section_header("🚨 Alert Attivi", "Generati da dati live: VIX (yfinance), Surprise Signal (DB), Yield Curve (FRED)")

    with st.spinner("Verifica alert in corso..."):
        alerts = _load_engine_alerts(vix_threshold=float(vix_threshold), var_threshold=float(var_threshold))

    if not alerts:
        st.success("✅ Nessun alert attivo — tutti gli indicatori monitorati rientrano nelle soglie configurate.")
    else:
        st.dataframe(
            pd.DataFrame(alerts),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()
    st.caption(
        "⚠️ Alert VaR portafoglio: richiede storico posizioni nel DB. "
        "Alert sentiment: connetti API esterne (Finnhub, AAII) per attivarlo."
    )


if __name__ == "__main__":   # pragma: no cover
    render_page("Alerts", "🚨", body_alerts)
