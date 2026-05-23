# ruff: noqa: N999
"""M2 — Yield Curve & Credit Spreads (v8.0). Sostituisce E3_Bonds.py."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_m2_yield_curve"]


def body_m2_yield_curve(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.components.yield_curve_chart import render_yield_curve_chart

    require_auth()
    st.title("🌍 Macro — Yield Curve & Credit Spreads")
    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("📊 Calcola", key="m2_compute",
                     help="Calcola yield curve e credit spreads dai dati FRED in DB "
                          "(richiede che FRED sia già stato caricato da M1)"):
            with st.spinner("Calcolo in corso…"):
                try:
                    from datetime import date, datetime, timezone
                    from scipy.stats import norm
                    from shared.db.duckdb_client import get_duckdb_client
                    from shared.db.macro_repo import get_macro_repository

                    repo = get_macro_repository()
                    db = get_duckdb_client()

                    def _latest(sid: str):
                        obs = repo.read_latest_macro(sid)
                        return float(obs["value"]) if obs and obs.get("value") is not None else None

                    y_3m   = _latest("DGS3MO"); y_2y   = _latest("DGS2")
                    y_5y   = _latest("DGS5");   y_10y  = _latest("DGS10")
                    y_30y  = _latest("DGS30");  t10y2y = _latest("T10Y2Y")
                    t10y3m = _latest("T10Y3M"); be10y  = _latest("T10YIE")
                    ff     = _latest("FEDFUNDS")

                    rec_prob = None
                    if t10y3m is not None:
                        rec_prob = float(norm.cdf(-0.6022 + -0.5517 * t10y3m))

                    curve_regime = None
                    if t10y2y is not None:
                        if t10y2y < -0.5:  curve_regime = "inverted"
                        elif t10y2y < 0:   curve_regime = "flat"
                        elif t10y2y > 1.5: curve_regime = "steep"
                        else:              curve_regime = "normal"

                    db.execute(
                        "INSERT OR REPLACE INTO yield_curve_snapshots "
                        "(snapshot_date, y_3m, y_2y, y_5y, y_10y, y_30y, "
                        "spread_10y_2y, spread_10y_3m, breakeven_10y, fed_funds, "
                        "inversion_signal, recession_prob_12m, curve_regime) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [date.today(), y_3m, y_2y, y_5y, y_10y, y_30y,
                         t10y2y, t10y3m, be10y, ff,
                         t10y2y is not None and t10y2y < 0, rec_prob, curve_regime],
                    )

                    hy_oas = _latest("BAMLH0A0HYM2"); ig_oas = _latest("BAMLC0A0CM")
                    ted    = _latest("TEDRATE");      nfci   = _latest("NFCI")
                    hy_ig  = (hy_oas / ig_oas) if (hy_oas and ig_oas and ig_oas > 0) else None

                    if hy_oas is None:   stress, score = "unknown",  0.0
                    elif hy_oas < 350:   stress, score = "low",      0.3
                    elif hy_oas < 500:   stress, score = "moderate", 0.0
                    elif hy_oas < 700:   stress, score = "elevated", -0.4
                    else:                stress, score = "crisis",   -0.9

                    db.execute(
                        "INSERT OR REPLACE INTO credit_spread_signals "
                        "(computed_at, hy_oas, ig_oas, hy_ig_ratio, ted_spread, "
                        "nfci, stress_level, stress_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        [datetime.now(timezone.utc), hy_oas, ig_oas, hy_ig, ted, nfci, stress, score],
                    )

                    parts = []
                    if y_10y is not None:    parts.append(f"10Y: {y_10y:.2f}%")
                    if curve_regime:         parts.append(f"Regime: {curve_regime}")
                    if rec_prob is not None: parts.append(f"P(Rec): {rec_prob*100:.1f}%")
                    if hy_oas is not None:   parts.append(f"HY OAS: {hy_oas:.0f}bps")
                    st.success("✅ " + (" · ".join(parts) if parts else "Calcolato"))
                    if y_10y is None and hy_oas is None:
                        st.info("Nessun dato FRED trovato — carica prima le serie da M1 → 📥 Carica da FRED.")
                    st.cache_data.clear()
                    st.rerun()
                except Exception as exc:
                    st.error(f"Errore calcolo: {type(exc).__name__}: {exc}")
    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="m2_refresh"):
            st.cache_data.clear()
            st.rerun()

    col1, col2 = st.columns([3, 2])

    with col1:
        st.subheader("📐 Curva Yield")
        try:
            from shared.db.macro_repo import get_macro_repository
            repo = get_macro_repository()
            snapshot = repo.read_yield_curve_snapshot()
            render_yield_curve_chart(st, snapshot)
        except Exception as exc:
            st.warning(f"Curva yield non disponibile: {exc}")

    with col2:
        st.subheader("💳 Credit Spreads")
        try:
            from shared.db.macro_repo import get_macro_repository
            repo = get_macro_repository()
            credit = repo.read_credit_spreads()
            if credit:
                stress_colors = {"low": "🟢", "moderate": "🟡", "elevated": "🔴", "crisis": "🟣"}
                icon = stress_colors.get(credit.stress_level, "⚪")
                st.metric("HY OAS", f"{credit.hy_oas:.0f} bps" if credit.hy_oas else "N/D")
                st.metric("IG OAS", f"{credit.ig_oas:.0f} bps" if credit.ig_oas else "N/D")
                st.metric("TED Spread", f"{credit.ted_spread:.1f} bps" if credit.ted_spread else "N/D")
                st.metric("NFCI", f"{credit.nfci:.3f}" if credit.nfci else "N/D")
                st.markdown(f"{icon} **Stress Level: {credit.stress_level.upper()}** "
                            f"(score: {credit.stress_score:+.2f})")
            else:
                st.info("Credit spreads non disponibili.")
        except Exception as exc:
            st.warning(f"Credit spreads non disponibili: {exc}")
