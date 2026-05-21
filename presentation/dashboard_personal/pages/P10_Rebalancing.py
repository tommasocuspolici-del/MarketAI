# presentation/dashboard_personal/pages/P10_Rebalancing.py
"""
P10 — Rebalancing Advisor: suggerisce il piano di ribilanciamento portafoglio.

Layout:
  Sezione 1: Configurazione (metodo ottimizzazione, parametri)
  Sezione 2: Portafoglio corrente (pesi e risk contribution)
  Sezione 3: Piano di ribilanciamento (tabella trade)
  Sezione 4: Confronto rischio before/after
  Sezione 5: Storico piani precedenti

Regola 22: InvestorProfile determina il metodo di default e i vincoli.
Regola 41: L'utente può modificare qualsiasi parametro prima di eseguire.
"""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from bridge.personal_client import PersonalClient
from engine.portfolio.rebalancing_engine import RebalancingEngine
from engine.risk.risk_contribution import RiskContributionAnalyzer
from presentation.ui.auth import require_auth
from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState
from presentation.ui.page_factory import render_page
from presentation.ui.session_keys import SK
from shared.db.duckdb_client import get_duckdb_client
from shared.db.sqlite_client import get_sqlite_client
from shared.feature_flags import is_enabled

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__all__ = ["body_rebalancing"]


def body_rebalancing(tokens: DesignTokens) -> None:  # pragma: no cover
    """Body Streamlit della pagina P10 (v8.2.0)."""
    require_auth()

    if not is_enabled("rebalancing_engine"):
        EmptyState(
            "Rebalancing Engine disabilitato",
            hint="Abilita 'rebalancing_engine' in feature_flags.yaml per accedere a questa funzionalità.",
            severity="warning",
        ).render()
        return

    st.title("⚖️ Rebalancing Advisor")
    st.caption(
        "Calcola il piano ottimale di ribilanciamento basato sul tuo profilo "
        "di rischio e sulla matrice di correlazione corrente."
    )

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="p10_refresh"):
            st.cache_data.clear()
            st.rerun()

    # ─── Carica dati portafoglio corrente ─────────────────────────────────
    @st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS)
    def _cached_portfolio() -> tuple[dict, float]:
        return _load_current_portfolio()

    current_weights, portfolio_eur = _cached_portfolio()

    if not current_weights:
        EmptyState(
            "Nessuna posizione trovata",
            hint="Importa le posizioni in P2 — Portafoglio eToro per continuare.",
            severity="warning",
        ).render()
        return

    # ─── Configurazione ───────────────────────────────────────────────────
    st.subheader("⚙️ Configurazione Ottimizzazione")
    col1, col2, col3 = st.columns(3)

    method = col1.selectbox(
        "Metodo di ottimizzazione",
        options=["hrp", "markowitz", "risk_parity", "equal_weight"],
        format_func={
            "hrp":          "HRP — Hierarchical Risk Parity (consigliato)",
            "markowitz":    "Markowitz — Mean-Variance",
            "risk_parity":  "Risk Parity — Equal Risk",
            "equal_weight": "Equal Weight — 1/N",
        }.get,
        help=(
            "HRP: robusto, non richiede stime rendimenti. "
            "Markowitz: ottimale in teoria ma instabile. "
            "Risk Parity: ogni asset contribuisce ugualmente al rischio."
        ),
    )

    drift_threshold = col2.slider(
        "Soglia drift per ribilanciare (%)",
        min_value=1, max_value=15, value=5,
        help="Non suggerisce trade se la differenza è sotto questa soglia",
    ) / 100.0

    min_trade_eur = col3.number_input(
        "Importo minimo per trade (€)",
        min_value=10.0, max_value=500.0, value=50.0, step=10.0,
    )

    # ─── Portafoglio corrente con risk contribution ────────────────────────
    st.subheader("📊 Portafoglio Corrente")

    risk_analyzer = RiskContributionAnalyzer(get_duckdb_client())
    risk_report = None
    try:
        risk_report = risk_analyzer.analyze(
            weights=current_weights, profile_id="me"
        )
    except Exception as exc:
        st.caption(f"Risk contribution non disponibile: {exc}")

    # Tabella posizioni correnti
    rows = []
    for ticker, weight in current_weights.items():
        rc = (
            risk_report.risk_contributions.get(ticker, 0.0)
            if risk_report else 0.0
        )
        rows.append({
            "Ticker":              ticker,
            "Peso Attuale":        f"{weight * 100:.1f}%",
            "Risk Contribution":   f"{rc * 100:.1f}%",
            "Valore (€)":         f"€{weight * portfolio_eur:,.0f}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if risk_report:
        col1, col2, col3 = st.columns(3)
        col1.metric("Volatilità Annua", f"{risk_report.portfolio_vol_annual * 100:.1f}%")
        col2.metric("CVaR 95%",         f"{abs(risk_report.portfolio_cvar_95) * 100:.1f}%")
        col3.metric("HHI Concentrazione", f"{risk_report.hhi:.3f}",
                    help="0 = perfettamente diversificato, 1 = tutto su 1 asset")

        if risk_report.hhi > 0.30:
            st.warning(risk_report.recommendation)
        else:
            st.success(risk_report.recommendation)

    # ─── Calcola piano di ribilanciamento ─────────────────────────────────
    st.divider()
    st.subheader("🔄 Piano di Ribilanciamento")

    if st.button("📐 Calcola Piano Ottimale", type="primary"):
        with st.spinner(f"Ottimizzando con metodo {method.upper()}..."):
            try:
                engine = RebalancingEngine(
                    duckdb=get_duckdb_client(),
                    profile_risk=_get_profile_risk(),
                    method=method,
                    min_trade_eur=min_trade_eur,
                    drift_threshold=drift_threshold,
                )
                report = engine.run(
                    current_weights=current_weights,
                    portfolio_value_eur=portfolio_eur,
                    profile_id="me",
                )
                st.session_state[SK.LAST_REBALANCING_REPORT] = report
            except Exception as exc:
                st.error(f"❌ Errore nel calcolo: {exc}")
                return

    if SK.LAST_REBALANCING_REPORT not in st.session_state:
        st.info("ℹ️ Premi il pulsante per calcolare il piano ottimale.")
        return

    report = st.session_state[SK.LAST_REBALANCING_REPORT]

    # ── Summary ────────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Operazioni suggerite", report.n_trades)
    col2.metric("Turnover portafoglio",  f"{report.total_turnover_pct * 100:.1f}%")
    col3.metric("Impatto fiscale stimato", f"€{report.estimated_tax_eur:,.0f}")
    col4.metric(
        "Var. Volatilità",
        f"{report.expected_vol_annual * 100:.1f}%",
        delta=f"{(report.expected_vol_annual - report.current_vol_annual) * 100:+.1f}%",
    )

    st.info(report.summary)

    # ── Tabella trade ──────────────────────────────────────────────────────
    st.subheader("📋 Operazioni Suggerite")
    action_icon = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "⚪ HOLD"}
    trade_rows = []
    for t in report.trades:
        trade_rows.append({
            "Ticker":         t.ticker,
            "Azione":         action_icon.get(t.action, t.action),
            "Peso Attuale":   f"{t.current_weight * 100:.1f}%",
            "Peso Target":    f"{t.target_weight * 100:.1f}%",
            "Drift":          f"{t.drift_pct:+.1f}%",
            "Importo (€)":   f"€{t.estimated_eur:,.0f}" if t.action != "HOLD" else "—",
            "Priorità":       "🔴 Alta" if t.priority == 1 else ("🟡 Media" if t.priority == 2 else "🟢 Bassa"),
        })
    st.dataframe(pd.DataFrame(trade_rows), use_container_width=True, hide_index=True)

    # ── Before/After chart ─────────────────────────────────────────────────
    st.subheader("📊 Confronto Allocazione Before/After")
    tickers_list = list(report.current_weights.keys())
    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Corrente",
        x=tickers_list,
        y=[report.current_weights[t] * 100 for t in tickers_list],
        marker_color="#4A90D9",
    ))
    fig.add_trace(go.Bar(
        name="Target",
        x=tickers_list,
        y=[report.target_weights.get(t, 0) * 100 for t in tickers_list],
        marker_color="#7ED321",
    ))
    fig.update_layout(
        barmode="group", height=300,
        yaxis_title="Peso (%)",
        margin={"l": 0, "r": 0, "t": 20, "b": 0},
    )
    st.plotly_chart(fig, use_container_width=True)

    # ── Risk contribution before/after ─────────────────────────────────────
    if risk_report:
        st.subheader("⚠️ Risk Contribution Before/After")
        rc_current = [
            risk_report.risk_contributions.get(t, 0.0) * 100
            for t in tickers_list
        ]
        # Risk contribution after (stima basata sui nuovi pesi)
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            name="Risk Contribution Corrente",
            x=tickers_list, y=rc_current,
            marker_color="#E74C3C",
        ))
        fig2.update_layout(
            height=250, yaxis_title="Contributo al Rischio (%)",
            margin={"l": 0, "r": 0, "t": 20, "b": 0},
        )
        st.plotly_chart(fig2, use_container_width=True)

    # ── Disclaimer ─────────────────────────────────────────────────────────
    st.divider()
    st.caption(
        "⚠️ **Disclaimer:** Questo piano è puramente indicativo e non costituisce "
        "consulenza finanziaria. Le operazioni non vengono eseguite automaticamente. "
        "Consulta un professionista prima di effettuare modifiche al portafoglio. "
        "Il calcolo dell'impatto fiscale è una stima semplificata — "
        "consulta il modulo P8 — Fiscale per un calcolo preciso."
    )

    # ── Storico ────────────────────────────────────────────────────────────
    _render_history()


@st.cache_data(ttl=CACHE_TTL.MARKET_KPI)
def _load_current_portfolio() -> tuple[dict[str, float], float]:
    """
    Carica posizioni correnti da SQLite e calcola pesi.
    Ritorna ({ticker: weight}, total_eur).
    """
    try:
        db = get_sqlite_client()
        rows = db.fetchall(
            "SELECT ticker, quantity, avg_cost, currency "
            "FROM positions WHERE is_open = 1"
        )
        if not rows:
            return {}, 0.0

        # Calcola valore corrente (usa avg_cost come proxy se prezzo live non disponibile)
        from shared.db.prices_repo import get_prices_repository
        from shared.types import TimeFrame
        repo = get_prices_repository()

        values: dict[str, float] = {}
        for row in rows:
            ticker = str(row["ticker"])
            qty    = float(row["quantity"])
            price_df = repo.read_ohlcv(
                ticker=ticker, exchange="NASDAQ",
                timeframe=TimeFrame.D1, limit=1,
            )
            price = (
                float(price_df["close"].iloc[-1])
                if price_df is not None and not price_df.empty
                else float(row["avg_cost"])
            )
            values[ticker] = qty * price

        total = sum(values.values())
        if total <= 0:
            return {}, 0.0

        weights = {t: v / total for t, v in values.items()}
        return weights, total

    except Exception:
        return {}, 0.0


def _get_profile_risk() -> str:
    try:
        client  = PersonalClient()
        profile = client.get_investor_profile("me")
        return profile.risk_tolerance.value if profile else "moderate"
    except Exception:
        return "moderate"


@st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS)
def _render_history() -> None:
    st.subheader("📋 Storico Piani di Ribilanciamento")
    try:
        client = get_duckdb_client()
        rows   = client.query(
            "SELECT computed_at, method, total_trades, total_turnover_pct, "
            "estimated_tax_impact_eur, current_vol, target_vol "
            "FROM rebalancing_reports WHERE profile_id = 'me' "
            "ORDER BY computed_at DESC LIMIT 10"
        ).fetchall()
        if rows:
            df = pd.DataFrame(rows, columns=[
                "Data", "Metodo", "N Operazioni", "Turnover",
                "Impatto Fiscale (€)", "Vol Corrente", "Vol Target",
            ])
            df["Turnover"]     = df["Turnover"].apply(lambda x: f"{x * 100:.1f}%")
            df["Vol Corrente"] = df["Vol Corrente"].apply(lambda x: f"{x * 100:.1f}%")
            df["Vol Target"]   = df["Vol Target"].apply(lambda x: f"{x * 100:.1f}%")
            st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("Nessun piano storico ancora.")
    except Exception as exc:
        st.caption(f"Storico non disponibile: {exc}")


if __name__ == "__main__":  # pragma: no cover
    render_page("Rebalancing Advisor", "⚖️", body_rebalancing)
