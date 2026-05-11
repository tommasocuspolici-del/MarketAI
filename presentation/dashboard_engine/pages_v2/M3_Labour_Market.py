# ruff: noqa: N999
"""M3 — Labour Market ★ NUOVA (v8.0).

Pagina nuova: ICSA/CCSA/JOLTS + ClaimsInflationCrossAnalyzer.
"""
from __future__ import annotations

__version__ = "8.0.0"
__all__ = ["body_m3_labour_market"]


def body_m3_labour_market(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.components.claims_cross_panel import render_claims_cross_panel

    require_auth()
    st.title("🌍 Macro — Labour Market")
    st.caption("Claims settimanali, Payrolls e cross-signal Claims/Inflation.")

    # ── Claims cross signal ────────────────────────────────────────────────
    st.subheader("⚡ Claims/Inflation Cross Signal")
    try:
        from shared.db.macro_repo import get_macro_repository
        repo   = get_macro_repository()
        signal = repo.read_claims_signal()
        render_claims_cross_panel(st, signal)
    except Exception as exc:
        st.warning(f"Signal non disponibile: {exc}")

    st.divider()

    # ── Serie storiche ─────────────────────────────────────────────────────
    st.subheader("📈 Serie Storiche")
    try:
        import plotly.graph_objects as go
        from shared.db.macro_repo import get_macro_repository
        repo = get_macro_repository()

        labour_series = {
            "Initial Claims (ICSA)":    "ICSA",
            "Continued Claims (CCSA)":  "CCSA",
            "Nonfarm Payrolls (PAYEMS)":"PAYEMS",
        }

        for label, sid in labour_series.items():
            try:
                df = repo.read_macro(sid)
                if df is None or df.empty:
                    continue
                df_plot = df.tail(104)  # 2 anni
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_plot["ts"], y=df_plot["value"],
                    mode="lines", name=label,
                    line=dict(color=tokens.colors.positive if "Payrolls" in label
                              else tokens.colors.negative, width=1.8),
                ))
                fig.update_layout(height=180, margin=dict(l=0, r=0, t=20, b=0),
                                  title=label, showlegend=False,
                                  paper_bgcolor="rgba(0,0,0,0)",
                                  plot_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, use_container_width=True)
            except Exception:
                st.caption(f"{label}: dati non disponibili")
    except Exception as exc:
        st.warning(f"Dati non disponibili: {exc}")
