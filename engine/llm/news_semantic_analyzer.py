"""News Semantic Analyzer — analisi semantica profonda di articoli news.

Integrazione LLM latente (Fase 9):
  LLM attivo  → analisi semantica via LLMGateway
  LLM inattivo → keyword summary deterministico (sempre disponibile)
"""
from __future__ import annotations

from typing import Any

from shared.logger import get_logger

__version__ = "1.0.0"
__all__ = ["NewsSemanticAnalyzer"]

log = get_logger(__name__)


class NewsSemanticAnalyzer:
    """Analizza semanticamente articoli news per estrarre insight.

    Usato da N2_News_Analysis per arricchire i cluster tematici.
    Integrazione LLM latente: template finché llm_news_semantic=false.
    """

    def __init__(self) -> None:
        from shared.llm.llm_gateway import get_llm_gateway
        self._llm = get_llm_gateway()

    def analyze(self, title: str, summary: str, category: str) -> dict[str, Any]:
        """Analizza un articolo e restituisce insight strutturati.

        Args:
            title:    Titolo articolo.
            summary:  Sommario (max 500 chars).
            category: Categoria classificata.

        Returns:
            Dict con sentiment, key_entities, impact_estimate, tags.
        """
        context = {"title": title, "summary": summary[:500], "category": category}

        try:
            from shared.feature_flags import is_enabled
            if is_enabled("llm_engine_enabled") and is_enabled("llm_news_semantic") \
                    and self._llm.is_available():
                result = self._llm.generate(
                    template="news_analysis",
                    context=context,
                    max_tokens=256,
                )
                import json
                parsed: dict[str, Any] = json.loads(result.text)
                parsed["source"] = "llm"
                return parsed
        except Exception as exc:
            log.debug("news_semantic.llm_fallback", error=str(exc)[:80])

        return self._keyword_analysis(title, summary, category)

    def _keyword_analysis(self, title: str, summary: str, category: str) -> dict[str, Any]:
        """Analisi keyword deterministica senza ML/LLM."""
        text = (title + " " + summary).lower()

        bullish = {"surge", "rally", "beat", "exceed", "growth", "rise", "record", "strong"}
        bearish = {"fall", "drop", "miss", "decline", "recession", "weak", "cut", "risk"}

        bull_hits = sum(1 for w in bullish if w in text)
        bear_hits = sum(1 for w in bearish if w in text)

        if bull_hits > bear_hits:
            sentiment = "positive"
            score = min(1.0, bull_hits * 0.2)
        elif bear_hits > bull_hits:
            sentiment = "negative"
            score = max(-1.0, -bear_hits * 0.2)
        else:
            sentiment = "neutral"
            score = 0.0

        return {
            "sentiment": sentiment,
            "sentiment_score": round(score, 2),
            "impact_estimate": "medium",
            "tags": [category],
            "source": "keyword",
        }

    def batch_analyze(self, articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Analizza una lista di articoli.

        Args:
            articles: Lista dict con keys title, summary, category.

        Returns:
            Lista di dict con analisi per ogni articolo.
        """
        return [
            self.analyze(
                title=a.get("title", ""),
                summary=a.get("summary", ""),
                category=a.get("category", "unknown"),
            )
            for a in articles
        ]
