# ruff: noqa: N999
"""M6 — Valuation & P/E Ratios (v1.0).

Fase 6: P/E Trailing, Forward PE, Shiller CAPE, ERP con dati reali da DB.
Regola 33: ogni valore mostra badge fonte dati.
Regola 34: timestamp ultimo aggiornamento visibile sotto ogni KPI.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_valuation_pe"]


def _erp_color(regime: str | None) -> str:
    if regime == "attractive":
        return "🟢"
    if regime == "fair":
        return "🟡"
    if regime in ("expensive", "extreme"):
        return "🔴"
    return "⚪"


def _label_badge(label: str | None) -> str:
    _map = {
        "deep_value":     "🟢 Deep Value",
        "cheap":          "🟢 Cheap",
        "fair_value":     "⚪ Fair Value",
        "stretched":      "🟡 Stretched",
        "bubble_warning": "🔴 Bubble Warning",
    }
    return _map.get(str(label), "⚪ N/D")


def _zscore_delta(z: float | None) -> str:
    """Representa z-score come Δ vs media storica."""
    if z is None:
        return "—"
    sign = "+" if z >= 0 else ""
    return f"{sign}{z:.1f}σ"


def body_valuation_pe(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    import streamlit as st

    from engine.analytics.valuation.pe_calculator import PECalculator
    from engine.analytics.valuation.pe_context_builder import PEContextBuilder
    from engine.analytics.valuation.valuation_signal_generator import ValuationSignalGenerator
    from shared.db.duckdb_client import get_duckdb_client
    from shared.feature_flags import is_enabled

    render_section_header(
        "📊 Valuation & P/E Ratios",
        "Trailing PE · Forward PE · Shiller CAPE · ERP — dati reali, aggiornati orario",
    )

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="m6_refresh"):
            st.cache_data.clear()
            st.rerun()

    if not is_enabled("valuation_pe_engine"):
        st.warning("⚠️ Modulo valutazione non attivo. Abilita `valuation_pe_engine` in feature_flags.yaml.")
        return

    @st.cache_data(ttl=3600)
    def _load_valuation(ticker: str) -> dict:
        try:
            client = get_duckdb_client()
            calc    = PECalculator(client)
            builder = PEContextBuilder(client)
            metrics = calc.compute(ticker)
            if metrics is None:
                return {"error": "Dati non disponibili per questo ticker"}
            ctx = builder.build(metrics)
            return {"metrics": metrics, "context": ctx}
        except Exception as exc:
            return {"error": str(exc)}

    @st.cache_data(ttl=1800)
    def _load_signal(ticker: str) -> dict:
        try:
            from shared.db.duckdb_client import get_duckdb_client as _gdc
            client = _gdc()
            gen    = ValuationSignalGenerator(client)
            result = gen.compute(ticker)
            return {"result": result}
        except Exception as exc:
            return {"error": str(exc)}

    @st.cache_data(ttl=86400)
    def _load_cape_history(n: int = 240) -> list:
        try:
            from shared.db.duckdb_client import get_duckdb_client as _gdc
            rows = _gdc().query(
                "SELECT data_date, cape_ratio FROM shiller_cape_historical "
                "WHERE cape_ratio IS NOT NULL ORDER BY data_date DESC LIMIT ?",
                [n],
            )
            return list(reversed(rows)) if rows else []
        except Exception:
            return []

    ticker = st.selectbox("Ticker", ["^GSPC", "SPY", "QQQ"], index=0, key="m6_ticker")

    # ── SEZIONE A — KPI ────────────────────────────────────────────────────
    st.divider()
    render_section_header("📐 Metriche di Valutazione")

    data = _load_valuation(ticker)

    if "error" in data:
        st.error(f"❌ Errore caricamento dati: {data['error']}")
        st.info(
            "**Come popolare il DB:**\n"
            "Esegui `scripts/scheduler_jobs_data.py` oppure usa E0_API_Health per verificare "
            "le connessioni alle sorgenti dati."
        )
    else:
        metrics = data["metrics"]
        ctx     = data["context"]
        ts_str  = metrics.metric_date.strftime("%Y-%m-%d")

        cols = st.columns(4)

        with cols[0]:
            pe_t = metrics.trailing_pe
            z_t  = ctx.get("trailing_zscore")
            pct_t = ctx.get("trailing_pct")
            st.metric(
                label="Trailing P/E",
                value=f"{pe_t:.1f}x" if pe_t else "N/D",
                delta=_zscore_delta(z_t),
                help="Price / EPS ultimi 4 trimestri. Fonte: Alpha Vantage / EDGAR.",
            )
            if pct_t is not None:
                st.caption(f"Percentile 20Y: {pct_t:.0f}°")

        with cols[1]:
            pe_f = metrics.forward_pe
            z_f  = ctx.get("forward_zscore")
            pct_f = ctx.get("forward_pct")
            st.metric(
                label="Forward P/E",
                value=f"{pe_f:.1f}x" if pe_f else "N/D",
                delta=_zscore_delta(z_f),
                help="Price / EPS forward 12M (stima consenso). Fonte: Alpha Vantage / FRED.",
            )
            if pct_f is not None:
                st.caption(f"Percentile 20Y: {pct_f:.0f}°")

        with cols[2]:
            cape = metrics.shiller_cape
            z_c  = ctx.get("cape_zscore")
            pct_c = ctx.get("cape_pct")
            st.metric(
                label="Shiller CAPE",
                value=f"{cape:.1f}x" if cape else "N/D",
                delta=_zscore_delta(z_c),
                help="Price / EPS reale media 10 anni (CPI-adjusted). Fonte: Yale Shiller.",
            )
            if pct_c is not None:
                st.caption(f"Percentile 20Y: {pct_c:.0f}°")

        with cols[3]:
            erp = metrics.erp_implied
            regime = metrics.erp_regime
            erp_str = f"{erp*100:.2f}%" if erp is not None else "N/D"
            st.metric(
                label=f"ERP {_erp_color(regime)}",
                value=erp_str,
                help="Equity Risk Premium = Earnings Yield (1/ForwardPE) − DGS10. Fonte: FRED.",
            )
            if regime:
                st.caption(f"Regime: **{regime}**")

        # Label composito
        label = ctx.get("label")
        composite = ctx.get("composite_score")
        st.divider()
        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown(f"**Valutazione composita:** {_label_badge(label)}")
        with c2:
            if composite is not None:
                st.metric("Score composito", f"{composite:+.2f}")
        st.caption(f"🕐 Ultimo aggiornamento: {ts_str} · Fonte: DB locale")

    # ── SEZIONE B — Chart CAPE Storico ────────────────────────────────────
    st.divider()
    render_section_header("📈 Shiller CAPE — Serie Storica")

    cape_rows = _load_cape_history()

    if cape_rows:
        import pandas as pd
        df_cape = pd.DataFrame(cape_rows, columns=["data_date", "cape_ratio"])
        df_cape["data_date"] = pd.to_datetime(df_cape["data_date"])
        df_cape = df_cape.sort_values("data_date")

        mean_cape  = df_cape["cape_ratio"].mean()
        std_cape   = df_cape["cape_ratio"].std()
        df_cape["mean"]   = mean_cape
        df_cape["plus1s"] = mean_cape + std_cape
        df_cape["plus2s"] = mean_cape + 2 * std_cape
        df_cape["minus1s"] = mean_cape - std_cape

        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_cape["data_date"], y=df_cape["cape_ratio"],
            name="CAPE", line=dict(color=tokens.accent_primary, width=2),
        ))
        fig.add_trace(go.Scatter(
            x=df_cape["data_date"], y=df_cape["plus2s"],
            name="+2σ", line=dict(color="red", dash="dash", width=1),
        ))
        fig.add_trace(go.Scatter(
            x=df_cape["data_date"], y=df_cape["plus1s"],
            name="+1σ", line=dict(color="orange", dash="dot", width=1),
        ))
        fig.add_trace(go.Scatter(
            x=df_cape["data_date"], y=df_cape["mean"],
            name="Media", line=dict(color="gray", dash="dash", width=1),
        ))
        fig.add_trace(go.Scatter(
            x=df_cape["data_date"], y=df_cape["minus1s"],
            name="−1σ", line=dict(color="green", dash="dot", width=1),
        ))
        fig.update_layout(
            height=350, margin=dict(l=0, r=0, t=20, b=0),
            plot_bgcolor=tokens.bg_secondary, paper_bgcolor=tokens.bg_secondary,
            font=dict(color=tokens.text_primary),
            legend=dict(orientation="h"),
            yaxis_title="CAPE",
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(f"Serie: {len(cape_rows)} osservazioni mensili · Fonte: shiller_cape_historical DB")
    else:
        st.info(
            "Dati CAPE non ancora presenti in DB. "
            "Esegui lo scheduler per popolare `shiller_cape_historical`."
        )

    # ── SEZIONE C — Implied Return ────────────────────────────────────────
    st.divider()
    render_section_header("🔮 Rendimento Implicito a 10 Anni")

    if "metrics" in data and data["metrics"].shiller_cape is not None:
        cape_val = data["metrics"].shiller_cape
        st.markdown(
            "Basato sul CAPE corrente — formula: `1/CAPE - expected_inflation + growth`"
        )
        scenarios = {
            "Pessimistico":  {"inflation": 0.035, "growth": 0.01},
            "Base":          {"inflation": 0.025, "growth": 0.02},
            "Ottimistico":   {"inflation": 0.020, "growth": 0.03},
        }
        cols_s = st.columns(3)
        for i, (name, params) in enumerate(scenarios.items()):
            cape_yield = 1.0 / cape_val if cape_val > 0 else 0
            ret = cape_yield - params["inflation"] + params["growth"]
            with cols_s[i]:
                color = "normal" if ret > 0 else "inverse"
                st.metric(
                    label=name,
                    value=f"{ret*100:.1f}% annuo",
                    delta=f"inflazione {params['inflation']*100:.1f}%",
                    delta_color=color,
                )
    else:
        st.info("Rendimento implicito non disponibile — CAPE non presente in DB.")

    # ── SEZIONE D — Valuation Signal ─────────────────────────────────────
    st.divider()
    render_section_header("⚡ Segnale Valutazione → Composite Signal v3")

    sig_data = _load_signal(ticker)
    if "error" in sig_data:
        st.warning(f"Segnale non disponibile: {sig_data['error']}")
    else:
        result = sig_data.get("result")
        if result:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Score Valutazione", f"{result.valuation_score:+.3f}")
            with c2:
                st.metric("Contributo Trailing PE", f"{result.trailing_pe_signal:+.3f}")
            with c3:
                st.metric("Contributo CAPE", f"{result.cape_signal:+.3f}")
            st.caption(
                "Score [-1,+1]: +1 = deep value (azioni economiche), -1 = bubble warning. "
                f"Label: **{_label_badge(result.label)}**"
            )


if __name__ == "__main__":  # pragma: no cover
    render_page("Valuation & P/E", "📊", body_valuation_pe)
