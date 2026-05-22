# ruff: noqa: N999
"""Q13 — Model Registry (gestione modelli previsionali, WFO, baseline beat).

Legge da DuckDB: tabelle model_registry e wfo_results.
Zero API call (Regola 12).
"""
from __future__ import annotations

__version__ = "13.0.0"
__all__ = ["body_q13_model_registry"]


# ─── Soglie (Regola 7 — zero magic numbers inline) ────────────────────────────
_SHARPE_GREEN  = 0.5
_DACC_GREEN    = 0.55  # directional accuracy
_MSE_YELLOW    = 0.1


# ─── Public loaders (testabili senza Streamlit) ───────────────────────────────

def load_model_registry():
    """Carica model_registry da DuckDB. Ritorna DataFrame (anche vuoto)."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        return db.execute(
            "SELECT * FROM model_registry ORDER BY trained_at DESC"
        ).df()
    except Exception:
        return pd.DataFrame()


def load_wfo_results(model_id: str | None = None):
    """Carica wfo_results, opzionalmente filtrati per model_id."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        if model_id:
            return db.execute(
                "SELECT * FROM wfo_results WHERE model_id = ? ORDER BY fold_index",
                [model_id],
            ).df()
        return db.execute(
            "SELECT * FROM wfo_results ORDER BY model_id, fold_index"
        ).df()
    except Exception:
        return pd.DataFrame()


# ─── Streamlit body ───────────────────────────────────────────────────────────

def body_q13_model_registry(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    from presentation.ui.cache_policy import CACHE_TTL

    st.title("🗂️ Q13 — Model Registry")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="model_registry_refresh"):
            st.cache_data.clear()
            st.rerun()

    @st.cache_data(ttl=CACHE_TTL.SIGNALS)
    def _load_registry():
        return load_model_registry()

    @st.cache_data(ttl=CACHE_TTL.SIGNALS)
    def _load_wfo(model_id: str | None = None):
        return load_wfo_results(model_id)

    df = _load_registry()

    if df.empty:
        st.info(
            "Nessun modello nel Registry. "
            "Eseguire la pipeline WFO (WFORunner) per registrare i modelli."
        )
        return

    # ── Filtri ────────────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns(3)

    model_types = ["Tutti"] + sorted(df["model_type"].dropna().unique().tolist()) \
        if "model_type" in df.columns else ["Tutti"]
    selected_type = col_f1.selectbox("Tipo Modello", model_types, key="mreg_type")

    is_active_opt = col_f2.selectbox("Stato", ["Tutti", "Attivo", "Inattivo"],
                                      key="mreg_active")
    beat_opt = col_f3.selectbox("Baseline Beat", ["Tutti", "Sì", "No"],
                                 key="mreg_beat")

    filtered = df.copy()
    if selected_type != "Tutti" and "model_type" in filtered.columns:
        filtered = filtered[filtered["model_type"] == selected_type]
    if is_active_opt == "Attivo" and "is_active" in filtered.columns:
        filtered = filtered[filtered["is_active"] == True]  # noqa: E712
    elif is_active_opt == "Inattivo" and "is_active" in filtered.columns:
        filtered = filtered[filtered["is_active"] == False]  # noqa: E712
    if beat_opt == "Sì" and "is_baseline_beaten" in filtered.columns:
        filtered = filtered[filtered["is_baseline_beaten"] == True]  # noqa: E712
    elif beat_opt == "No" and "is_baseline_beaten" in filtered.columns:
        filtered = filtered[filtered["is_baseline_beaten"] == False]  # noqa: E712

    # ── Metriche riassuntive ───────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Modelli Totali", len(df))
    n_active = int(df["is_active"].sum()) if "is_active" in df.columns else 0
    n_beat = int(df["is_baseline_beaten"].sum()) if "is_baseline_beaten" in df.columns else 0
    avg_dacc = df["directional_acc"].mean() if "directional_acc" in df.columns else 0.0
    col2.metric("Attivi", n_active)
    col3.metric("Baseline Beaten", n_beat)
    col4.metric("Dir. Accuracy Media", f"{avg_dacc:.2%}" if avg_dacc else "N/D")

    # ── Tabella modelli ────────────────────────────────────────────────────────
    st.subheader("Modelli Registrati")

    display_cols = [
        c for c in [
            "model_id", "model_type", "target_metric", "mse_oos",
            "directional_acc", "sharpe_predictive", "is_active",
            "is_baseline_beaten", "trained_at",
        ]
        if c in filtered.columns
    ]
    if display_cols:
        st.dataframe(filtered[display_cols], use_container_width=True)
    else:
        st.dataframe(filtered, use_container_width=True)

    # ── WFO Results per modello selezionato ───────────────────────────────────
    st.subheader("Walk-Forward Results")

    model_ids = filtered["model_id"].dropna().unique().tolist() \
        if "model_id" in filtered.columns else []

    if not model_ids:
        st.info("Nessun modello disponibile per i WFO results.")
    else:
        selected_model = st.selectbox("Seleziona Modello", model_ids,
                                       key="mreg_model_sel")
        wfo_df = _load_wfo(selected_model)

        if wfo_df.empty:
            st.info(f"Nessun WFO result per il modello '{selected_model}'.")
        else:
            wfo_cols = [
                c for c in [
                    "fold_index", "train_start", "train_end",
                    "test_start", "test_end", "sharpe_oos",
                    "directional_acc_oos", "mse_oos", "n_samples",
                ]
                if c in wfo_df.columns
            ]
            st.dataframe(wfo_df[wfo_cols] if wfo_cols else wfo_df,
                         use_container_width=True)

            if "sharpe_oos" in wfo_df.columns and "fold_index" in wfo_df.columns:
                st.subheader("Sharpe OOS per Fold")
                st.bar_chart(wfo_df.set_index("fold_index")["sharpe_oos"])

    # ── Performance scatter: Sharpe vs Directional Acc ────────────────────────
    st.subheader("Mappa Performance Modelli")

    if "sharpe_predictive" in df.columns and "directional_acc" in df.columns:
        import pandas as pd
        scatter_df = df[["model_id", "sharpe_predictive", "directional_acc"]].dropna()
        if not scatter_df.empty:
            st.scatter_chart(
                scatter_df,
                x="sharpe_predictive",
                y="directional_acc",
                color=None,
            )
    else:
        st.info("Colonne sharpe_predictive / directional_acc non disponibili.")

    st.caption(
        "Dati letti da DuckDB · tabelle model_registry, wfo_results · "
        "Premere 🔄 Aggiorna per ricaricare"
    )
