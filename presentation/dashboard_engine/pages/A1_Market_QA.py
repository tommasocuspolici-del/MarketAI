# ruff: noqa: N999
"""A1 — Market Q&A (Blocco F — Stub).

Stub completo con EmptyState + preview demo.
Backend LLM (Ollama/mistral:7b-q4) sarà attivo con Fase 7.
Feature flag: 'llm_qa_enabled'.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from presentation.ui.components import EmptyState
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "1.0.0"
__all__ = ["body_market_qa"]

_DEMO_QA = [
    {
        "q": "Qual è il regime di mercato attuale?",
        "a": "Sulla base di VIX=18.4, spread 2y-10y=-42bp e macro_conviction=+0.31, "
             "il regime attuale è **transition** con leggera inclinazione bull.",
    },
    {
        "q": "Il portafoglio è sovra-esposto alla duration?",
        "a": "Con TLT al 15% del portafoglio e DGS10 in salita, "
             "la duration implicita è ~7.2 anni. Il modello suggerisce una riduzione al 10%.",
    },
    {
        "q": "Quali settori beneficiano dall'attuale curva dei tassi?",
        "a": "Con curva ancora invertita (spread negativo), i settori difensivi "
             "(Utilities, Healthcare, Consumer Staples) mostrano rendimenti attesi superiori.",
    },
]


def _is_llm_available() -> bool:
    """Verifica disponibilità Ollama (localhost:11434)."""
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        return True
    except Exception:
        return False


def body_market_qa(tokens: DesignTokens) -> None:  # pragma: no cover
    import streamlit as st

    from shared.feature_flags import is_enabled

    render_section_header("🤖 Market Q&A", "Risposte contestualizzate ai dati di mercato via LLM locale")

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="a1_refresh"):
            st.cache_data.clear()
            st.rerun()

    if not is_enabled("llm_qa_enabled"):
        EmptyState(
            title="LLM Q&A non ancora attivo",
            hint=(
                "Sarà disponibile con la Fase 7 (LLM Gateway). "
                "Attiva il feature flag 'llm_qa_enabled' e avvia Ollama con mistral:7b-q4."
            ),
            severity="info",
        ).render()

        if st.toggle("👀 Mostra preview con dati demo", key="a1_demo_toggle"):
            _render_demo_preview(st, tokens)
        return

    _render_live_qa(st, tokens)


def _render_demo_preview(st, tokens: DesignTokens) -> None:  # pragma: no cover
    st.info("⚠️ **Dati dimostrativi** — il motore LLM non è ancora connesso.")
    render_section_header("💬 Esempio domande e risposte")
    for item in _DEMO_QA:
        with st.expander(f"❓ {item['q']}"):
            st.markdown(item["a"])
            st.caption("🤖 Risposta generata da mistral:7b-q4 (demo)")


def _render_live_qa(st, tokens: DesignTokens) -> None:  # pragma: no cover
    question = st.text_input(
        "Fai una domanda sul mercato...",
        placeholder="Es: Qual è il regime attuale? Il portafoglio è esposto al rischio duration?",
        key="a1_question",
    )
    if st.button("▶ Invia", type="primary", key="a1_send") and question.strip():
        with st.spinner("LLM in elaborazione..."):
            try:
                from engine.llm.market_qa_engine import MarketQAEngine
                engine = MarketQAEngine()
                answer = engine.answer(question)
                st.markdown(f"**Risposta:** {answer}")
            except Exception as exc:
                st.error(f"❌ Errore LLM: {exc}")

    render_section_header("💬 Domande frequenti")
    for item in _DEMO_QA:
        if st.button(f"❓ {item['q']}", key=f"a1_faq_{hash(item['q'])}"):
            st.session_state["a1_question"] = item["q"]
            st.rerun()


if __name__ == "__main__":  # pragma: no cover
    render_page("Market Q&A", "🤖", body_market_qa)
