# ruff: noqa: N999
"""E1 — Market Overview (v7.1).

Risolve i problemi della v6:
  - KPI hardcoded -> ora live da yfinance via LiveMarketService.
  - Nessun modo di forzare refresh -> bottone "🔄 Aggiorna ora".
  - Valuta non chiara -> badge valuta su ogni KPI.
  - Sentiment Radar senza spiegazione -> sezione narrative integrata.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from engine.market_data.live_market_service import (
    MarketSnapshot,
    get_live_market_service,
)
from presentation.ui.components.metric_card import (
    MetricSpec,
    render_metric_row,
)
from presentation.ui.components.regime_badge import render_regime_badge
from presentation.ui.components.sentiment_radar import render_sentiment_radar
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page
from presentation.ui.session_keys import SK

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.1"

__all__ = ["body_market_overview"]


def _snapshot_to_metrics(snapshot: MarketSnapshot) -> list[MetricSpec]:
    """Converte un MarketSnapshot in una lista di MetricSpec."""
    metrics: list[MetricSpec] = []
    for kpi in snapshot.kpis:
        if kpi.value is None:
            metrics.append(
                MetricSpec(
                    term=kpi.term,
                    value="—",
                    format_spec=kpi.format_spec,
                )
            )
            continue
        metrics.append(
            MetricSpec(
                term=kpi.term,
                value=kpi.value,
                delta=kpi.delta_pct,
                format_spec=kpi.format_spec,
                unit_override=f" {kpi.currency}",
                delta_pct=True,
            )
        )
    return metrics


def _render_refresh_bar(st_module, snapshot: MarketSnapshot) -> bool:  # pragma: no cover
    """Barra con stato cache + bottone force refresh.

    Returns:
        True se l'utente ha cliccato "Aggiorna ora".
    """
    st = st_module
    cols = st.columns([2, 2, 1])
    with cols[0]:
        n_total = len(snapshot.kpis)
        n_ok = sum(1 for k in snapshot.kpis if k.value is not None)
        n_stale = sum(1 for k in snapshot.kpis if k.is_stale)
        all_stale = n_stale == n_total and n_total > 0
        if all_stale:
            st.warning(
                f"📦 Dati da cache disco · fetchati {snapshot.fetched_at_human} "
                f"(API offline — mostrando ultimo snapshot valido)"
            )
        elif n_ok == n_total:
            st.success(f"✅ Tutti i {n_total} KPI aggiornati · {snapshot.fetched_at_human}")
        elif n_ok > 0:
            st.warning(
                f"⚠️ {n_ok}/{n_total} KPI aggiornati · {snapshot.n_errors} errori"
            )
        else:
            st.error(f"❌ Dati di mercato non disponibili · {snapshot.fetched_at_human}")
    with cols[1]:
        n_stale = sum(1 for k in snapshot.kpis if k.is_stale)
        if n_stale > 0 and not all_stale:
            st.caption(
                f"📦 {n_stale} valori da cache "
                f"(API offline o ticker temporaneamente non disponibile)"
            )
    with cols[2]:
        return bool(
            st.button(
                "🔄 Aggiorna ora",
                key="market_force_refresh",
                use_container_width=True,
                help="Forza un nuovo fetch dalle API ignorando la cache",
            )
        )


def _render_error_summary(st_module, snapshot: MarketSnapshot) -> None:  # pragma: no cover
    """Mostra elenco degli errori per ticker se presenti."""
    errors = [k for k in snapshot.kpis if k.error]
    if not errors:
        return
    with st_module.expander(
        f"⚠️ Dettaglio errori fetch ({len(errors)})", expanded=False
    ):
        for k in errors:
            st_module.write(f"- **{k.term}** (`{k.yf_ticker}`): {k.error}")


def body_market_overview(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    """Body della pagina E1 v7.1."""
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    svc = get_live_market_service()

    # Pulizia forzata della cache di Streamlit se necessario (risolve "vista vuota" persistente)
    if st.session_state.get(SK.CLEAR_CACHE, False):
        st.cache_data.clear()
        st.session_state[SK.CLEAR_CACHE] = False

    # Force-refresh flag tramite session_state
    if st.session_state.pop(SK.FORCE_REFRESH, False):
        snapshot = svc.refresh_now()
        # Dopo un refresh manuale, cancella anche la cache Streamlit per sicurezza
        st.cache_data.clear()
    else:
        snapshot = svc.get_kpi_snapshot()

    render_section_header(
        "🌍 Market KPIs · Live Data",
        "Prezzi reali da Yahoo Finance · cache 60s · click 'Aggiorna ora' per forzare refresh",
    )

    if _render_refresh_bar(st, snapshot):
        st.session_state[SK.FORCE_REFRESH] = True
        st.rerun()

    metrics = _snapshot_to_metrics(snapshot)
    render_metric_row(tokens, metrics)
    _render_error_summary(st, snapshot)

    # Sezione regime + sentiment
    st.write("")
    col_regime, col_sentiment = st.columns([1, 2])

    with col_regime:
        render_section_header("Market Regime", "HMM-based classification")
        try:
            render_regime_badge(tokens, regime="bull")
        except (ImportError, AttributeError, TypeError):
            st.info("Regime classifier non disponibile in questa build.")

    with col_sentiment:
        render_section_header("📡 Sentiment Composite — 8 fonti")

        @st.cache_data(ttl=900)
        def _cached_e1_sentiment() -> tuple[dict[str, float], list[str]]:
            from engine.analytics.sentiment.live_sentiment_service import (
                _DEMO_SCORES,
                get_live_sentiment_service,
            )
            svc = get_live_sentiment_service()
            result = svc.fetch_all()
            return result.to_display_dict(fallbacks=_DEMO_SCORES), result.live_sources

        sentiment_scores, live_srcs = _cached_e1_sentiment()
        if live_srcs:
            st.caption(f"✅ Live: {', '.join(live_srcs)} · resto DEMO")
        else:
            st.caption("⚠️ DATI DEMO — connetti API esterne per scores live (Finnhub, AAII, CNN F&G)")
        try:
            render_sentiment_radar(tokens, sentiment_scores)
        except (ImportError, AttributeError, TypeError):
            st.info("Sentiment radar non disponibile in questa build.")

        with st.expander("📚 Come si legge il Sentiment Radar?", expanded=False):
            st.markdown(
                "Ogni asse del radar e' una fonte di sentiment indipendente. "
                "Il valore va da -1 (bearish: paura/pessimismo) a +1 (bullish: "
                "ottimismo/avidità), normalizzato a 0-100 sul grafico.\n\n"
                "**Pattern significativi:**\n\n"
                "- 🟢 **Tutti gli assi sopra 75** → euforia generalizzata. "
                "Storicamente un *segnale contrarian di vendita*.\n\n"
                "- 🔴 **Tutti gli assi sotto 25** → paura diffusa. "
                "Storicamente vicino a minimi di mercato (segnale contrarian "
                "di acquisto).\n\n"
                "- 🟡 **Pattern misto/asimmetrico** → mercato in transizione. "
                "Leggi le singole fonti: COT (smart money) e Insider sono i "
                "più informativi a medio termine; AAII e CNN F&G sono retail "
                "(più rumorosi).\n\n"
                "**Le 8 fonti** (clicca 'ⓘ Cos'e?' su ogni KPI per definizione "
                "completa): CNN F&G (composito 7 indicatori USA), AAII "
                "(sondaggio retail), Crypto F&G (BTC sentiment), Put/Call "
                "(volume opzioni), COT (positioning futures), Insider "
                "(acquisti dirigenti), Short Int (% flottante shortato), "
                "Finnhub (NLP su news)."
            )

    render_section_header("Top Risk Factors")

    @st.cache_data(ttl=3600)
    def _cached_risk_factors() -> list[str]:
        from engine.market_data.fred_simple_client import FredSimpleClient
        import yfinance as yf

        factors: list[str] = []
        try:
            fred = FredSimpleClient()
            if fred.has_api_key:
                t10 = fred.fetch_latest("DGS10")
                t2  = fred.fetch_latest("DGS2")
                if t10 is not None and t2 is not None:
                    spread_bp = round((t10 - t2) * 100, 0)
                    label = "invertita" if spread_bp < 0 else f"+{int(spread_bp)}bp"
                    factors.append(f"Yield curve 10Y-2Y: {label} — {'⚠️ inversione attiva' if spread_bp < 0 else 'normale'}")
        except Exception:
            pass
        try:
            vix_hist = yf.Ticker("^VIX").history(period="2d")
            if not vix_hist.empty:
                vix_now = float(vix_hist["Close"].iloc[-1])
                if vix_now > 30:
                    factors.append(f"VIX elevato: {vix_now:.1f} — stress di mercato (soglia critica 30)")
                elif vix_now > 20:
                    factors.append(f"VIX in rialzo: {vix_now:.1f} — volatilità moderata")
                else:
                    factors.append(f"VIX basso: {vix_now:.1f} — mercato tranquillo")
        except Exception:
            pass
        try:
            fred = FredSimpleClient()
            if fred.has_api_key:
                cpi_df = fred.fetch_series("CPIAUCSL", limit=13)
                if cpi_df is not None and len(cpi_df) >= 13:
                    latest = float(cpi_df["value"].iloc[-1])
                    year_ago = float(cpi_df["value"].iloc[-13])
                    cpi_yoy = (latest / year_ago - 1) * 100
                    factors.append(f"CPI YoY: {cpi_yoy:.1f}% — {'⚠️ sopra target Fed 2%' if cpi_yoy > 2.5 else 'vicino al target'}")
        except Exception:
            pass
        if not factors:
            factors = [
                "Dati risk factor non disponibili — configura FRED_API_KEY in .env",
            ]
        return factors

    risk_factors = _cached_risk_factors()
    for i, factor in enumerate(risk_factors, 1):
        st.info(f"{i}. {factor}")


if __name__ == "__main__":  # pragma: no cover
    render_page("Market Overview", "📊", body_market_overview)