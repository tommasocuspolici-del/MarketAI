# ruff: noqa: N999
"""K3 — Bonds & Credit (v8.0). Sostituisce E3_Bonds.py."""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_k3_bonds_credit"]


def body_k3_bonds_credit(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.components.yield_curve_chart import render_yield_curve_chart
    require_auth()
    st.title("📊 Mercati — Bonds & Credit")
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="k3_refresh"):
            st.cache_data.clear()
            st.rerun()

    col1, col2 = st.columns([3, 2])
    with col1:
        st.subheader("📐 Yield Curve")
        try:
            from shared.db.macro_repo import get_macro_repository
            snap = get_macro_repository().read_yield_curve_snapshot()
            render_yield_curve_chart(st, snap)
        except Exception as exc:
            st.warning(f"N/D: {exc}")

    with col2:
        st.subheader("💳 Credit Spreads")
        try:
            from shared.db.macro_repo import get_macro_repository
            credit = get_macro_repository().read_credit_spreads()
            if credit:
                st.metric("HY OAS", f"{credit.hy_oas:.0f} bps" if credit.hy_oas else "N/D")
                st.metric("IG OAS", f"{credit.ig_oas:.0f} bps" if credit.ig_oas else "N/D")
                st.metric("Stress", credit.stress_level.upper())
                st.metric("Score",  f"{credit.stress_score:+.2f}")
            else:
                st.info("Credit spreads N/D")
        except Exception as exc:
            st.warning(f"N/D: {exc}")
