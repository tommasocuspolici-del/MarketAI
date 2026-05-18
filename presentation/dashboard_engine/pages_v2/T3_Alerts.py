# ruff: noqa: N999
"""T3 Alerts (v8.1) — alert reali da VIX, FRED yield curve, DuckDB surprise_signal."""
from __future__ import annotations

__version__ = "8.1.0"
__all__ = ["body_t3_alerts"]


def body_t3_alerts(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("⚙️ Strategie — Alerts & Notifiche")
    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        vix_threshold = st.number_input("Soglia VIX", value=25.0, min_value=10.0, max_value=80.0, step=1.0, key="t3_vix_thr")
    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="t3_refresh"):
            st.cache_data.clear()
            st.rerun()

    @st.cache_data(ttl=300)
    def _load_alerts(vix_thr: float) -> list[dict]:
        import yfinance as yf
        alerts: list[dict] = []

        # 1. VIX alert
        try:
            vix_hist = yf.Ticker("^VIX").history(period="2d")
            if not vix_hist.empty:
                vix_now = float(vix_hist["Close"].iloc[-1])
                if vix_now > vix_thr:
                    alerts.append({
                        "Severity": "🔴 HIGH",
                        "Type": "Vol spike",
                        "Detail": f"VIX {vix_now:.1f} > soglia {vix_thr:.0f}",
                        "Fonte": "yfinance ^VIX",
                    })
                else:
                    alerts.append({
                        "Severity": "🟢 OK",
                        "Type": "Volatilità",
                        "Detail": f"VIX {vix_now:.1f} — sotto soglia {vix_thr:.0f}",
                        "Fonte": "yfinance ^VIX",
                    })
        except Exception as exc:
            alerts.append({"Severity": "⚠️ ERR", "Type": "VIX", "Detail": str(exc), "Fonte": "yfinance"})

        # 2. Surprise signal da DuckDB
        try:
            from shared.db.duckdb_client import get_duckdb_client
            db = get_duckdb_client()
            rows = db.query(
                "SELECT signal_value, dominant_sector, generated_at "
                "FROM surprise_signal ORDER BY generated_at DESC LIMIT 1"
            )
            if rows and rows[0][0] is not None:
                sig_val = float(rows[0][0])
                sector = rows[0][1] or "N/D"
                if abs(sig_val) > 0.5:
                    alerts.append({
                        "Severity": "🟡 MED" if abs(sig_val) < 1.0 else "🔴 HIGH",
                        "Type": "Economic Surprise",
                        "Detail": f"Signal {sig_val:+.2f} — settore dominante: {sector}",
                        "Fonte": "DuckDB surprise_signal",
                    })
        except Exception:
            pass

        # 3. Yield curve inversion (FRED)
        try:
            from engine.market_data.fred_simple_client import FredSimpleClient
            fred = FredSimpleClient()
            if fred.has_api_key:
                t10 = fred.fetch_latest("DGS10")
                t2  = fred.fetch_latest("DGS2")
                if t10 is not None and t2 is not None:
                    spread = t10[1] - t2[1]  # fetch_latest ritorna (date, float)
                    if spread < 0:
                        alerts.append({
                            "Severity": "🔴 HIGH",
                            "Type": "Yield Curve Inversion",
                            "Detail": f"Spread 10Y-2Y: {spread*100:.0f}bp — inversione attiva",
                            "Fonte": "FRED DGS10/DGS2",
                        })
                    else:
                        alerts.append({
                            "Severity": "🟢 OK",
                            "Type": "Yield Curve",
                            "Detail": f"Spread 10Y-2Y: +{spread*100:.0f}bp — normale",
                            "Fonte": "FRED DGS10/DGS2",
                        })
        except Exception:
            pass

        return alerts

    alerts = _load_alerts(float(vix_threshold))

    critical = [a for a in alerts if a["Severity"].startswith("🔴")]
    medium   = [a for a in alerts if a["Severity"].startswith("🟡")]
    ok_items = [a for a in alerts if a["Severity"].startswith("🟢")]

    if critical:
        st.error(f"🚨 {len(critical)} alert critico/i attivo/i")
    if medium:
        st.warning(f"⚠️ {len(medium)} alert medio/i")
    if not critical and not medium:
        st.success("✅ Nessun alert critico — mercato nella norma")

    import pandas as pd
    if alerts:
        df = pd.DataFrame(alerts)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nessun dato disponibile — verifica connessione DB e FRED_API_KEY.")
