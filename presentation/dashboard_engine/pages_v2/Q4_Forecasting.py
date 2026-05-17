# ruff: noqa: N999
"""Q4 Forecasting (v8.0)."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_q4_forecasting"]


def body_q4_forecasting(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()
    st.title("🔬 Analisi — Forecasting (3 scenari)")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="q4_refresh"):
            st.cache_data.clear()
            st.rerun()
    st.caption("Wiring dati reali da DuckDB — completamento Settimana 8.")

    try:
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.prices_repo import get_prices_repository
        _db    = get_duckdb_client()
        _prepo = get_prices_repository()
        st.caption("✅ DB connesso — dati reali disponibili")
    except Exception as exc:
        st.caption(f"⚠️ DB: {exc}")
