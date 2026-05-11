# ruff: noqa: N999
"""M1 — Macro Dashboard (v8.0). Sostituisce E6_Macro.py."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_m1_macro_dashboard"]


def _load_series_data() -> dict:
    from shared.db.macro_repo import get_macro_repository
    from presentation.ui.components.macro_heatmap import build_series_data_from_repo
    repo = get_macro_repository()
    return build_series_data_from_repo(repo)


def body_m1_macro_dashboard(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.components.macro_heatmap import render_macro_heatmap

    require_auth()
    st.title("🌍 Macro — Dashboard FRED")
    st.caption("28 serie macroeconomiche FRED con semaforo (🟢 ok · 🟡 attenzione · 🔴 critico).")

    try:
        series_data = _load_series_data()
        available = sum(1 for v in series_data.values() if v is not None)
        st.caption(f"Serie disponibili: {available}/28")
        render_macro_heatmap(st, series_data)
    except Exception as exc:
        st.warning(f"⚠️ Dati FRED non ancora disponibili: {exc}")
        st.info("Avvia lo scheduler per popolare le serie FRED: `python scripts/run_scheduler.py`")

    # ── Metriche chiave in dettaglio ───────────────────────────────────────
    st.divider()
    st.subheader("📊 Indicatori Chiave")
    try:
        from shared.db.macro_repo import get_macro_repository
        repo = get_macro_repository()

        key_series = {
            "CPI YoY (%)": "CPIAUCSL",
            "Fed Funds (%)": "FEDFUNDS",
            "10Y Treasury (%)": "DGS10",
            "HY OAS (bps)": "BAMLH0A0HYM2",
            "Initial Claims": "ICSA",
            "Unemployment (%)": "UNRATE",
        }

        cols = st.columns(3)
        for i, (label, sid) in enumerate(key_series.items()):
            with cols[i % 3]:
                try:
                    obs = repo.read_latest_macro(sid)
                    val = obs["value"] if obs else None
                    st.metric(label, f"{val:.2f}" if val is not None else "N/D")
                except Exception:
                    st.metric(label, "N/D")
    except Exception:
        pass

    if st.button("🔄 Aggiorna"):
        _load_series_data.clear()
        st.rerun()
