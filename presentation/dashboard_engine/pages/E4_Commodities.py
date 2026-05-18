# ruff: noqa: N999
"""E4 — Commodities (v7.1).

Risolve "prezzi commodities incongruenti con il mercato" della v6:
ora i prezzi sono live da yfinance e ognuno ha la valuta corretta indicata.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from engine.market_data.live_market_service import (
    MarketKpi,
    get_live_market_service,
)
from presentation.ui.components.metric_card import (
    MetricSpec,
    render_metric_row,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page
from presentation.ui.session_keys import SK

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.0"

__all__ = ["body_commodities"]

# Le commodities che vogliamo mostrare in pagina (subset dei KPI live).
_COMMODITIES = {"WTI", "Brent", "Gold", "Silver", "Nat Gas", "Copper"}


def _filter_commodities(kpis: list[MarketKpi]) -> list[MarketKpi]:
    """Filtra dal snapshot live solo le commodities."""
    return [k for k in kpis if k.term in _COMMODITIES]


def body_commodities(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    svc = get_live_market_service()
    if st.session_state.pop(SK.COMMODITY_FORCE_REFRESH, False):
        snapshot = svc.refresh_now()
    else:
        snapshot = svc.get_kpi_snapshot()

    render_section_header(
        "🛢️ Commodity Prices · Live",
        "Prezzi futures CME/COMEX/NYMEX · valuta indicata su ogni KPI",
    )

    cols = st.columns([3, 1])
    with cols[1]:
        if st.button("🔄 Aggiorna ora", key="commodity_refresh", use_container_width=True):
            st.session_state[SK.COMMODITY_FORCE_REFRESH] = True
            st.rerun()

    commodities = _filter_commodities(snapshot.kpis)
    if not commodities:
        st.error("❌ Dati commodities non disponibili.")
        return

    n_stale = sum(1 for k in commodities if k.is_stale)
    if n_stale == len(commodities):
        st.warning(
            f"📦 Dati da cache disco · fetchati {snapshot.fetched_at_human} "
            f"(API offline — mostrando ultimo snapshot valido)"
        )
    elif n_stale > 0:
        st.caption(f"📦 {n_stale} prezzi da cache (API parzialmente offline)")

    metrics = []
    for k in commodities:
        if k.value is None:
            metrics.append(MetricSpec(term=k.term, value="—", format_spec=k.format_spec))
            continue
        metrics.append(
            MetricSpec(
                term=k.term,
                value=k.value,
                delta=k.delta_pct,
                format_spec=k.format_spec,
                unit_override=f" {k.currency}",
                delta_pct=True,
            )
        )
    render_metric_row(tokens, metrics)

    # Spiegazione delle commodities mostrate
    with st.expander("📚 Cosa rappresentano questi prezzi?", expanded=False):
        st.markdown(
            "**WTI (West Texas Intermediate)** — greggio USA al NYMEX, "
            "benchmark petrolifero per l'emisfero occidentale, prezzato in USD/barile.\n\n"
            "**Brent** — greggio europeo all'ICE, benchmark globale "
            "(due terzi del petrolio mondiale viene prezzato su Brent), USD/barile.\n\n"
            "**Gold** — oro fisico spot, USD per oncia troy. Bene rifugio classico, "
            "copertura contro inflazione e dollaro debole.\n\n"
            "**Silver** — argento spot, USD per oncia troy. Più volatile dell'oro "
            "perché ha forte componente di domanda industriale (pannelli solari, elettronica).\n\n"
            "**Nat Gas** — gas naturale al benchmark Henry Hub, USD per MMBtu. "
            "Estremamente volatile, sensibile a meteo e stoccaggi.\n\n"
            "**Copper** — rame futures (COMEX), USD per libbra. Soprannominato "
            "*Dr. Copper* perché considerato leading indicator dell'economia "
            "globale, dato l'uso industriale pervasivo (cablaggi, motori, edilizia)."
        )

    render_section_header("Commodity / Equity Ratio Implications")
    st.info(
        "Gold/SPX ratio elevato → flight to safety attivo. "
        "Watch for risk-off rotation."
    )


if __name__ == "__main__":  # pragma: no cover
    render_page("Commodities", "🛢️", body_commodities)
