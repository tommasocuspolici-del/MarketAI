# ruff: noqa: N999
"""K4 — Commodity & Futures ★ ESPANSA (v8.0). Sostituisce E4_Commodities.py."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_k4_commodity_futures"]

_FUTURES_TICKERS = ["CL=F", "GC=F", "ES=F", "ZC=F", "ZW=F"]


def _load_futures_analyses() -> list:
    """Carica le analisi commodity da DuckDB."""
    from shared.db.duckdb_client import get_duckdb_client
    from shared.db.prices_repo import get_prices_repository
    from engine.futures_analysis import (
        RollAnalyzer, BasisAnalyzer,
        OpenInterestAnalyzer, CommodityRegimeClassifier,
    )
    db    = get_duckdb_client()
    prepo = get_prices_repository()
    clf   = CommodityRegimeClassifier(
        roll_analyzer=RollAnalyzer(duckdb=db),
        basis_analyzer=BasisAnalyzer(duckdb=db, prices_repo=prepo),
        oi_analyzer=OpenInterestAnalyzer(duckdb=db),
    )
    results = []
    for ticker in _FUTURES_TICKERS:
        try:
            results.append(clf.classify(ticker))
        except Exception:
            pass
    return results


def body_k4_commodity_futures(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.components.futures_term_structure_panel import (
        render_futures_term_structure_panel,
    )

    require_auth()
    st.title("📊 Mercati — Commodity & Futures")
    st.caption("Term structure (roll yield), basis vs spot ETF, Open Interest signal.")

    try:
        analyses = _load_futures_analyses()
    except Exception as exc:
        st.warning(f"Dati futures non disponibili: {exc}")
        analyses = []

    # ── Term Structure Panel ───────────────────────────────────────────────
    st.subheader("📐 Term Structure")
    render_futures_term_structure_panel(st, analyses)

    if not analyses:
        st.info("Avvia lo scheduler per popolare i dati futures.")
        return

    st.divider()

    # ── Dettaglio per ticker ───────────────────────────────────────────────
    st.subheader("🔍 Dettaglio per Contratto")
    selected = st.selectbox("Seleziona contratto",
                            [a.ticker for a in analyses])

    analysis = next((a for a in analyses if a.ticker == selected), None)
    if not analysis:
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Roll Yield**")
        roll = analysis.roll_result
        st.metric("Roll 22d",   f"{roll.roll_yield_22d*100:+.3f}%")
        st.metric("Roll annual",f"{roll.roll_yield_annual*100:+.1f}%")
        st.metric("Term Struct",roll.term_structure.value.upper())
        if roll.roll_pct_rank is not None:
            st.metric("Pct Rank", f"{roll.roll_pct_rank*100:.0f}°")

    with col2:
        st.markdown("**Basis vs Spot ETF**")
        basis = analysis.basis_result
        st.metric("Basis",      f"{basis.basis:.3f}" if basis.basis else "N/D")
        st.metric("Basis %",    f"{basis.basis_pct:.3f}%" if basis.basis_pct else "N/D")
        st.metric("Z-Score",    f"{basis.basis_zscore:.2f}" if basis.basis_zscore else "N/D")
        st.metric("Signal",     basis.signal.upper())

    with col3:
        st.markdown("**Open Interest**")
        oi = analysis.oi_result
        st.metric("OI Signal",  oi.oi_signal.value.replace("_", " ").title())
        if oi.oi_change_pct is not None:
            st.metric("OI Δ",   f"{oi.oi_change_pct:+.1f}%")
        if oi.price_change_pct is not None:
            st.metric("Price Δ",f"{oi.price_change_pct:+.1f}%")
        st.metric("Inst. Bias", oi.institutional_bias.upper())

    regime_colors = {
        "bullish": "#10B981", "backwardation_squeeze": "#059669",
        "neutral": "#6B7280", "bearish": "#EF4444", "contango_trap": "#DC2626",
    }
    color = regime_colors.get(analysis.regime.value, "#6B7280")
    st.markdown(
        f'<div style="margin-top:12px;padding:12px;border-radius:8px;'
        f'background:{color}22;border:1px solid {color}">'
        f'<b>Regime: {analysis.regime.value.upper()}</b> — '
        f'Score: <b>{analysis.score:+.2f}</b> — '
        f'Confidence: {analysis.confidence}<br>'
        f'<small>{analysis.summary}</small></div>',
        unsafe_allow_html=True,
    )

    if st.button("🔄 Aggiorna"):
        _load_futures_analyses.clear()
        st.rerun()
