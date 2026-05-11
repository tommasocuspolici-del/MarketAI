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
