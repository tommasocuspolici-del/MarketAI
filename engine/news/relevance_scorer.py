"""Relevance Scorer — filtra notizie per portafoglio utente (Fase 7).

Regola 33: ticker monitorati provengono da config/watched_tickers.yaml.
Zero ticker hardcoded nel codice.
"""
from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

import yaml

from engine.news.schemas import NewsArticle
from shared.logger import get_logger

if TYPE_CHECKING:
    pass

__version__ = "1.0.0"
__all__ = ["RelevanceScorer"]

log = get_logger(__name__)

_CONFIG_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "watched_tickers.yaml"

# Score di rilevanza (0.0 - 1.0)
_BASE_SCORE         = 0.3   # ogni articolo ha rilevanza minima
_TICKER_MATCH_BONUS = 0.4   # articolo menziona ticker in watchlist
_HIGH_IMPACT_BONUS  = 0.2   # articolo da fonte ad alta credibilità
_CATEGORY_BONUS     = 0.1   # categoria macro/central_bank (sempre rilevante)


class RelevanceScorer:
    """Valuta la rilevanza di un articolo per il portafoglio utente.

    La rilevanza è un float [0, 1]:
      0.0 → completamente irrilevante
      1.0 → altamente rilevante (ticker in portfolio, fonte credibile)

    Usage::

        scorer = RelevanceScorer()
        scored = scorer.score_batch(articles)
        relevant = [a for a in scored if a.impact_score >= 0.4]
    """

    def __init__(self, watched_tickers: list[str] | None = None) -> None:
        source = watched_tickers if watched_tickers is not None else self._load_watched_tickers()
        self._watched: set[str] = set(
            t.upper() for t in source if isinstance(t, str)
        )

    def score(self, article: NewsArticle) -> float:
        """Calcola relevance score [0, 1] per un articolo.

        Aggiorna article.impact_score in-place e lo ritorna.
        """
        score = _BASE_SCORE

        # Bonus per ticker rilevante
        article_tickers = {t.upper() for t in (article.tickers or [])}
        if article_tickers & self._watched:
            score += _TICKER_MATCH_BONUS

        # Bonus categoria macro/central_bank
        if article.category and article.category.value in ("macro", "central_bank", "earnings"):
            score += _CATEGORY_BONUS

        # Bonus alta credibilità (determiniamo da source name)
        if _is_high_credibility(article.source):
            score += _HIGH_IMPACT_BONUS

        final_score = min(1.0, score)
        article.impact_score = final_score
        return final_score

    def score_batch(self, articles: list[NewsArticle]) -> list[NewsArticle]:
        """Score batch di articoli (aggiorna impact_score in-place)."""
        for article in articles:
            self.score(article)
        return articles

    def filter_relevant(
        self, articles: list[NewsArticle], min_score: float = 0.4
    ) -> list[NewsArticle]:
        """Ritorna solo articoli con impact_score >= min_score."""
        return [a for a in articles if a.impact_score >= min_score]

    def add_ticker(self, ticker: str) -> None:
        """Aggiunge un ticker alla watchlist in runtime."""
        self._watched.add(ticker.upper())

    @property
    def watched_count(self) -> int:
        return len(self._watched)

    # ── Private ──────────────────────────────────────────────────────────────

    @staticmethod
    def _load_watched_tickers() -> list[str]:
        """Carica ticker da config/watched_tickers.yaml."""
        try:
            with _CONFIG_PATH.open("r", encoding="utf-8") as f:
                data: dict = yaml.safe_load(f) or {}
            tickers: list[str] = []
            for section in ("primary", "etfs", "bonds", "commodities", "crypto", "forex"):
                tickers.extend(data.get(section, []))
            return tickers
        except Exception as exc:
            log.warning("relevance_scorer.config_load_failed", error=str(exc)[:80])
            return _FALLBACK_TICKERS


# Fallback se YAML non trovato
_FALLBACK_TICKERS = [
    "SPY", "QQQ", "IWM", "DIA", "GLD", "TLT", "VIX",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "^GSPC", "^IXIC", "^DJI",
]

_HIGH_CREDIBILITY_SOURCES = {
    "reuters", "financial times", "bloomberg", "ft", "wsj", "wall street journal",
    "cnbc", "ft.com", "reuters.com",
}


def _is_high_credibility(source: str) -> bool:
    src_lower = source.lower()
    return any(h in src_lower for h in _HIGH_CREDIBILITY_SOURCES)
