# ruff: noqa: N999
"""Q17 — Vol Surface (VRP, vol regime, VIX term structure, strategy scanner).

Legge da DuckDB: tabelle vol_surface_snapshots, vix_signals, putcall_ratio_daily.
Zero API call (Regola 12).
"""
from __future__ import annotations

__version__ = "17.0.0"
__all__ = ["body_q17_vol_surface"]

# ─── Soglie (Regola 7) ────────────────────────────────────────────────────────
_VRP_RED_ZSCOR      = 2.0   # VRP z-score > 2 = premi elevati (sell vol)
_VRP_GREEN_ZSCOR    = -1.0  # VRP z-score < -1 = premi bassi (buy vol hedge)
_VOL_REGIME_THRESHOLDS: dict[str, tuple[float, float]] = {
    "calm":    (0.0, 15.0),
    "normal":  (15.0, 22.0),
    "high":    (22.0, 30.0),
    "extreme": (30.0, 9999.0),
}
_VOL_REGIME_COLORS: dict[str, str] = {
    "calm":    "#22c55e",
    "normal":  "#3b82f6",
    "high":    "#f59e0b",
    "extreme": "#ef4444",
}


# ─── Public loaders ──────────────────────────────────────────────────────────

def load_vol_surface():
    """Carica vol_surface_snapshots da DuckDB."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        return db.execute(
            "SELECT * FROM vol_surface_snapshots ORDER BY snapshot_at DESC LIMIT 30"
        ).df()
    except Exception:
        return pd.DataFrame()


def load_vix_signals():
    """Carica vix_signals da DuckDB (ultime 90 righe per term structure storica)."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        return db.execute(
            "SELECT * FROM vix_signals ORDER BY computed_at DESC LIMIT 90"
        ).df()
    except Exception:
        return pd.DataFrame()


def load_options_flow():
    """Carica putcall_ratio_daily da DuckDB (ultimi 60 gg)."""
    import pandas as pd
    try:
        from shared.db.duckdb_client import get_duckdb_client
        db = get_duckdb_client()
        return db.execute(
            "SELECT * FROM putcall_ratio_daily ORDER BY date DESC LIMIT 60"
        ).df()
    except Exception:
        return pd.DataFrame()


def classify_vol_regime(vix_level: float | None) -> str:
    """Classifica il regime di volatilità in base al livello VIX."""
    if vix_level is None:
        return "unknown"
    for regime, (low, high) in _VOL_REGIME_THRESHOLDS.items():
        if low <= vix_level < high:
            return regime
    return "extreme"


def get_strategy_recommendations(vol_regime: str, vrp_zscore: float | None) -> list[str]:
    """Restituisce raccomandazioni di strategia options in base a regime e VRP."""
    recs: list[str] = []
    if vol_regime == "calm":
        recs.append("📈 Long straddle / strangle — vol storicamente bassa, possibile spike")
        recs.append("💰 Ratio spread — premi bassi, rischio/rendimento favorevole")
    elif vol_regime == "normal":
        recs.append("⚖️ Iron condor — vol in range, vendere premi ai bordi")
        recs.append("📊 Covered call — generare reddito con posizioni long")
    elif vol_regime == "high":
        recs.append("💵 Short premium — vix elevato → premi attraenti da vendere")
        recs.append("🛡️ Collar — protezione con cap al rialzo")
    elif vol_regime == "extreme":
        recs.append("🔴 Evitare vendita di vol scoperta — rischio coda estremo")
        recs.append("🛡️ Long put — hedging diretto contro ulteriori ribassi")

    if vrp_zscore is not None:
        if vrp_zscore > _VRP_RED_ZSCOR:
            recs.append(f"📉 VRP z-score={vrp_zscore:+.1f} → premi elevati: favorisce short vol")
        elif vrp_zscore < _VRP_GREEN_ZSCOR:
            recs.append(f"📈 VRP z-score={vrp_zscore:+.1f} → premi compressi: favorisce long vol / hedge")

    return recs


# ─── Streamlit body ───────────────────────────────────────────────────────────

def body_q17_vol_surface(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    from presentation.ui.cache_policy import CACHE_TTL

    st.title("🌊 Q17 — Vol Surface")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="vol_surface_refresh"):
            st.cache_data.clear()
            st.rerun()

    @st.cache_data(ttl=CACHE_TTL.MARKET_KPI)
    def _load_surface():
        return load_vol_surface()

    @st.cache_data(ttl=CACHE_TTL.MARKET_KPI)
    def _load_vix():
        return load_vix_signals()

    @st.cache_data(ttl=CACHE_TTL.MARKET_KPI)
    def _load_opts():
        return load_options_flow()

    surf_df = _load_surface()
    vix_df = _load_vix()
    opts_df = _load_opts()

    all_empty = surf_df.empty and vix_df.empty and opts_df.empty
    if all_empty:
        st.info(
            "Nessun dato Vol Surface disponibile. "
            "Eseguire la pipeline OptionsFlowFetcher e VixSignalCalculator."
        )
        return

    # ── VIX corrente e regime ─────────────────────────────────────────────────
    st.subheader("Regime Volatilità")

    vix_level = None
    vix_zscore = None
    vix_regime_raw = None

    if not vix_df.empty:
        latest_vix = vix_df.iloc[0]
        vix_level = float(latest_vix["vix_level"]) if "vix_level" in vix_df.columns else None
        vix_zscore = float(latest_vix["vix_zscore"]) if "vix_zscore" in vix_df.columns else None
        vix_regime_raw = str(latest_vix["regime"]) if "regime" in vix_df.columns else None

    vol_regime = classify_vol_regime(vix_level)
    regime_color = _VOL_REGIME_COLORS.get(vol_regime, "#6b7280")
    regime_label = vol_regime.upper()

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("VIX Livello", f"{vix_level:.1f}" if vix_level is not None else "N/D")
    col_b.metric("VIX Z-Score", f"{vix_zscore:+.2f}" if vix_zscore is not None else "N/D")
    col_c.metric("Regime Vol", regime_label)

    st.markdown(
        f"""
        <div style="background:#1e293b;border-radius:10px;padding:12px 16px;
                    margin-bottom:16px;border-left:4px solid {regime_color}">
          <span style="color:{regime_color};font-weight:700;font-size:1.1rem">
            {regime_label}
          </span>
          <span style="color:#94a3b8;margin-left:12px">
            VIX = {f"{vix_level:.1f}" if vix_level is not None else "N/D"}
            {f"  ·  z-score {vix_zscore:+.2f}" if vix_zscore is not None else ""}
          </span>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── VRP ────────────────────────────────────────────────────────────────────
    st.subheader("Volatility Risk Premium (VRP)")

    vrp_zscore = None
    vrp_value = None

    if not surf_df.empty:
        latest_surf = surf_df.iloc[0]
        vrp_value = float(latest_surf["vrp"]) if "vrp" in surf_df.columns else None
        vrp_zscore = float(latest_surf["vrp_zscore"]) \
            if "vrp_zscore" in surf_df.columns else None
        contango_pct = float(latest_surf["contango_pct"]) \
            if "contango_pct" in surf_df.columns else None
        skew_index = float(latest_surf["skew_index"]) \
            if "skew_index" in surf_df.columns else None

        col_v1, col_v2, col_v3, col_v4 = st.columns(4)
        col_v1.metric("VRP", f"{vrp_value:.2f}" if vrp_value is not None else "N/D")
        col_v2.metric("VRP Z-Score", f"{vrp_zscore:+.2f}" if vrp_zscore is not None else "N/D")
        col_v3.metric("Contango %", f"{contango_pct:.1f}%" if contango_pct is not None else "N/D")
        col_v4.metric("Skew Index", f"{skew_index:.3f}" if skew_index is not None else "N/D")

        # Storico VRP
        if "vrp" in surf_df.columns and "snapshot_at" in surf_df.columns:
            vrp_hist = surf_df[["snapshot_at", "vrp"]].dropna().sort_values("snapshot_at")
            if not vrp_hist.empty:
                st.line_chart(vrp_hist.set_index("snapshot_at")["vrp"])
    else:
        st.info("Dati Vol Surface non disponibili.")

    # ── VIX Term Structure ─────────────────────────────────────────────────────
    st.subheader("VIX Term Structure")

    if not vix_df.empty:
        term_cols = [c for c in ["vix_level", "vix_9d", "vxv", "vix3m", "vix6m"]
                     if c in vix_df.columns]
        if len(term_cols) >= 2:
            latest_term = vix_df.iloc[0][term_cols]
            import pandas as pd
            term_df = pd.DataFrame(
                {"Scadenza": term_cols, "IV": [latest_term[c] for c in term_cols]}
            ).set_index("Scadenza")
            st.bar_chart(term_df)
            st.caption(
                "Struttura a termine implicita: vix_9d (9gg) → vix_level (30gg) "
                "→ vxv/vix3m (93gg) → vix6m (180gg)"
            )

        # Serie storica VIX
        if "vix_level" in vix_df.columns and "computed_at" in vix_df.columns:
            vix_hist = vix_df[["computed_at", "vix_level"]].dropna() \
                .sort_values("computed_at")
            if not vix_hist.empty:
                st.subheader("Storico VIX")
                st.line_chart(vix_hist.set_index("computed_at")["vix_level"])
    else:
        st.info("Dati VIX non disponibili.")

    # ── IV Skew storico ────────────────────────────────────────────────────────
    if not opts_df.empty and "iv_skew_25d" in opts_df.columns and "date" in opts_df.columns:
        st.subheader("IV Skew 25-Delta (storico)")
        skew_hist = opts_df[["date", "iv_skew_25d"]].dropna().sort_values("date")
        if not skew_hist.empty:
            st.line_chart(skew_hist.set_index("date")["iv_skew_25d"])
            st.caption(
                "IV Skew 25d > 0%: put 25-delta più cara di call 25-delta (put premium / bearish hedge)"
            )

    # ── Raccomandazioni strategia options ─────────────────────────────────────
    st.subheader("Raccomandazioni Strategia Options")

    recommendations = get_strategy_recommendations(vol_regime, vrp_zscore)
    if recommendations:
        for rec in recommendations:
            st.markdown(f"- {rec}")
    else:
        st.info("Nessuna raccomandazione disponibile per il regime corrente.")

    st.caption(
        "Dati letti da DuckDB · tabelle vol_surface_snapshots, vix_signals, putcall_ratio_daily · "
        "Premere 🔄 Aggiorna per ricaricare"
    )
