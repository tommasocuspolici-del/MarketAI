"""Market Q&A Engine — risponde a domande sul mercato in linguaggio naturale.

Integrazione LLM latente (Fase 9):
  LLM attivo  → risposta contestualizzata via LLMGateway
  LLM inattivo → "Dato non disponibile" con suggerimento pagina
"""
from __future__ import annotations

from typing import Any

from shared.logger import get_logger

__version__ = "1.0.0"
__all__ = ["MarketQAEngine"]

log = get_logger(__name__)

_TOPIC_MAP: dict[str, str] = {
    "vix":        "Q1_VIX_Based_Analysis",
    "volatility": "Q1_VIX_Based_Analysis",
    "sentiment":  "Q2_Sentiment",
    "news":       "N1_News_Feed",
    "macro":      "M1_Macro_Dashboard",
    "yield":      "M2_Yield_Curve",
    "inflation":  "M1_Macro_Dashboard",
    "gdp":        "M1_Macro_Dashboard",
    "valuation":  "M6_Valuation_PE",
    "pe":         "M6_Valuation_PE",
    "cape":       "M6_Valuation_PE",
    "ib":         "M7_IB_Consensus",
    "forecast":   "M7_IB_Consensus",
}


class MarketQAEngine:
    """Risponde a domande testuali sui mercati.

    Pattern latente: LLM off → risposta template + link pagina rilevante.
    LLM on → risposta con contesto dati reali in italiano.
    """

    def __init__(self) -> None:
        from shared.llm.llm_gateway import get_llm_gateway
        self._llm = get_llm_gateway()

    def answer(self, question: str, market_context: dict[str, Any] | None = None) -> str:
        """Risponde a una domanda sul mercato.

        Args:
            question:       Domanda in linguaggio naturale.
            market_context: Contesto opzionale (VIX, regime, ecc.).

        Returns:
            Risposta testuale.
        """
        ctx = {"question": question, **(market_context or {})}

        try:
            from shared.feature_flags import is_enabled
            if is_enabled("llm_engine_enabled") and is_enabled("llm_market_qa") \
                    and self._llm.is_available():
                result = self._llm.generate(
                    template="market_narrative",
                    context=ctx,
                    max_tokens=256,
                )
                log.debug("market_qa.llm_answered", latency_ms=result.latency_ms)
                return result.text
        except Exception as exc:
            log.debug("market_qa.llm_fallback", error=str(exc)[:80])

        return self._template_answer(question)

    def _template_answer(self, question: str) -> str:
        """Risposta template: individua topic e suggerisce pagina."""
        q_lower = question.lower()
        for keyword, page in _TOPIC_MAP.items():
            if keyword in q_lower:
                return (
                    f"Per informazioni su **{keyword}** consulta la pagina **{page}**. "
                    f"Abilita LLM in S2_Impostazioni per risposte contestualizzate."
                )
        return (
            "Il sistema Q&A richiede LLM attivo per rispondere a domande in linguaggio naturale. "
            "Abilita LLM in S2_Impostazioni · Navigazione: usa le sezioni M, K, Q, N per i dati."
        )
