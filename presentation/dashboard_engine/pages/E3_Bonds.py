# ruff: noqa: N999
"""E3 — Bonds (v7.1.2 hotfix).

Risolve "yield curve hardcoded" segnalato in ULTERIORI_ERRORI.txt.
La versione precedente usava ``build_mock_yield_curve()`` con valori
fissi [4.85, 4.78, 4.62, 4.30, 4.18, 4.36, 4.55].

Ora la pagina:
  - Fetcha yield curve reale da FRED via FredSimpleClient (DGS1MO, DGS3MO,
    DGS6MO, DGS1, DGS2, DGS5, DGS10, DGS30).
  - Cache @st.cache_data(ttl=3600) — la curva e' aggiornata 1 volta/ora
    (FRED pubblica daily, no point in fetching piu' spesso).
  - Fallback: se FRED key mancante o fetch fallisce, mostra messaggio
    chiaro che indirizza a E0/.env (niente piu' yield curve falsa).
  - Calcoli aggiuntivi: spread 10Y-3M (Estrella-Mishkin) e 10Y-2Y.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from engine.market_data.fred_simple_client import (
    FredKeyMissingError,
    FredSimpleClient,
    FredSimpleError,
)
from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.2"

__all__ = ["body_bonds"]

# Cache TTL: la yield curve viene rilasciata da FRED una volta al giorno,
# 60 minuti di TTL sono ampi e tagliano gli HTTP storm sui rerender.
_CACHE_TTL_S = 3600


def _cached_fetch_yield_curve() -> tuple[pd.DataFrame, str | None]:
    """Wrapper con cache Streamlit. Ritorna (df, error_message).

    error_message = None se il fetch e' andato bene; altrimenti contiene
    una descrizione user-facing del problema.
    """
    try:
        import streamlit as st

        @st.cache_data(ttl=CACHE_TTL.MACRO_CONVICTION, show_spinner=False)
        def _fn() -> tuple[pd.DataFrame, str | None]:
            return _fetch_yield_curve_inner()

        return _fn()
    except ImportError:  # pragma: no cover
        return _fetch_yield_curve_inner()


def _fetch_yield_curve_inner() -> tuple[pd.DataFrame, str | None]:
    """Fetch effettivo. Separata per testabilita' (no @cache_data)."""
    client = FredSimpleClient()
    if not client.has_api_key:
        return pd.DataFrame(), (
            "FRED API key non configurata. Aggiungi `FRED_API_KEY` al file "
            "`.env` (registrati gratis su https://fredaccount.stlouisfed.org/apikey)."
        )
    try:
        df = client.fetch_yield_curve()
    except FredKeyMissingError as exc:
        return pd.DataFrame(), str(exc)
    except FredSimpleError as exc:
        return pd.DataFrame(), f"Errore FRED: {exc}"
    if df.empty:
        return pd.DataFrame(), "FRED ha risposto ma nessuna serie ha dati recenti."
    return df, None


def _render_curve_chart(  # pragma: no cover -- Streamlit
    tokens: DesignTokens, st_module, df: pd.DataFrame
) -> None:
    """Disegna la curva con Plotly."""
    try:
        import plotly.graph_objects as go
    except ImportError:
        st_module.warning("plotly non installato — installa con `poetry install`.")
        return

    fig = go.Figure(
        go.Scatter(
            x=df["tenor"],
            y=df["yield_pct"],
            line={"color": tokens.colors.accent_primary, "width": 3},
            mode="lines+markers",
            name="Today",
        )
    )
    fig.update_layout(
        template=tokens.plotly.template,
        paper_bgcolor=tokens.plotly.paper_bgcolor,
        plot_bgcolor=tokens.plotly.plot_bgcolor,
        font={
            "family": tokens.plotly.font_family,
            "color": tokens.plotly.font_color,
        },
        height=tokens.plotly.height_md,
        yaxis_title="Yield %",
        xaxis_title="Tenor",
    )
    st_module.plotly_chart(fig, use_container_width=True)


def _spread(df: pd.DataFrame, tenor_long: str, tenor_short: str) -> float | None:
    """Calcola spread (long - short). Ritorna None se uno dei tenor manca."""
    long_rows = df.loc[df["tenor"] == tenor_long, "yield_pct"]
    short_rows = df.loc[df["tenor"] == tenor_short, "yield_pct"]
    if long_rows.empty or short_rows.empty:
        return None
    return float(long_rows.iloc[0] - short_rows.iloc[0])


def body_bonds(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    render_section_header(
        "💵 Yield Curve · US Treasuries (FRED)",
        "Tassi reali per tenor da 1M a 30Y · aggiornamento orario",
    )

    cols_top = st.columns([3, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="e3_refresh"):
            st.cache_data.clear()
            st.rerun()

    df, error = _cached_fetch_yield_curve()

    if error is not None:
        st.error(f"❌ {error}")
        st.info(
            "💡 **Cosa fare:** vai in **📡 API Health** e verifica lo stato "
            "delle API key. Se FRED appare 'Configurata' ma il fetch fallisce, "
            "potrebbe esserci un problema di rete temporaneo."
        )
        return

    if df.empty:
        st.warning("Yield curve non disponibile.")
        return

    # Mostra data dell'ultimo dato disponibile (FRED pubblica T+1 di solito).
    latest_obs = df["observation_date"].max()
    st.caption(f"📅 Ultimo dato FRED: **{latest_obs}**")

    _render_curve_chart(tokens, st, df)

    # Tabella valori esatti
    st.dataframe(
        df.assign(yield_pct=df["yield_pct"].map(lambda v: f"{v:.2f}%"))[
            ["tenor", "series_id", "yield_pct", "observation_date"]
        ].rename(
            columns={
                "tenor": "Tenor",
                "series_id": "FRED Series",
                "yield_pct": "Yield",
                "observation_date": "Data",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    # Spread analitici
    render_section_header(
        "📐 Spread chiave",
        "10Y-3M (Estrella-Mishkin) e 10Y-2Y per leading recessione",
    )
    cols = st.columns(3)
    spread_10y_3m = _spread(df, "10Y", "3M")
    spread_10y_2y = _spread(df, "10Y", "2Y")
    spread_30y_5y = _spread(df, "30Y", "5Y")

    if spread_10y_3m is not None:
        cols[0].metric(
            "Spread 10Y-3M",
            f"{spread_10y_3m:+.2f}%",
            help="Estrella-Mishkin: inversione = recessione 12M con prob > 50%",
        )
        if spread_10y_3m < 0:
            cols[0].error("⚠️ INVERSA")
    if spread_10y_2y is not None:
        cols[1].metric(
            "Spread 10Y-2Y",
            f"{spread_10y_2y:+.2f}%",
            help="Spread classico: storicamente preannuncia recessioni 18-24M",
        )
        if spread_10y_2y < 0:
            cols[1].error("⚠️ INVERSA")
    if spread_30y_5y is not None:
        cols[2].metric(
            "Spread 30Y-5Y",
            f"{spread_30y_5y:+.2f}%",
            help="Pendenza long-end: indica inflazione attesa",
        )

    st.caption(
        "📌 Fonte: Federal Reserve Economic Data (FRED) — St. Louis Fed · "
        f"Cache TTL {_CACHE_TTL_S // 60} min"
    )


if __name__ == "__main__":  # pragma: no cover
    render_page("Bonds", "💵", body_bonds)
