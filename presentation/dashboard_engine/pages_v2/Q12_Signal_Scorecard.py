# ruff: noqa: N999
"""Q12 — Signal Scorecard (IC rolling, hit rate, staleness, alpha decay).

Legge da DuckDB: tabella signal_scorecard.
Zero API call (Regola 12).
"""
from __future__ import annotations

__version__ = "12.0.0"
__all__ = ["body_q12_signal_scorecard"]


# ─── Public loaders (testabili senza Streamlit) ───────────────────────────────

def load_scorecard():  # pragma: no cover — vedi test_q12
    """Carica signal_scorecard da DuckDB. Ritorna DataFrame (anche vuoto)."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        return db.execute(
            "SELECT * FROM signal_scorecard ORDER BY snapshot_date DESC, signal_id"
        ).df()
    except Exception:
        return pd.DataFrame()


# ─── Streamlit body ───────────────────────────────────────────────────────────

def body_q12_signal_scorecard(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    from presentation.ui.cache_policy import CACHE_TTL

    st.title("📊 Q12 — Signal Scorecard")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="signal_scorecard_refresh"):
            st.cache_data.clear()
            st.rerun()

    @st.cache_data(ttl=CACHE_TTL.SIGNALS)
    def _load():
        return load_scorecard()

    df = _load()

    if df.empty:
        st.info(
            "Nessun dato nel Signal Scorecard. "
            "Eseguire il calcolo IC prima (ICRollingCalculator)."
        )
        return

    # ── Metriche riassuntive ───────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)

    total_signals = df["signal_id"].nunique() if "signal_id" in df.columns else 0

    if "is_significant" in df.columns and "signal_id" in df.columns:
        significant_ids = df.loc[df["is_significant"] == True, "signal_id"].unique()  # noqa: E712
        n_significant = len(significant_ids)
    else:
        n_significant = 0

    if "is_stale" in df.columns and "signal_id" in df.columns:
        stale_ids = df.loc[df["is_stale"] == True, "signal_id"].unique()  # noqa: E712
        n_stale = len(stale_ids)
    else:
        n_stale = 0

    avg_ic = df["ic_mean"].mean() if "ic_mean" in df.columns else 0.0

    col1.metric("Segnali Totali", total_signals)
    col2.metric("Significativi", n_significant)
    col3.metric("Stale", n_stale, delta=f"-{n_stale}" if n_stale > 0 else None,
                delta_color="inverse")
    col4.metric("IC Medio", f"{avg_ic:.4f}")

    # ── Tabella dettagliata ────────────────────────────────────────────────────
    st.subheader("Scorecard Dettagliata")

    latest = df.groupby("signal_id").first().reset_index() if "signal_id" in df.columns else df
    display_cols = [
        c for c in [
            "signal_id", "ic_mean", "ic_tstat", "hit_rate",
            "alpha_decay_hl", "is_significant", "is_stale", "staleness_days",
        ]
        if c in latest.columns
    ]
    if display_cols:
        st.dataframe(latest[display_cols], use_container_width=True)
    else:
        st.dataframe(latest, use_container_width=True)

    # ── Trend IC per segnale ───────────────────────────────────────────────────
    st.subheader("Trend IC per Segnale")

    if "ic_mean" in df.columns and "snapshot_date" in df.columns and "signal_id" in df.columns:
        top_signals = df["signal_id"].unique()[:6]  # max 6 per leggibilità
        pivot = df[df["signal_id"].isin(top_signals)].pivot_table(
            index="snapshot_date", columns="signal_id", values="ic_mean"
        )
        if not pivot.empty:
            st.line_chart(pivot)
        else:
            st.info("Dati IC non sufficienti per il grafico trend.")
    else:
        st.info("Colonne snapshot_date / ic_mean non presenti nel dataset.")

    # ── Hit rate comparison ────────────────────────────────────────────────────
    st.subheader("Hit Rate per Segnale")

    if "hit_rate" in df.columns and "signal_id" in df.columns:
        hr = (
            df.groupby("signal_id")["hit_rate"]
            .mean()
            .reset_index()
            .rename(columns={"hit_rate": "hit_rate_avg"})
            .sort_values("hit_rate_avg", ascending=False)
        )
        if not hr.empty:
            st.bar_chart(hr.set_index("signal_id")["hit_rate_avg"])
    else:
        st.info("Colonna hit_rate non disponibile.")

    # ── Alpha Decay Halflife ───────────────────────────────────────────────────
    if "alpha_decay_hl" in df.columns and "signal_id" in df.columns:
        st.subheader("Alpha Decay Halflife (giorni)")
        decay = (
            df.groupby("signal_id")["alpha_decay_hl"]
            .mean()
            .reset_index()
            .sort_values("alpha_decay_hl", ascending=True)
        )
        if not decay.empty:
            st.bar_chart(decay.set_index("signal_id")["alpha_decay_hl"])

    st.caption(
        "Dati letti da DuckDB · tabella signal_scorecard · "
        "Premere 🔄 Aggiorna per ricaricare"
    )
