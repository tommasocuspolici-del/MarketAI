# ruff: noqa: N999
"""T1 Backtesting (v8.0)."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_t1_backtesting"]


def body_t1_backtesting(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()
    st.title("⚙️ Strategie — Backtesting VectorBT")
    st.caption("Wiring dati reali da DuckDB — completamento Settimana 8.")

    try:
        from shared.db.duckdb_client import get_duckdb_client
        from shared.db.prices_repo import get_prices_repository
        _db    = get_duckdb_client()
        _prepo = get_prices_repository()
        st.caption("✅ DB connesso — dati reali disponibili")
    except Exception as exc:
        st.caption(f"⚠️ DB: {exc}")
