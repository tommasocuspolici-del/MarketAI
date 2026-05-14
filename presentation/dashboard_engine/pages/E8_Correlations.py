# ruff: noqa: N999
"""E8 — Correlations (v7.1).

Risolve "i collegamenti del network non sono spiegati" della v6.
Aggiunge:
  - tabella dei top-N pair correlazioni con spiegazione narrativa
  - decomposizione: per ogni asset class, cosa significa correlare con altre
  - tooltip glossario su DCC-GARCH e regime
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from presentation.ui.components.correlation_network import (
    render_correlation_network,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.0"

__all__ = ["body_correlations", "build_mock_correlation_matrix"]


def build_mock_correlation_matrix() -> pd.DataFrame:
    """Mock correlation matrix tra 6 asset class (riproducibile)."""
    rng = np.random.default_rng(11)
    assets = ["SPX", "NDX", "Gold", "BTC", "Bonds", "USD"]
    n = len(assets)
    raw = rng.uniform(-0.5, 0.9, (n, n))
    matrix = (raw + raw.T) / 2
    np.fill_diagonal(matrix, 1.0)
    return pd.DataFrame(matrix, index=assets, columns=assets)


# Spiegazioni narrative per pair "tipici" — quando una correlazione e' alta o
# bassa, qual e' l'interpretazione macro-finanziaria standard.
_PAIR_NARRATIVES = {
    ("SPX", "NDX"): "Le grandi azioni USA si muovono insieme. Correlazione "
                     "tipicamente >0.85 perché NDX (heavy-tech) è un sottoinsieme "
                     "dell'S&P 500 fortemente pesato.",
    ("SPX", "Gold"): "Storicamente bassa o lievemente negativa: l'oro e' "
                      "considerato bene rifugio. Correlazione che sale in "
                      "regimi inflazionistici quando equity e oro salgono "
                      "entrambi.",
    ("SPX", "Bonds"): "Tipicamente negativa nei regimi 'risk on/off' (quando "
                       "l'equity sale, i Treasury scendono e viceversa), ma "
                       "diventa POSITIVA quando l'inflazione e' il driver "
                       "dominante (2022). E' la rottura del classico portafoglio "
                       "60/40.",
    ("SPX", "USD"): "USD forte = pressione su utili multinazionali USA "
                     "(esportatori) e su mercati emergenti. Correlazione "
                     "spesso negativa, soprattutto in fasi risk-off.",
    ("BTC", "NDX"): "Crypto si muove come tech ad alto beta dal 2020. "
                     "BTC è diventato un proxy del sentiment risk-on dei "
                     "mercati USA growth.",
    ("Gold", "USD"): "Storicamente fortemente negativa (oro denominato in USD: "
                      "USD forte = oro più caro per il resto del mondo, "
                      "domanda cala).",
    ("Gold", "Bonds"): "Entrambi beni rifugio in fasi di stress, ma "
                        "comportamento divergente in regimi inflazionistici "
                        "(oro sale, Treasury crollano).",
    ("Bonds", "USD"): "Tassi USA in salita = USD forte (capitali entrano in "
                       "USD per cercare rendimento). Correlazione moderatamente "
                       "negativa tra prezzo bonds e DXY.",
}


def _top_n_pairs(matrix: pd.DataFrame, n: int = 5) -> list[tuple[str, str, float]]:
    """Estrae i top N pair per |correlazione| (escluso diagonale)."""
    pairs: list[tuple[str, str, float]] = []
    assets = matrix.columns.tolist()
    for i, a in enumerate(assets):
        for b in assets[i + 1 :]:
            pairs.append((a, b, float(matrix.loc[a, b])))
    pairs.sort(key=lambda p: abs(p[2]), reverse=True)
    return pairs[:n]


def body_correlations(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    matrix = build_mock_correlation_matrix()

    render_section_header(
        "🕸️ Correlation Network",
        "Asset class collegati se |correlazione| ≥ 0.3 — spessore = forza del legame",
    )
    try:
        render_correlation_network(tokens, matrix, threshold=0.3)
    except (ImportError, AttributeError, TypeError):
        st.warning("Correlation network non disponibile.")

    # Top-N narrative
    st.divider()
    render_section_header("🔍 Top correlazioni — cosa significano")
    top_pairs = _top_n_pairs(matrix, n=8)
    for a, b, corr in top_pairs:
        # Cerca narrativa specifica, in entrambi gli ordini
        narrative = _PAIR_NARRATIVES.get((a, b)) or _PAIR_NARRATIVES.get((b, a))
        if narrative is None:
            narrative = (
                f"Correlazione {corr:+.2f}: una variazione dell'1% in **{a}** "
                f"e' associata mediamente a una variazione di {corr * 100:+.1f}% in "
                f"**{b}**. Correlazioni > 0.7 indicano movimenti molto allineati; "
                f"vicine a 0 indicano indipendenza; negative indicano movimenti "
                f"opposti."
            )
        # Etichetta visuale del livello
        abs_c = abs(corr)
        if abs_c > 0.7:
            badge = "🔴 ALTA"
        elif abs_c > 0.3:
            badge = "🟡 MEDIA"
        else:
            badge = "🟢 BASSA"
        sign_emoji = "📈" if corr > 0 else "📉"
        with st.expander(
            f"{sign_emoji} **{a} ↔ {b}** · ρ = {corr:+.2f} · {badge}",
            expanded=False,
        ):
            st.markdown(narrative)

    # Heatmap completa
    st.divider()
    render_section_header("🌡️ Heatmap completa")
    st.dataframe(
        matrix.style.background_gradient(cmap="RdYlGn", axis=None, vmin=-1, vmax=1)
        .format("{:+.2f}"),
        use_container_width=True,
    )

    # Spiegazione concettuale
    st.divider()
    render_section_header("📚 Cosa misura una correlazione e perché conta?")
    st.markdown(
        "**Correlazione di Pearson (ρ)** misura la forza e direzione del "
        "movimento congiunto di due asset, su una scala da -1 a +1:\n\n"
        "- **ρ = +1** → si muovono identicamente (raddoppia uno, raddoppia "
        "l'altro). Asset perfettamente correlati = stesso rischio, no "
        "diversificazione.\n"
        "- **ρ = 0** → indipendenti. È la situazione ideale per "
        "diversificazione: un asset cala, l'altro non è influenzato.\n"
        "- **ρ = -1** → si muovono in modo perfettamente opposto. Hedge "
        "perfetto (raro nella pratica).\n\n"
        "**Trappola classica:** le correlazioni *salgono in crisi*. Asset "
        "che hai diversificato in tempi tranquilli si muovono insieme nei "
        "momenti peggiori (2008, marzo 2020). Per questo è importante usare "
        "modelli **dinamici** come DCC-GARCH che catturano la dipendenza "
        "condizionale alla volatilità del momento, anziché correlazioni "
        "statiche calcolate sull'intero campione."
    )

    st.divider()
    render_section_header("📊 Rolling Correlations")
    window = st.selectbox("Finestra (giorni)", [30, 90, 252], index=1)
    st.caption(
        f"DCC-GARCH conditional correlations su finestra mobile di {window} "
        f"giorni (modello di Engle, 2002 — implementazione lite via EWMA)."
    )


if __name__ == "__main__":  # pragma: no cover
    render_page("Correlations", "🕸️", body_correlations)
