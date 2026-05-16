# ruff: noqa: N999
"""Q11 — Options Analytics (v10.0.0, Blocco D Lean MVP).

2 tab:
  1. Greeks      — input form + BS Greeks + vol surface (mock chain)
  2. Expected Move — IV → expected price range per expiry

Feature flags: options_analytics (off by default — shows info banner if disabled).
"""
from __future__ import annotations

__version__ = "10.0.0"
__all__ = ["body_q11_options_analytics"]


def body_q11_options_analytics(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("📐 Options Analytics")
    st.caption("Black-Scholes Greeks, Volatility Surface, Expected Move — Lean MVP v10.0")

    from shared.feature_flags import is_enabled
    if not is_enabled("options_analytics"):
        st.info(
            "**Options Analytics** è disabilitato (feature flag `options_analytics: false`).\n\n"
            "I dati visualizzati sono generati con una **catena mock** (Black-Scholes sintetico).\n"
            "Per abilitare la catena live Finnhub, imposta `options_live_chain: true` "
            "in `config/feature_flags.yaml`."
        )

    tab_greeks, tab_em = st.tabs(["📊 Greeks", "📏 Expected Move"])

    with tab_greeks:
        _render_greeks_tab(st)

    with tab_em:
        _render_expected_move_tab(st)


def _render_greeks_tab(st) -> None:  # pragma: no cover
    """Tab 1 — Greeks: input form + BS calculation + mock chain table."""
    st.subheader("Black-Scholes Greeks")
    st.caption("Inserisci i parametri dell'opzione. I prezzi sono calcolati con Black-Scholes.")

    col1, col2, col3 = st.columns(3)
    with col1:
        spot   = st.number_input("Spot price (S)", value=100.0, min_value=0.01, step=1.0)
        strike = st.number_input("Strike (K)",     value=100.0, min_value=0.01, step=1.0)
    with col2:
        t_days = st.number_input("Giorni a scadenza", value=30, min_value=1, max_value=730)
        iv     = st.slider("Volatilità implicita (IV %)", min_value=1, max_value=200,
                            value=20) / 100.0
    with col3:
        r          = st.number_input("Risk-free rate (%)", value=5.0, step=0.1) / 100.0
        opt_type   = st.selectbox("Tipo opzione", ["call", "put"])

    t_years = t_days / 365.0

    try:
        from engine.options.bs_calculator import BlackScholesCalculator
        calc   = BlackScholesCalculator()
        result = calc.price(S=spot, K=strike, T=t_years, r=r, sigma=iv,
                            option_type=opt_type)

        st.divider()
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Prezzo",  f"{result.price:.4f}")
        c2.metric("Delta",   f"{result.greeks.delta:+.4f}")
        c3.metric("Gamma",   f"{result.greeks.gamma:.6f}")
        c4.metric("Vega",    f"{result.greeks.vega:.4f}",
                  help="Variazione prezzo per +1% di IV")
        c5.metric("Theta",   f"{result.greeks.theta:+.4f}",
                  help="Variazione prezzo per 1 giorno calendariale")
        c6.metric("Rho",     f"{result.greeks.rho:+.4f}",
                  help="Variazione prezzo per +1% del tasso risk-free")

        st.divider()
        st.subheader("Catena Mock (spot ±20%, 5 scadenze)")
        st.caption("Prezzi generati con Black-Scholes a volatilità piatta (semplificazione).")

        from engine.options.mock_chain import MockOptionsChain
        import pandas as pd

        chain     = MockOptionsChain()
        contracts = chain.generate(
            ticker="MOCK", spot=spot, iv=iv, r=r,
            expiry_days=[7, 14, 30, 60, 90],
        )
        calls = [c for c in contracts if c.option_type == "call"]
        rows  = [
            {
                "Tipo":        c.option_type.upper(),
                "Strike":      c.strike,
                "Scad. (gg)":  c.expiry_days,
                "Prezzo":      round(c.price, 4),
                "Delta":       round(c.delta, 4),
                "Gamma":       round(c.gamma, 6),
                "Vega":        round(c.vega, 4),
                "Theta":       round(c.theta, 4),
                "ITM":         "✅" if c.is_itm else "",
            }
            for c in calls
        ]
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

    except Exception as exc:
        st.error(f"Errore nel calcolo Greeks: {exc}")


def _render_expected_move_tab(st) -> None:  # pragma: no cover
    """Tab 2 — Expected Move: IV → price range per N scadenze."""
    st.subheader("Expected Move")
    st.caption(
        "Formula: **EM = IV × Spot × √T**  |  "
        "Interpretazione: ~68% dei movimenti cade nel range ±1σ."
    )

    col1, col2 = st.columns(2)
    with col1:
        spot = st.number_input("Spot price", value=100.0, min_value=0.01,
                                step=1.0, key="em_spot")
        iv   = st.slider("Volatilità implicita (IV %)", min_value=1, max_value=200,
                          value=20, key="em_iv") / 100.0
    with col2:
        expiry_options = [7, 14, 30, 60, 90, 180, 365]
        selected_days  = st.multiselect(
            "Scadenze (giorni)", options=expiry_options,
            default=[7, 30, 90],
        )

    if not selected_days:
        st.info("Seleziona almeno una scadenza.")
        return

    try:
        from engine.options.expected_move import ExpectedMoveCalculator
        import pandas as pd

        calc = ExpectedMoveCalculator()
        rows = []
        for days in sorted(selected_days):
            r = calc.calculate_days(spot=spot, iv=iv, days=days)
            rows.append({
                "Scadenza":    f"{days}gg",
                "Move ±1σ":    f"±{r.move_abs:.2f}",
                "Move % ±1σ":  f"±{r.move_pct:.1%}",
                "Lower 1σ":    f"{r.lower_1sigma:.2f}",
                "Upper 1σ":    f"{r.upper_1sigma:.2f}",
                "Lower 2σ":    f"{r.lower_2sigma:.2f}",
                "Upper 2σ":    f"{r.upper_2sigma:.2f}",
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Visual range chart for 30-day expiry
        em_30 = calc.calculate_days(spot=spot, iv=iv, days=30)
        st.divider()
        st.markdown(f"**Range a 30 giorni** (IV={iv:.0%})")
        col_l2, col_l1, col_s, col_u1, col_u2 = st.columns(5)
        col_l2.metric("-2σ", f"{em_30.lower_2sigma:.1f}", delta=f"{em_30.lower_2sigma - spot:.1f}")
        col_l1.metric("-1σ", f"{em_30.lower_1sigma:.1f}", delta=f"{em_30.lower_1sigma - spot:.1f}")
        col_s.metric("Spot", f"{em_30.spot:.1f}")
        col_u1.metric("+1σ", f"{em_30.upper_1sigma:.1f}", delta=f"+{em_30.upper_1sigma - spot:.1f}")
        col_u2.metric("+2σ", f"{em_30.upper_2sigma:.1f}", delta=f"+{em_30.upper_2sigma - spot:.1f}")

    except Exception as exc:
        st.error(f"Errore nel calcolo Expected Move: {exc}")


if __name__ == "__main__":  # pragma: no cover
    from presentation.ui.page_factory import render_page
    render_page("Options Analytics", "📐", body_q11_options_analytics)
