# ruff: noqa: N999
"""E7 — Sentiment (v7.1).

Risolve "Sentiment Radar non spiegato" della v6: ogni delle 8 fonti
ha la sua spiegazione integrata + interpretazione del pattern composito.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from shared.glossary import get_glossary
from presentation.ui.components.sentiment_radar import render_sentiment_radar
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.0"

__all__ = ["body_sentiment"]


def _classify_pattern(scores: dict[str, float]) -> tuple[str, str]:
    """Classifica il pattern composito (avg, dispersion).

    Returns:
        (titolo, descrizione) della narrativa interpretativa.
    """
    if not scores:
        return ("Nessun dato", "Sentiment non disponibile.")
    avg = sum(scores.values()) / len(scores)
    spread = max(scores.values()) - min(scores.values())

    if avg > 0.6:
        return (
            "🟢 Euforia generalizzata",
            "Le fonti sono allineate su valori alti. Storicamente questo "
            "è un *segnale contrarian di vendita*: quando tutti sono "
            "ottimisti, è spesso il momento di ridurre il rischio.",
        )
    if avg < -0.6:
        return (
            "🔴 Paura diffusa",
            "Tutte le fonti convergono su valori bassi. Storicamente "
            "vicino a minimi di mercato (segnale contrarian di acquisto). "
            "Ricorda: sentirsi a disagio nel comprare è spesso il segnale "
            "che è il momento giusto.",
        )
    if spread > 0.6:
        return (
            "🟡 Mercato in transizione",
            "Le fonti divergono significativamente. Tipico di fasi di "
            "cambio regime. Le fonti più informative a medio termine sono "
            "**COT** (smart money positioning) e **Insider** (dirigenti "
            "che comprano/vendono azioni delle proprie società).",
        )
    return (
        "⚪ Sentiment neutro",
        "Le fonti sono distribuite intorno allo zero. Mercato senza "
        "convinzioni forti né nel rialzo né nel ribasso. "
        "Ascolta più i fondamentali (CPI, GDP, earnings) che il sentiment.",
    )


def body_sentiment(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    glossary = get_glossary()

    render_section_header(
        "📡 Sentiment Radar — All 8 Sources",
        "Ogni asse e' una fonte di sentiment indipendente · -1 (bearish) ÷ +1 (bullish)",
    )

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="e7_refresh"):
            st.cache_data.clear()
            st.rerun()

    st.warning(
        "⚠️ **DATI DEMO** — i valori mostrati sono placeholder statici. "
        "Collega le API (Finnhub, AAII, CNN Fear & Greed) per scores live."
    )

    scores = {
        "CNN F&G": 0.45,
        "AAII": 0.25,
        "Crypto F&G": -0.15,
        "Put/Call": 0.10,
        "COT": 0.30,
        "Insider": -0.05,
        "Short Int": 0.15,
        "Finnhub": 0.40,
    }

    try:
        render_sentiment_radar(tokens, scores)
    except (ImportError, AttributeError, TypeError):
        st.info("Sentiment radar non disponibile.")

    # Interpretazione narrativa del pattern complessivo
    pattern_title, pattern_desc = _classify_pattern(scores)
    st.divider()
    render_section_header("🧭 Cosa significa questo pattern?")
    st.markdown(f"### {pattern_title}")
    st.info(pattern_desc)

    # Decomposizione: per ogni sorgente, valore + spiegazione completa
    st.divider()
    render_section_header(
        "🔍 Le 8 fonti in dettaglio",
        "Ogni fonte misura un aspetto diverso del sentiment — clicca per la spiegazione",
    )
    for source, score in scores.items():
        entry = glossary.get_or_stub(source)
        # Etichetta del valore
        if score > 0.3:
            badge = "🟢 BULLISH"
        elif score < -0.3:
            badge = "🔴 BEARISH"
        else:
            badge = "⚪ NEUTRO"
        with st.expander(
            f"**{entry.term}** · {entry.full_name} → score {score:+.2f} · {badge}",
            expanded=False,
        ):
            st.markdown(f"**Cosa rappresenta:** {entry.description}")
            if entry.interpretation:
                st.markdown(f"**Come si legge:** {entry.interpretation}")
            if entry.typical_range:
                st.markdown(f"**Range tipico:** {entry.typical_range}")

    st.divider()
    render_section_header("⚡ Contrarian Signals")
    extreme_high = [s for s, v in scores.items() if v >= 0.75]
    extreme_low = [s for s, v in scores.items() if v <= -0.75]
    if extreme_high:
        st.warning(
            f"⚠️ Extreme greed su: {', '.join(extreme_high)} — "
            f"considerare riduzione del rischio."
        )
    if extreme_low:
        st.success(
            f"💡 Extreme fear su: {', '.join(extreme_low)} — "
            f"potenziale buy signal contrarian."
        )
    if not (extreme_high or extreme_low):
        st.info("Sentiment within normal range. No contrarian signal active.")


if __name__ == "__main__":  # pragma: no cover
    render_page("Sentiment", "🎭", body_sentiment)
