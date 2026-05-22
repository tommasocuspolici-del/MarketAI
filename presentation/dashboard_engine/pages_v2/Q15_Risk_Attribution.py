# ruff: noqa: N999
"""Q15 — Risk Attribution (VaR/CVaR, component VaR, liquidità).

Legge da DuckDB: tabelle portfolio_risk_metrics e position_risk_contribution.
Zero API call (Regola 12).
"""
from __future__ import annotations

__version__ = "15.0.0"
__all__ = ["body_q15_risk_attribution"]

# ─── Soglie (Regola 7) ────────────────────────────────────────────────────────
_LIQUIDITY_RED_DAYS   = 10   # giorni per liquidare — soglia critica
_LIQUIDITY_YELLOW_DAYS = 5   # soglia attenzione
_VAR_WARN_PCT          = 0.05  # VaR > 5% del portfolio → attenzione


# ─── Public loaders ──────────────────────────────────────────────────────────

def load_portfolio_risk():
    """Carica portfolio_risk_metrics da DuckDB."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        return db.execute(
            "SELECT * FROM portfolio_risk_metrics ORDER BY computed_at DESC LIMIT 1"
        ).df()
    except Exception:
        return pd.DataFrame()


def load_position_risk():
    """Carica position_risk_contribution da DuckDB."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        return db.execute(
            "SELECT * FROM position_risk_contribution ORDER BY var_contribution DESC"
        ).df()
    except Exception:
        return pd.DataFrame()


# ─── Streamlit body ───────────────────────────────────────────────────────────

def body_q15_risk_attribution(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    from presentation.ui.cache_policy import CACHE_TTL

    st.title("🛡️ Q15 — Risk Attribution")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="risk_attribution_refresh"):
            st.cache_data.clear()
            st.rerun()

    @st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS)
    def _load_portfolio():
        return load_portfolio_risk()

    @st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS)
    def _load_positions():
        return load_position_risk()

    risk_df = _load_portfolio()
    pos_df = _load_positions()

    if risk_df.empty and pos_df.empty:
        st.info(
            "Nessun dato Risk Attribution disponibile. "
            "Eseguire la pipeline CVaR e risk contribution."
        )
        return

    # ── Metriche portafoglio ───────────────────────────────────────────────────
    st.subheader("Metriche Portafoglio")

    if not risk_df.empty:
        row = risk_df.iloc[0]
        col1, col2, col3, col4 = st.columns(4)

        var_95 = row.get("var_95") if "var_95" in risk_df.columns else None
        var_99 = row.get("var_99") if "var_99" in risk_df.columns else None
        cvar_95 = row.get("cvar_95") if "cvar_95" in risk_df.columns else None
        cvar_99 = row.get("cvar_99") if "cvar_99" in risk_df.columns else None

        col1.metric("VaR 95%", f"{float(var_95):.2%}" if var_95 is not None else "N/D")
        col2.metric("VaR 99%", f"{float(var_99):.2%}" if var_99 is not None else "N/D")
        col3.metric("CVaR 95%", f"{float(cvar_95):.2%}" if cvar_95 is not None else "N/D")
        col4.metric("CVaR 99%", f"{float(cvar_99):.2%}" if cvar_99 is not None else "N/D")

        # CVaR per regime
        regime_cvar_cols = [c for c in risk_df.columns if "cvar" in c.lower() and "regime" in c.lower()]
        if regime_cvar_cols:
            st.subheader("CVaR Condizionale per Regime")
            cvar_regime = {c.replace("cvar_", "").replace("_", " ").title(): float(row[c])
                           for c in regime_cvar_cols if row[c] is not None}
            if cvar_regime:
                import pandas as pd
                cr_df = pd.DataFrame(
                    list(cvar_regime.items()), columns=["Regime", "CVaR"]
                ).set_index("Regime")
                st.bar_chart(cr_df)
    else:
        st.info("Metriche portafoglio aggregate non disponibili.")

    # ── Component VaR (top 10) ─────────────────────────────────────────────────
    st.subheader("Component VaR — Top 10 Posizioni per Contributo al Rischio")

    if pos_df.empty:
        st.info("Nessun dato position_risk_contribution disponibile.")
    else:
        top10 = pos_df.head(10)
        display_cols = [
            c for c in [
                "ticker", "weight", "var_contribution", "cvar_contribution",
                "marginal_var", "beta", "days_to_liquidate",
            ]
            if c in top10.columns
        ]
        if display_cols:
            st.dataframe(top10[display_cols], use_container_width=True)

            if "var_contribution" in top10.columns and "ticker" in top10.columns:
                st.bar_chart(top10.set_index("ticker")["var_contribution"])

    # ── Liquidity heatmap ─────────────────────────────────────────────────────
    if not pos_df.empty and "days_to_liquidate" in pos_df.columns and "ticker" in pos_df.columns:
        st.subheader("Liquidità — Giorni per Liquidare")

        liq_df = pos_df[["ticker", "days_to_liquidate"]].dropna()
        if not liq_df.empty:
            liq_df = liq_df.sort_values("days_to_liquidate", ascending=False)

            # Semaforo liquidità
            def _liq_label(days: float) -> str:
                if days >= _LIQUIDITY_RED_DAYS:
                    return "🔴 ILLIQUIDO"
                if days >= _LIQUIDITY_YELLOW_DAYS:
                    return "🟡 MODERATO"
                return "🟢 LIQUIDO"

            liq_df["stato"] = liq_df["days_to_liquidate"].apply(_liq_label)
            st.dataframe(liq_df, use_container_width=True)
            st.bar_chart(liq_df.set_index("ticker")["days_to_liquidate"])

    # ── Posizioni con VaR elevato ─────────────────────────────────────────────
    if not pos_df.empty and "var_contribution" in pos_df.columns:
        high_var = pos_df[pos_df["var_contribution"] > _VAR_WARN_PCT] \
            if "var_contribution" in pos_df.columns else pos_df.iloc[0:0]
        if not high_var.empty:
            st.warning(
                f"⚠️ {len(high_var)} posizione/i con contributo VaR > {_VAR_WARN_PCT:.0%} "
                "del portafoglio — verificare concentrazione."
            )

    st.caption(
        "Dati letti da DuckDB · tabelle portfolio_risk_metrics, position_risk_contribution · "
        "Premere 🔄 Aggiorna per ricaricare"
    )
