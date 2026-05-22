# ruff: noqa: N999
"""Q16 — Backtesting Pro (WFO equity curve, PSR, FDR, fold metrics).

Legge da DuckDB: tabelle wfo_results e model_registry.
Zero API call (Regola 12).
"""
from __future__ import annotations

__version__ = "16.0.0"
__all__ = ["body_q16_backtesting_pro"]

# ─── Soglie (Regola 7) ────────────────────────────────────────────────────────
_PSR_GREEN_MIN     = 0.95   # Probabilistic Sharpe Ratio: accettabile se > 95%
_SHARPE_BENCH      = 0.0    # Sharpe benchmark OOS (almeno positivo)
_FDR_ALPHA         = 0.05   # livello di significatività per FDR Benjamini-Hochberg


# ─── Public loaders ──────────────────────────────────────────────────────────

def load_wfo():
    """Carica wfo_results da DuckDB."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        return db.execute(
            "SELECT * FROM wfo_results ORDER BY model_id, fold_index"
        ).df()
    except Exception:
        return pd.DataFrame()


def load_models():
    """Carica model_registry da DuckDB."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        return db.execute(
            "SELECT model_id, model_type, target_metric, psr, sharpe_predictive, "
            "directional_acc, is_active, is_baseline_beaten "
            "FROM model_registry ORDER BY psr DESC NULLS LAST"
        ).df()
    except Exception:
        return pd.DataFrame()


def compute_fdr_survivors(models_df, alpha: float = _FDR_ALPHA):
    """Applica correzione Benjamini-Hochberg (FDR) sui p-value dei modelli.

    Ritorna il DataFrame con colonna is_fdr_survivor aggiunta.
    """
    import numpy as np
    import pandas as pd

    if models_df.empty or "psr" not in models_df.columns:
        return models_df

    df = models_df.copy()
    # PSR ≈ Prob(Sharpe > 0); p-value ≈ 1 - PSR
    df["pvalue"] = 1.0 - df["psr"].clip(0.0, 1.0)
    n = len(df)
    df_sorted = df.sort_values("pvalue").reset_index(drop=True)
    ranks = np.arange(1, n + 1)
    bh_threshold = ranks * alpha / n
    df_sorted["is_fdr_survivor"] = df_sorted["pvalue"] <= bh_threshold
    return df_sorted


# ─── Streamlit body ───────────────────────────────────────────────────────────

def body_q16_backtesting_pro(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    from presentation.ui.cache_policy import CACHE_TTL

    st.title("⚡ Q16 — Backtesting Pro")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="backtesting_pro_refresh"):
            st.cache_data.clear()
            st.rerun()

    @st.cache_data(ttl=CACHE_TTL.SIGNALS)
    def _load_wfo():
        return load_wfo()

    @st.cache_data(ttl=CACHE_TTL.SIGNALS)
    def _load_models():
        return load_models()

    wfo_df = _load_wfo()
    models_df = _load_models()

    if wfo_df.empty and models_df.empty:
        st.info(
            "Nessun dato Backtesting Pro disponibile. "
            "Eseguire la pipeline WFORunner per generare i risultati."
        )
        return

    # ── Riepilogo modelli ──────────────────────────────────────────────────────
    if not models_df.empty:
        col1, col2, col3, col4 = st.columns(4)
        n_models = len(models_df)
        n_active = int(models_df["is_active"].sum()) if "is_active" in models_df.columns else 0
        n_beat = int(models_df["is_baseline_beaten"].sum()) \
            if "is_baseline_beaten" in models_df.columns else 0
        avg_psr = models_df["psr"].mean() if "psr" in models_df.columns else None

        col1.metric("Modelli Totali", n_models)
        col2.metric("Attivi", n_active)
        col3.metric("Baseline Beaten", n_beat)
        col4.metric("PSR Medio", f"{avg_psr:.2%}" if avg_psr is not None else "N/D")

    # ── WFO Equity Curve (per modello) ────────────────────────────────────────
    st.subheader("WFO Equity Curve — Ritorni OOS Cumulati")

    if not wfo_df.empty:
        model_ids = wfo_df["model_id"].unique().tolist() if "model_id" in wfo_df.columns else []

        if model_ids:
            selected_model = st.selectbox(
                "Seleziona Modello", model_ids, key="bt_model_sel"
            )
            model_wfo = wfo_df[wfo_df["model_id"] == selected_model].copy()

            if not model_wfo.empty and "fold_return_oos" in model_wfo.columns:
                model_wfo = model_wfo.sort_values("fold_index") \
                    if "fold_index" in model_wfo.columns else model_wfo
                model_wfo["equity_curve"] = (1 + model_wfo["fold_return_oos"]).cumprod()
                idx_col = "fold_index" if "fold_index" in model_wfo.columns else None
                eq_chart = (
                    model_wfo.set_index(idx_col)["equity_curve"]
                    if idx_col else model_wfo["equity_curve"]
                )
                st.line_chart(eq_chart)
            else:
                st.info("Colonna fold_return_oos non disponibile per l'equity curve.")

        # ── Fold metrics table ─────────────────────────────────────────────────
        st.subheader("Metriche per Fold")

        fold_cols = [
            c for c in [
                "model_id", "fold_index", "train_start", "train_end",
                "test_start", "test_end", "sharpe_oos",
                "directional_acc_oos", "mse_oos", "fold_return_oos",
            ]
            if c in wfo_df.columns
        ]
        if fold_cols:
            st.dataframe(wfo_df[fold_cols], use_container_width=True)
    else:
        st.info("Nessun WFO result disponibile.")

    # ── PSR bar chart ──────────────────────────────────────────────────────────
    st.subheader("Probabilistic Sharpe Ratio (PSR) per Modello")

    if not models_df.empty and "psr" in models_df.columns and "model_id" in models_df.columns:
        psr_data = models_df[["model_id", "psr"]].dropna().set_index("model_id")
        st.bar_chart(psr_data)
        st.caption(
            f"Linea verde (ideale): PSR ≥ {_PSR_GREEN_MIN:.0%}. "
            "PSR = Prob(Sharpe OOS > 0) corretta per lunghezza campione e skewness."
        )
    else:
        st.info("Colonna PSR non disponibile nel Model Registry.")

    # ── FDR Correction ────────────────────────────────────────────────────────
    st.subheader(f"FDR Correction (Benjamini-Hochberg α={_FDR_ALPHA})")

    if not models_df.empty and "psr" in models_df.columns:
        fdr_df = compute_fdr_survivors(models_df, alpha=_FDR_ALPHA)
        n_survivors = int(fdr_df["is_fdr_survivor"].sum()) \
            if "is_fdr_survivor" in fdr_df.columns else 0
        n_total = len(fdr_df)
        st.metric(
            "Strategie che superano FDR",
            f"{n_survivors} / {n_total}",
        )
        fdr_cols = [
            c for c in ["model_id", "model_type", "psr", "pvalue", "is_fdr_survivor"]
            if c in fdr_df.columns
        ]
        if fdr_cols:
            st.dataframe(fdr_df[fdr_cols], use_container_width=True)
    else:
        st.info(
            "FDR correction richiede la colonna PSR nel Model Registry. "
            "Eseguire PSRCalculator prima."
        )

    st.caption(
        "Dati letti da DuckDB · tabelle wfo_results, model_registry · "
        "Premere 🔄 Aggiorna per ricaricare"
    )
