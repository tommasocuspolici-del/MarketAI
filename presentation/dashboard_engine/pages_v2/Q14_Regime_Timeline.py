# ruff: noqa: N999
"""Q14 — Regime Timeline (macro regime, CUSUM change points, ritorni condizionali).

Legge da DuckDB: tabelle macro_regime_timeline e conditional_returns.
Zero API call (Regola 12).
"""
from __future__ import annotations

__version__ = "14.0.0"
__all__ = ["body_q14_regime_timeline"]

# ─── Colori regime (Regola 7 — zero magic numbers inline) ────────────────────
_REGIME_COLORS: dict[str, str] = {
    "expansion":   "#22c55e",
    "recovery":    "#3b82f6",
    "slowdown":    "#f59e0b",
    "contraction": "#ef4444",
}
_REGIME_LABELS_IT: dict[str, str] = {
    "expansion":   "Espansione",
    "recovery":    "Ripresa",
    "slowdown":    "Rallentamento",
    "contraction": "Contrazione",
}


# ─── Public loaders ──────────────────────────────────────────────────────────

def load_regime_timeline():
    """Carica macro_regime_timeline da DuckDB."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        return db.execute(
            "SELECT * FROM macro_regime_timeline ORDER BY date DESC"
        ).df()
    except Exception:
        return pd.DataFrame()


def load_conditional_returns():
    """Carica conditional_returns da DuckDB."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        return db.execute(
            "SELECT * FROM conditional_returns ORDER BY regime, asset"
        ).df()
    except Exception:
        return pd.DataFrame()


# ─── Streamlit body ───────────────────────────────────────────────────────────

def body_q14_regime_timeline(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    from presentation.ui.cache_policy import CACHE_TTL

    st.title("🗓️ Q14 — Regime Timeline")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="regime_timeline_refresh"):
            st.cache_data.clear()
            st.rerun()

    @st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION)
    def _load_timeline():
        return load_regime_timeline()

    @st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION)
    def _load_cond():
        return load_conditional_returns()

    df = _load_timeline()
    cond_df = _load_cond()

    if df.empty:
        st.info(
            "Nessun dato nel Regime Timeline. "
            "Eseguire la pipeline HMM regime detection."
        )
        return

    # ── Regime corrente ────────────────────────────────────────────────────────
    st.subheader("Regime Corrente")

    latest_row = df.iloc[0] if not df.empty else None
    if latest_row is not None and "regime" in df.columns:
        current_regime = str(latest_row["regime"]).lower()
        color = _REGIME_COLORS.get(current_regime, "#6b7280")
        label_it = _REGIME_LABELS_IT.get(current_regime, current_regime.upper())
        confidence = latest_row.get("confidence") if "confidence" in df.columns else None
        conf_str = f" · confidenza: {float(confidence):.1%}" if confidence is not None else ""

        st.markdown(
            f"""
            <div style="background:#1e293b;border-radius:12px;padding:16px 20px;
                        margin-bottom:20px;border-left:4px solid {color}">
              <div style="font-size:0.85rem;color:#94a3b8;margin-bottom:4px">
                REGIME MACRO CORRENTE
              </div>
              <div style="font-size:2rem;font-weight:700;color:{color}">
                {label_it}
              </div>
              <div style="font-size:0.9rem;color:#cbd5e1;margin-top:4px">
                {latest_row.get("date", "")}{conf_str}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── Distribuzione probabilità regime ──────────────────────────────────────
    prob_cols = [c for c in df.columns if c.startswith("prob_")]
    if prob_cols and latest_row is not None:
        st.subheader("Probabilità Regime (ultimo snapshot)")
        probs = {c.replace("prob_", "").capitalize(): float(latest_row[c])
                 for c in prob_cols if latest_row[c] is not None}
        if probs:
            import pandas as pd
            prob_df = pd.DataFrame(
                list(probs.items()), columns=["Regime", "Probabilità"]
            ).set_index("Regime")
            col_pie, col_bar = st.columns(2)
            with col_pie:
                st.bar_chart(prob_df)
            with col_bar:
                for regime, prob in probs.items():
                    color_r = _REGIME_COLORS.get(regime.lower(), "#6b7280")
                    st.markdown(
                        f'<div style="margin-bottom:6px">'
                        f'<span style="color:{color_r};font-weight:600">{regime}</span>'
                        f': {prob:.1%}</div>',
                        unsafe_allow_html=True,
                    )

    # ── Timeline storica ───────────────────────────────────────────────────────
    st.subheader("Timeline Storica")

    if "regime" in df.columns and "date" in df.columns:
        # Codifica numerica per il grafico (line chart per semplicità)
        regime_map = {"expansion": 2, "recovery": 1, "slowdown": -1, "contraction": -2}
        timeline_plot = df[["date", "regime"]].copy()
        timeline_plot["regime_score"] = timeline_plot["regime"].str.lower().map(
            lambda r: regime_map.get(r, 0)
        )
        timeline_plot = timeline_plot.sort_values("date")
        if not timeline_plot.empty:
            st.line_chart(timeline_plot.set_index("date")["regime_score"])
            st.caption(
                "Scala: Espansione=2 · Ripresa=1 · Rallentamento=-1 · Contrazione=-2"
            )

    # ── CUSUM change points ────────────────────────────────────────────────────
    cusum_cols = [c for c in df.columns if "cusum" in c.lower() or "change_point" in c.lower()]
    if cusum_cols:
        st.subheader("CUSUM Change Points")
        change_points = df[df[cusum_cols[0]] == True] if cusum_cols else None  # noqa: E712
        if change_points is not None and not change_points.empty:
            cp_cols = ["date", "regime"] + [c for c in cusum_cols if c in change_points.columns]
            st.dataframe(change_points[cp_cols], use_container_width=True)
        else:
            st.info("Nessun change point rilevato nel periodo corrente.")

    # ── Ritorni condizionali ───────────────────────────────────────────────────
    st.subheader("Ritorni Condizionali per Regime")

    if cond_df.empty:
        st.info("Nessun dato conditional_returns disponibile.")
    else:
        ret_cols = [
            c for c in ["regime", "asset", "mean_return", "volatility", "sharpe", "n_obs"]
            if c in cond_df.columns
        ]
        if ret_cols:
            if "regime" in cond_df.columns:
                regimes = cond_df["regime"].unique()
                for regime in regimes:
                    r_df = cond_df[cond_df["regime"] == regime]
                    color = _REGIME_COLORS.get(str(regime).lower(), "#6b7280")
                    label = _REGIME_LABELS_IT.get(str(regime).lower(), str(regime))
                    st.markdown(
                        f'<h4 style="color:{color}">{label}</h4>',
                        unsafe_allow_html=True,
                    )
                    st.dataframe(r_df[ret_cols], use_container_width=True)
            else:
                st.dataframe(cond_df[ret_cols], use_container_width=True)

    st.caption(
        "Dati letti da DuckDB · tabelle macro_regime_timeline, conditional_returns · "
        "Premere 🔄 Aggiorna per ricaricare"
    )
