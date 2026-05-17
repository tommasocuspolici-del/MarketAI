# ruff: noqa: N999
"""M7 — IB Consensus Dashboard (v1.0 — Fase 8).

Proiezioni aggregate da Fed SEP, IMF WEO, World Bank e IB RSS.
Regola 33: badge fonte visibile per ogni valore — zero previsioni simulate.
Regola 34: dati letti da ib_consensus e ib_forecasts (DuckDB, TTL 86400s).
"""
from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["body_m7_ib_consensus"]


def body_m7_ib_consensus(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    require_auth()

    st.title("🏦 Macro — IB Consensus Forecast")
    st.caption("Fed SEP · IMF WEO · World Bank · RSS IB Report · Segnale IB [-1,+1]")

    cols_top = st.columns([3, 1, 1])
    with cols_top[1]:
        if st.button("📥 Aggiorna Sorgenti", key="m7_fetch"):
            try:
                from shared.db.duckdb_client import get_duckdb_client
                from engine.ib_forecast.ib_rss_fetcher import IBRSSFetcher
                from engine.ib_forecast.fed_projections_parser import FedProjectionsParser
                from engine.ib_forecast.imf_wb_outlook_fetcher import IMFWBOutlookFetcher
                from engine.ib_forecast.forecast_extractor import ForecastExtractor
                from engine.ib_forecast.consensus_builder import ConsensusBuilder
                from engine.ib_forecast.ib_signal_generator import IBSignalGenerator

                db = get_duckdb_client()
                with st.spinner("Fetching IB reports…"):
                    IBRSSFetcher(client=db).fetch_all()
                with st.spinner("Fetching Fed SEP…"):
                    FedProjectionsParser(client=db).fetch_latest_projections()
                with st.spinner("Fetching IMF/WB…"):
                    IMFWBOutlookFetcher(client=db).fetch_all()

                consensus_list = ConsensusBuilder(client=db).build()
                signal = IBSignalGenerator(client=db).generate(consensus_list)
                score_str = f"{signal.score:+.3f}" if signal else "N/A"
                st.success(f"Aggiornato — {len(consensus_list)} consensus · Segnale: {score_str}")
            except Exception as exc:
                st.error(f"Fetch fallito: {exc}")
    with cols_top[2]:
        if st.button("🔄 Aggiorna", key="m7_refresh"):
            st.cache_data.clear()
            st.rerun()

    try:
        from shared.db.duckdb_client import get_duckdb_client
        import pandas as pd
        db = get_duckdb_client()
    except Exception as exc:
        st.error(f"DB non disponibile: {exc}")
        return

    tab_signal, tab_consensus, tab_detail = st.tabs([
        "⚡ Segnale IB",
        "📊 Consensus Tabella",
        "🔍 Dettaglio Sorgenti",
    ])

    # ── Tab 1: Segnale IB ─────────────────────────────────────────────────────
    with tab_signal:
        st.subheader("Segnale IB — Composite Signal v3")
        try:
            rows = db.query(
                "SELECT signal_date, score, gdp_signal, inflation_signal, "
                "rates_signal, equity_signal, source_count, data_quality "
                "FROM ib_signal ORDER BY signal_date DESC LIMIT 1"
            )
            if not rows:
                st.info(
                    "Nessun segnale IB calcolato. "
                    "Clicca **📥 Aggiorna Sorgenti** per generarlo."
                )
            else:
                r = rows[0]
                score = float(r[1])
                label = "🟢 BULLISH" if score > 0.2 else "🔴 BEARISH" if score < -0.2 else "🟡 NEUTRO"
                col1, col2, col3, col4, col5 = st.columns(5)
                col1.metric("Score IB", f"{score:+.3f}", label)
                col2.metric("GDP Signal", f"{r[2]:+.2f}" if r[2] is not None else "N/A")
                col3.metric("CPI Signal", f"{r[3]:+.2f}" if r[3] is not None else "N/A")
                col4.metric("Rates Signal", f"{r[4]:+.2f}" if r[4] is not None else "N/A")
                col5.metric("Fonti", str(r[6] or 0))
                st.caption(
                    f"Qualità dati: **{r[7]}** · Aggiornato: {r[0]} "
                    f"(Regola 34: cache 86400s)"
                )
        except Exception as exc:
            st.warning(f"Segnale IB non disponibile: {exc}")

    # ── Tab 2: Tabella consensus ──────────────────────────────────────────────
    with tab_consensus:
        st.subheader("Consensus per Indicatore")
        try:
            rows = db.query(
                "SELECT indicator, horizon, consensus_value, consensus_low, consensus_high, "
                "source_count, data_quality, computed_at "
                "FROM ib_consensus ORDER BY indicator, horizon"
            )
            if not rows:
                st.info("Nessun consensus disponibile. Clicca **📥 Aggiorna Sorgenti**.")
            else:
                df = pd.DataFrame(rows, columns=[
                    "Indicatore", "Orizzonte", "Consenso",
                    "Min", "Max", "Fonti", "Qualità", "Calcolato"
                ])
                df["Consenso"] = df["Consenso"].apply(
                    lambda v: f"{v:.2f}%" if v is not None else "N/A"
                )
                df["Range"] = df.apply(
                    lambda r: f"[{r['Min']:.1f}; {r['Max']:.1f}]"
                    if r["Min"] is not None and r["Max"] is not None else "—",
                    axis=1,
                )
                st.dataframe(
                    df[["Indicatore", "Orizzonte", "Consenso", "Range", "Fonti", "Qualità"]],
                    use_container_width=True,
                    hide_index=True,
                )

                # Fonte badge (Regola 33)
                st.caption(
                    "📌 Fonti: **Fed SEP** · **IMF WEO** · **World Bank** · **IB RSS** "
                    "— nessun dato simulato."
                )
        except Exception as exc:
            st.warning(f"Consensus non disponibile: {exc}")

    # ── Tab 3: Dettaglio sorgenti ─────────────────────────────────────────────
    with tab_detail:
        st.subheader("Previsioni per Sorgente")
        try:
            rows = db.query(
                "SELECT source, indicator, horizon, value, confidence, fetched_at "
                "FROM ib_forecasts "
                "WHERE fetched_at >= NOW() - INTERVAL 7 DAY "
                "ORDER BY source, indicator, fetched_at DESC"
            )
            if not rows:
                st.info("Nessuna previsione recente. Clicca **📥 Aggiorna Sorgenti**.")
            else:
                df = pd.DataFrame(rows, columns=[
                    "Sorgente", "Indicatore", "Orizzonte", "Valore", "Confidenza", "Aggiornato"
                ])
                # Timestamp aggiornamento visibile (Regola 34)
                df["Aggiornato"] = df["Aggiornato"].astype(str).str[:16]
                df["Valore"] = df["Valore"].apply(
                    lambda v: f"{v:.2f}%" if v is not None else "N/A"
                )
                df["Confidenza"] = df["Confidenza"].apply(
                    lambda v: f"{v:.0%}" if v is not None else "—"
                )

                for source in df["Sorgente"].unique():
                    sub = df[df["Sorgente"] == source]
                    src_icon = {
                        "fed_sep": "🏛️ Fed SEP",
                        "imf_weo": "🌐 IMF WEO",
                        "world_bank": "🌍 World Bank",
                    }.get(source, f"📄 {source}")
                    with st.expander(f"{src_icon} — {len(sub)} previsioni"):
                        st.dataframe(
                            sub[["Indicatore", "Orizzonte", "Valore", "Confidenza", "Aggiornato"]],
                            use_container_width=True,
                            hide_index=True,
                        )
        except Exception as exc:
            st.warning(f"Dettaglio non disponibile: {exc}")
