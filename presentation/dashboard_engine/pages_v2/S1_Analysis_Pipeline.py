# ruff: noqa: N999
"""S1 — Analysis Pipeline (v8.0). Sostituisce E11_Analysis_Pipeline.py."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_s1_analysis_pipeline"]


def body_s1_analysis_pipeline(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.components.engine_signal_summary import render_engine_signal_summary

    require_auth()
    st.title("📡 Sistema — Analysis Pipeline")
    st.caption("Stato pipeline dati e composite signal giornaliero.")

    # ── Composite Signal ───────────────────────────────────────────────────
    st.subheader("🔬 Engine Composite Signal")
    try:
        from shared.db.macro_repo import get_macro_repository
        repo = get_macro_repository()
        composite = repo.read_composite_signal()
        render_engine_signal_summary(st, composite)
    except Exception as exc:
        st.warning(f"Composite signal non disponibile: {exc}")

    st.divider()

    # ── Pipeline jobs status ───────────────────────────────────────────────
    st.subheader("⚙️ Job Pipeline")
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()

        jobs = [
            ("VIX Strategy", "SELECT computed_at FROM vix_strategy_outputs ORDER BY computed_at DESC LIMIT 1"),
            ("Claims Cross",  "SELECT computed_at FROM claims_inflation_signals ORDER BY computed_at DESC LIMIT 1"),
            ("Yield Curve",   "SELECT snapshot_date FROM yield_curve_snapshots ORDER BY snapshot_date DESC LIMIT 1"),
            ("Credit Spreads","SELECT computed_at FROM credit_spread_signals ORDER BY computed_at DESC LIMIT 1"),
            ("Futures OHLCV", "SELECT MAX(ts) FROM futures_ohlcv"),
        ]

        for job_name, sql in jobs:
            try:
                rows = db.query(sql)
                val = rows[0][0] if rows and rows[0][0] else None
                icon = "🟢" if val else "🟡"
                st.markdown(f"{icon} **{job_name}**: {val or 'Nessun dato'}")
            except Exception:
                st.markdown(f"🔴 **{job_name}**: errore query")
    except Exception as exc:
        st.error(f"DB non raggiungibile: {exc}")

    # ── Refresh manuale ────────────────────────────────────────────────────
    st.divider()
    if st.button("🔄 Aggiorna pipeline ora", type="primary"):
        st.info("Per eseguire la pipeline manualmente: `python scripts/run_scheduler.py --dry-run`")
