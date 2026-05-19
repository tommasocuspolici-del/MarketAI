# ruff: noqa: N999
"""M7 — IB Forecast Consensus (v1.0).

Fase 8: previsioni aggregate da IB reports, FED SEP, IMF/World Bank.
Regola 33: solo previsioni reali da DB. Badge fonte su ogni dato.
Regola 34: timestamp aggiornamento visibile. Bottone Aggiorna.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_ib_consensus"]


def _signal_badge(score: float | None) -> str:
    if score is None:
        return "⚪ N/D"
    if score >= 0.3:
        return "🟢 Bullish"
    if score <= -0.3:
        return "🔴 Bearish"
    return "⚪ Neutro"


def _horizon_label(h: str) -> str:
    _map = {
        "2024": "2024", "2025": "2025", "2026": "2026",
        "12M": "12 mesi", "6M": "6 mesi", "Q1": "Q1", "Q2": "Q2",
    }
    return _map.get(h, h)


def body_ib_consensus(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    import streamlit as st

    from engine.ib_forecast.consensus_builder import ConsensusBuilder
    from shared.db.duckdb_client import get_duckdb_client
    from shared.feature_flags import is_enabled

    render_section_header(
        "🏦 IB Forecast Consensus",
        "Previsioni aggregate da IB Reports · FED SEP · IMF/World Bank — dati reali",
    )

    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="m7_refresh"):
            st.cache_data.clear()
            st.rerun()
    with cols_top[2]:
        run_pipeline = st.button("📥 Aggiorna previsioni", key="m7_run")

    if not is_enabled("ib_forecast_enabled"):
        st.warning("⚠️ IB Forecast Engine non attivo. Abilita `ib_forecast_enabled` in feature_flags.yaml.")
        return

    if run_pipeline:
        with st.spinner("Aggiornamento previsioni IB in corso..."):
            try:
                from engine.ib_forecast.ib_rss_fetcher import IBRSSFetcher
                from engine.ib_forecast.imf_wb_outlook_fetcher import IMFWorldBankFetcher
                client = get_duckdb_client()
                IBRSSFetcher(client).fetch_and_persist()
                IMFWorldBankFetcher(client).fetch_and_persist()
                st.success("✅ Previsioni aggiornate")
                st.cache_data.clear()
            except Exception as exc:
                st.error(f"Errore aggiornamento: {exc}")

    @st.cache_data(ttl=86400)
    def _load_consensus() -> dict:
        try:
            client = get_duckdb_client()
            builder = ConsensusBuilder(client)
            consensus_list = builder.build(lookback_days=60)
            signal = builder.build_signal(consensus_list)
            return {"consensus": consensus_list, "signal": signal}
        except Exception as exc:
            return {"error": str(exc)}

    @st.cache_data(ttl=86400)
    def _load_raw_forecasts() -> list:
        try:
            rows = get_duckdb_client().query(
                "SELECT source, indicator, horizon, value, unit, extraction_method, fetched_at "
                "FROM ib_forecasts ORDER BY fetched_at DESC LIMIT 100"
            )
            return rows or []
        except Exception:
            return []

    # ── SEZIONE A — Segnale IB ────────────────────────────────────────────
    data = _load_consensus()

    if "error" in data:
        st.error(f"❌ Errore: {data['error']}")
        st.info(
            "**Come popolare:** clicca '📥 Aggiorna previsioni' per scaricare i dati IB "
            "da IB RSS feed e IMF/World Bank API."
        )
        return

    signal = data.get("signal")
    if signal:
        st.divider()
        render_section_header("⚡ Segnale IB Aggregato")
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.metric("Score IB", f"{signal.score:+.3f}",
                      help="Score composito [-1,+1] da GDP + CPI + Tassi + Equity")
        with c2:
            v = signal.gdp_signal
            st.metric("GDP Signal", f"{v:+.2f}" if v is not None else "N/D")
        with c3:
            v = signal.inflation_signal
            st.metric("CPI Signal", f"{v:+.2f}" if v is not None else "N/D")
        with c4:
            v = signal.rates_signal
            st.metric("Tassi Signal", f"{v:+.2f}" if v is not None else "N/D")
        with c5:
            v = signal.equity_signal
            st.metric("Equity Signal", f"{v:+.2f}" if v is not None else "N/D")

        badge = _signal_badge(signal.score)
        st.markdown(f"**Outlook IB aggregato:** {badge} · Fonti: {signal.source_count}")
        st.caption(
            f"🕐 Calcolato: {signal.signal_date.strftime('%Y-%m-%d %H:%M')} UTC · "
            f"Qualità dati: **{signal.data_quality}**"
        )

    # ── SEZIONE B — Consensus per Indicatore ─────────────────────────────
    st.divider()
    render_section_header("📋 Consensus per Indicatore")

    consensus_list = data.get("consensus", [])

    if consensus_list:
        import pandas as pd

        rows_df = []
        for c in consensus_list:
            rows_df.append({
                "Indicatore":  c.indicator,
                "Orizzonte":   _horizon_label(c.horizon),
                "Consensus":   f"{c.consensus_value:.2f}" if c.consensus_value is not None else "N/D",
                "Range":       (
                    f"{c.consensus_low:.2f}–{c.consensus_high:.2f}"
                    if c.consensus_low is not None else "—"
                ),
                "Fonti":       c.source_count,
                "Metodo":      c.method,
                "Qualità":     c.data_quality,
            })
        df = pd.DataFrame(rows_df)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Nessun consensus disponibile. Aggiorna le previsioni per popolare il DB.")

    # ── SEZIONE C — Previsioni Raw ─────────────────────────────────────────
    st.divider()
    render_section_header("🔍 Previsioni Grezze")

    with st.expander("Mostra previsioni individuali", expanded=False):
        raw_rows = _load_raw_forecasts()
        if raw_rows:
            import pandas as pd
            df_raw = pd.DataFrame(raw_rows, columns=[
                "Fonte", "Indicatore", "Orizzonte", "Valore", "Unità",
                "Metodo estrazione", "Fetched at",
            ])
            df_raw["Fetched at"] = pd.to_datetime(df_raw["Fetched at"]).dt.strftime("%Y-%m-%d %H:%M")
            st.dataframe(df_raw, use_container_width=True, hide_index=True)
            st.caption(f"Mostrando ultime {len(raw_rows)} previsioni · Fonte: ib_forecasts DB")
        else:
            st.info("Nessuna previsione grezza in DB.")

    # ── SEZIONE D — LLM Status ────────────────────────────────────────────
    if is_enabled("ib_llm_extraction"):
        st.divider()
        st.info("🤖 **IB LLM Extraction attiva** — Stage 2 parsing semantico tramite Ollama.")
    else:
        with st.expander("💡 Upgrade: IB LLM Extraction (Stage 2)", expanded=False):
            st.markdown(
                "L'estrazione LLM (Stage 2) migliora il parsing di testi IB complessi. "
                "Attiva `ib_llm_extraction: true` in `feature_flags.yaml` dopo aver "
                "configurato Ollama (da S2_Settings)."
            )


if __name__ == "__main__":  # pragma: no cover
    render_page("IB Consensus", "🏦", body_ib_consensus)
