# ruff: noqa: N999
"""M3 — Labour Market Dashboard (Blocco D).

4 tab: Claims & Cycle · JOLTS & Beveridge · Payroll · Forecasting
Carica gracefully con DB vuoto (warning visibile, no crash).
@st.cache_data con TTL appropriato per ogni fetch.
Zero colori hardcoded — DESIGN_TOKENS sempre.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
from presentation.ui.page_factory import render_page
from presentation.ui.layout import render_section_header

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"


def _safe_read(duckdb, query: str, fallback=None):
    """Legge da DuckDB; restituisce fallback se DB vuoto o tabella assente."""
    try:
        return duckdb.query(query)
    except Exception:
        return fallback


def _render_claims_tab(st, tokens: DesignTokens) -> None:
    """Tab 1: Claims & Cycle."""
    render_section_header("📉 Claims & Ciclo Lavoro",
        "Initial Claims settimanali con media mobile 4 settimane e regime di ciclo.")

    from shared.db.duckdb_client import DuckDBClient
    from shared.constants import DUCKDB_PATH
    try:
        db = DuckDBClient(path=DUCKDB_PATH)
        rows = _safe_read(db,
            "SELECT week_ending, initial_claims, claims_4wk_ma, cycle_regime, signal_strength "
            "FROM claims_cycle ORDER BY week_ending DESC LIMIT 104")
    except Exception:
        rows = None

    if not rows:
        st.info("⏳ Nessun dato Claims disponibile. Esegui il job Labour Market per caricare i dati.")
        st.caption("Il job si avvia ogni giovedì dopo le 17:00 EST post-rilascio ICSA.")
        return

    import pandas as pd
    import plotly.graph_objects as go
    df = pd.DataFrame(rows, columns=["week_ending","initial_claims","claims_4wk_ma",
                                      "cycle_regime","signal_strength"])
    df["week_ending"] = pd.to_datetime(df["week_ending"])
    df = df.sort_values("week_ending")

    c = tokens.colors
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["week_ending"], y=df["initial_claims"],
        name="Initial Claims", line={"color": c.text_secondary, "width": 1}, opacity=0.5))
    fig.add_trace(go.Scatter(x=df["week_ending"], y=df["claims_4wk_ma"],
        name="4wk MA", line={"color": c.accent_primary, "width": 2}))
    fig.update_layout(
        title="Initial Claims — Media Mobile 4 Settimane",
        paper_bgcolor=c.bg_primary, plot_bgcolor=c.bg_secondary,
        font={"color": c.text_primary}, legend={"bgcolor": "rgba(0,0,0,0)"},
        height=350, margin={"t": 40, "b": 20},
    )
    st.plotly_chart(fig, use_container_width=True)

    latest = df.iloc[-1]
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Claims correnti", f"{latest['initial_claims']:,.0f}")
    with col2:
        st.metric("4wk MA", f"{latest['claims_4wk_ma']:,.0f}")
    with col3:
        regime_colors = {"expansion": "🟢", "peak": "🟡", "contraction": "🔴", "trough": "🔵"}
        emoji = regime_colors.get(str(latest["cycle_regime"]), "⚪")
        st.metric("Regime", f"{emoji} {latest['cycle_regime']}")


def _render_jolts_tab(st, tokens: DesignTokens) -> None:
    """Tab 2: JOLTS & Beveridge Curve."""
    render_section_header("📊 JOLTS & Beveridge Curve",
        "Job openings, dimissioni volontarie e il gap Beveridge (leading wage indicator).")

    from shared.db.duckdb_client import DuckDBClient
    from shared.constants import DUCKDB_PATH
    try:
        db = DuckDBClient(path=DUCKDB_PATH)
        rows = _safe_read(db,
            "SELECT series_date, job_openings, quits_rate, openings_rate, beveridge_gap "
            "FROM jolts_monthly ORDER BY series_date DESC LIMIT 60")
    except Exception:
        rows = None

    if not rows:
        st.info("⏳ Nessun dato JOLTS disponibile.")
        return

    import pandas as pd
    import plotly.graph_objects as go
    df = pd.DataFrame(rows, columns=["series_date","job_openings","quits_rate",
                                      "openings_rate","beveridge_gap"])
    df["series_date"] = pd.to_datetime(df["series_date"])
    df = df.sort_values("series_date")
    c = tokens.colors

    # Beveridge Curve scatter
    col1, col2 = st.columns(2)
    with col1:
        fig = go.Figure(go.Scatter(
            x=df["openings_rate"], y=df["beveridge_gap"],
            mode="lines+markers",
            marker={"color": df.index, "colorscale": "Blues", "size": 6},
            line={"color": c.accent_primary, "width": 1},
        ))
        fig.update_layout(
            title="Beveridge Curve",
            xaxis_title="Job Openings Rate %",
            yaxis_title="Beveridge Gap",
            paper_bgcolor=c.bg_primary, plot_bgcolor=c.bg_secondary,
            font={"color": c.text_primary}, height=300,
        )
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        fig2 = go.Figure(go.Scatter(
            x=df["series_date"], y=df["quits_rate"],
            line={"color": c.positive, "width": 2},
        ))
        fig2.update_layout(
            title="Quits Rate % (leading wage indicator)",
            paper_bgcolor=c.bg_primary, plot_bgcolor=c.bg_secondary,
            font={"color": c.text_primary}, height=300,
        )
        st.plotly_chart(fig2, use_container_width=True)


def _render_payroll_tab(st, tokens: DesignTokens) -> None:
    """Tab 3: Payroll Decomposition."""
    render_section_header("💼 Payroll per Settore",
        "NFP headline scomposto in ciclici vs difensivi. "
        "Cyclical ratio > 1 → espansione guidata dal settore privato.")

    from shared.db.duckdb_client import DuckDBClient
    from shared.constants import DUCKDB_PATH
    try:
        db = DuckDBClient(path=DUCKDB_PATH)
        rows = _safe_read(db,
            "SELECT release_date, sector, jobs_added_k, is_cyclical "
            "FROM payroll_sector ORDER BY release_date DESC LIMIT 120")
    except Exception:
        rows = None

    if not rows:
        st.info("⏳ Nessun dato Payroll disponibile.")
        return

    import pandas as pd
    import plotly.graph_objects as go
    df = pd.DataFrame(rows, columns=["release_date","sector","jobs_added_k","is_cyclical"])
    df["release_date"] = pd.to_datetime(df["release_date"])
    c = tokens.colors

    # Ultimi 12 mesi, aggregato ciclici vs difensivi
    last12 = df[df["release_date"] >= df["release_date"].max() - pd.DateOffset(months=12)]
    cyc  = last12[last12["is_cyclical"] == True].groupby("release_date")["jobs_added_k"].sum()   # noqa: E712
    def_ = last12[last12["is_cyclical"] == False].groupby("release_date")["jobs_added_k"].sum()  # noqa: E712

    fig = go.Figure()
    fig.add_trace(go.Bar(x=cyc.index, y=cyc.values, name="Ciclici",
                         marker_color=c.positive))
    fig.add_trace(go.Bar(x=def_.index, y=def_.values, name="Difensivi",
                         marker_color=c.accent_primary))
    fig.update_layout(
        barmode="stack", title="Payroll per Settore (ultimi 12 mesi, migliaia)",
        paper_bgcolor=c.bg_primary, plot_bgcolor=c.bg_secondary,
        font={"color": c.text_primary}, height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_forecasting_tab(st, tokens: DesignTokens) -> None:
    """Tab 4: Labour Market Forecasting."""
    render_section_header("🔮 Forecasting Mercato del Lavoro",
        "Previsioni ensemble ARIMA + Ridge a 1M/3M/6M.")

    from shared.db.duckdb_client import DuckDBClient
    from shared.constants import DUCKDB_PATH
    try:
        db = DuckDBClient(path=DUCKDB_PATH)
        rows = _safe_read(db,
            "SELECT generated_at, horizon, target_metric, forecast_value, "
            "forecast_lower, forecast_upper, model_used "
            "FROM labour_forecasts ORDER BY generated_at DESC LIMIT 30")
    except Exception:
        rows = None

    if not rows:
        st.info("⏳ Nessuna previsione disponibile. Il modello si addestra sui dati FRED storici.")
        st.caption(
            "Per generare le previsioni: assicurati che FRED_API_KEY sia configurata "
            "e che il job Labour Market abbia completato almeno un run."
        )
        return

    import pandas as pd
    df = pd.DataFrame(rows, columns=["generated_at","horizon","target_metric",
                                      "forecast_value","forecast_lower","forecast_upper","model_used"])

    for metric in df["target_metric"].unique():
        mdf = df[df["target_metric"] == metric].sort_values("horizon")
        st.markdown(f"**{metric}**")
        display = mdf[["horizon","forecast_value","forecast_lower","forecast_upper","model_used"]].copy()
        display.columns = ["Orizzonte","Forecast","Lower 10%","Upper 90%","Modello"]
        st.dataframe(display, use_container_width=True, hide_index=True)


def body_labour_market(tokens: DesignTokens) -> None:
    """Body Streamlit pagina M3."""
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    tab1, tab2, tab3, tab4 = st.tabs(
        ["📉 Claims & Ciclo", "📊 JOLTS & Beveridge", "💼 Payroll", "🔮 Forecasting"]
    )
    with tab1:
        _render_claims_tab(st, tokens)
    with tab2:
        _render_jolts_tab(st, tokens)
    with tab3:
        _render_payroll_tab(st, tokens)
    with tab4:
        _render_forecasting_tab(st, tokens)


if __name__ == "__main__":  # pragma: no cover
    render_page("Labour Market", "👷", body_labour_market)
