# ruff: noqa: N999
"""M4 — PMI & Leading Indicators ★ NUOVA (v8.0)."""
from __future__ import annotations

__version__ = "8.2.0"
__all__ = ["body_m4_pmi_leading_indicators"]

_SERIES_CFG = [
    (
        "ISM Manufacturing (NAPM)",
        "NAPM",
        50.0,
        "PMI manifatturiero USA. **Sopra 50** = espansione del settore industriale, "
        "**sotto 50** = contrazione. Indicatore leading del ciclo economico con 3–6 mesi "
        "di anticipo sul PIL. Pesa ~12% dell'economia ma anticipa ordini, occupazione e scorte.",
    ),
    (
        "Industrial Production (INDPRO)",
        "INDPRO",
        None,
        "Indice della produzione industriale USA (base 2017 = 100), pubblicato dalla Fed di St. Louis. "
        "Copre manifattura, miniere e utilities. Correlato direttamente con il PIL industriale; "
        "tre cali consecutivi segnalano recessione tecnica nel settore.",
    ),
    (
        "Housing Starts (HOUST)",
        "HOUST",
        1400,
        "Nuove costruzioni residenziali avviate (migliaia, SAAR). Soglia **1.400k** = livello "
        "storico di equilibrio pre-crisi. Indicatore leading del mercato immobiliare, del credito "
        "al consumo e dell'occupazione nel settore edile (circa 3–4 mesi di anticipo).",
    ),
    (
        "UMich Consumer Sentiment (UMCSENT)",
        "UMCSENT",
        70,
        "Fiducia dei consumatori — Università del Michigan (scala 0–100). Soglia **70** = territorio "
        "di espansione. Anticipa la spesa per consumi privati (~70% del PIL USA) con 1–2 mesi di "
        "anticipo. Crolli rapidi sotto 60 storicamente precedono recessioni.",
    ),
]


def _load_pmi_series(sid: str):
    from shared.db.macro_repo import get_macro_repository
    return get_macro_repository().read_macro(sid)


def body_m4_pmi_leading_indicators(st, tokens) -> None:  # pragma: no cover
    from presentation.ui.auth import require_auth
    from presentation.ui.cache_policy import CACHE_TTL

    require_auth()
    st.title("🌍 Macro — PMI & Leading Indicators")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="m4_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.caption("ISM Manufacturing · Industrial Production · Housing Starts · Consumer Sentiment — ultimi 5 anni.")

    cached_load = st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION)(_load_pmi_series)

    try:
        import plotly.graph_objects as go

        any_data = False

        for label, sid, threshold, description in _SERIES_CFG:
            try:
                df = cached_load(sid)
                if df is None or df.empty:
                    st.caption(f"{label}: N/D")
                    continue
                any_data = True
                df_plot = df.tail(60)
                values = df_plot["value"].dropna()
                latest = float(values.iloc[-1])

                v_min, v_max = float(values.min()), float(values.max())
                padding = (v_max - v_min) * 0.08 or abs(v_min) * 0.05 or 1.0
                y_low = v_min - padding
                y_high = v_max + padding

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_plot["ts"], y=values,
                    mode="lines", line=dict(color="#3B82F6", width=2),
                    fill="tozeroy" if y_low <= 0 else None,
                    fillcolor="rgba(59,130,246,0.13)",
                ))
                if threshold is not None:
                    fig.add_hline(
                        y=threshold, line_dash="dash", line_color="#6B7280",
                        annotation_text=str(threshold),
                        annotation_position="right",
                    )
                fig.update_layout(
                    height=220,
                    title=dict(text=f"{label}  —  ultimo: <b>{latest:.1f}</b>", font=dict(size=14)),
                    margin=dict(l=0, r=60, t=36, b=0),
                    showlegend=False,
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    yaxis=dict(range=[y_low, y_high], gridcolor="rgba(107,114,128,0.15)"),
                    xaxis=dict(gridcolor="rgba(107,114,128,0.15)"),
                )
                st.plotly_chart(fig, use_container_width=True)

                with st.expander("ℹ️ Informazioni sull'indicatore"):
                    st.markdown(description)

                st.divider()

            except Exception as exc:
                st.warning(f"{label}: {type(exc).__name__}: {exc}")

        if not any_data:
            st.info(
                "Nessun dato disponibile. "
                "Vai su **M1 — Macro Dashboard** e premi **📥 Carica da FRED** "
                "per popolare le serie macroeconomiche."
            )
    except Exception as exc:
        st.warning(f"Dati PMI non disponibili: {exc}")
        st.info(
            "Vai su **M1 — Macro Dashboard** e premi **📥 Carica da FRED**, "
            "oppure avvia lo scheduler: `python scripts/run_scheduler.py`"
        )
