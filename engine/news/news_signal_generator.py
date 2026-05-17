"""News Signal Generator — ★ CP-01 segnale news [-1,+1] per Composite Signal v3.

Regola 33: tutti i dati provengono da articoli RSS reali (nessun mock).
Regola 34: segnale cachato in news_signal (TTL: news_rss = 1800s).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from engine.news.schemas import NewsArticle, NewsSignal
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["NewsSignalGenerator"]

log = get_logger(__name__)

# Pesi per categoria (articoli macro/central_bank più impattanti)
_CATEGORY_WEIGHTS: dict[str, float] = {
    "central_bank":  1.5,
    "macro":         1.3,
    "earnings":      1.2,
    "geopolitics":   1.1,
    "equity":        1.0,
    "commodities":   0.9,
    "crypto":        0.7,
    "unknown":       0.5,
}

# Sentiment keyword per scoring rapido (senza ML)
_BULLISH_KW = {
    "surge", "rally", "soar", "gain", "rise", "beat", "exceed", "record high",
    "growth", "boom", "recovery", "strong", "positive", "bullish", "optimist",
    "upgrade", "outperform", "buy", "upside",
}
_BEARISH_KW = {
    "crash", "plunge", "fall", "drop", "decline", "miss", "below", "concern",
    "recession", "inflation", "bearish", "downgrade", "underperform", "sell",
    "warn", "risk", "fear", "crisis", "collapse", "weak",
}


def _score_title(title: str) -> float:
    """Score rapido [-1, +1] basato su keyword del titolo."""
    words = set(title.lower().split())
    bull = len(words & _BULLISH_KW)
    bear = len(words & _BEARISH_KW)
    if bull + bear == 0:
        return 0.0
    return (bull - bear) / (bull + bear)


class NewsSignalGenerator:
    """Genera segnale aggregato [-1, +1] dagli articoli news.

    Il segnale viene integrato in CompositeSignalAggregatorV3.
    LLM latente: quando llm_engine_enabled=true, usa NewsSemanticAnalyzer
    per sentiment più preciso. Quando off, usa keyword scoring.

    Args:
        client: DuckDBClient per persistenza segnale (Regola 34).

    Usage::

        gen = NewsSignalGenerator(client=get_duckdb_client())
        signal = gen.generate(articles)
        print(signal.score)
    """

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client

    def generate(
        self,
        articles: list[NewsArticle],
        lookback_hours: int = 24,
    ) -> NewsSignal:
        """Genera il segnale news dal pool di articoli.

        Args:
            articles:       Articoli recenti (già filtrati per dedup).
            lookback_hours: Finestra temporale da considerare.

        Returns:
            NewsSignal con score [-1, +1] per Composite Signal v3.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=lookback_hours)
        recent = [a for a in articles if a.published_at >= cutoff and not a.is_duplicate]

        if not recent:
            return NewsSignal(
                signal_date=datetime.now(UTC),
                score=0.0,
                article_count=0,
                cluster_count=0,
                bullish_count=0,
                bearish_count=0,
                neutral_count=0,
                data_quality="no_data",
            )

        bullish = bearish = neutral = 0
        weighted_sum = 0.0
        total_weight = 0.0
        ticker_counts: dict[str, int] = {}
        cat_counts: dict[str, int] = {}

        for art in recent:
            # Score da sentiment_score se disponibile (es. FinBERT), altrimenti keyword
            raw_score = art.sentiment_score if art.sentiment_score is not None else _score_title(art.title)
            cat_weight = _CATEGORY_WEIGHTS.get(art.category.value, 1.0)
            impact_w = art.impact_score

            weight = cat_weight * impact_w
            weighted_sum += raw_score * weight
            total_weight += weight

            if raw_score > 0.1:
                bullish += 1
            elif raw_score < -0.1:
                bearish += 1
            else:
                neutral += 1

            for t in art.tickers:
                ticker_counts[t] = ticker_counts.get(t, 0) + 1
            cat_counts[art.category.value] = cat_counts.get(art.category.value, 0) + 1

        score = (weighted_sum / total_weight) if total_weight > 0 else 0.0
        score = max(-1.0, min(1.0, score))

        top_tickers = sorted(ticker_counts, key=lambda t: -ticker_counts[t])[:5]
        top_categories = sorted(cat_counts, key=lambda c: -cat_counts[c])[:3]

        signal = NewsSignal(
            signal_date=datetime.now(UTC),
            score=score,
            article_count=len(recent),
            cluster_count=len({a.cluster_id for a in recent if a.cluster_id}),
            bullish_count=bullish,
            bearish_count=bearish,
            neutral_count=neutral,
            top_tickers=top_tickers,
            top_categories=top_categories,
            data_quality="ok",
        )

        if self._client:
            self._persist(signal)

        log.info(
            "news_signal.generated",
            score=round(score, 4),
            articles=len(recent),
            bull=bullish,
            bear=bearish,
        )
        return signal

    def read_latest(self) -> NewsSignal | None:
        """Legge l'ultimo segnale cachato da DuckDB (Regola 34)."""
        if not self._client:
            return None
        try:
            rows = self._client.query(
                "SELECT signal_date, score, article_count, bullish_count, bearish_count, "
                "neutral_count, data_quality FROM news_signal ORDER BY signal_date DESC LIMIT 1"
            )
            if not rows:
                return None
            r = rows[0]
            return NewsSignal(
                signal_date=r[0],
                score=float(r[1]),
                article_count=int(r[2]),
                cluster_count=0,
                bullish_count=int(r[3]),
                bearish_count=int(r[4]),
                neutral_count=int(r[5]),
                data_quality=str(r[6]),
            )
        except Exception as exc:
            log.debug("news_signal.read_failed", error=str(exc)[:100])
            return None

    def _persist(self, signal: NewsSignal) -> None:
        """Salva segnale in news_signal (Regola 34)."""
        if self._client is None:
            return
        try:
            self._client.execute(
                """
                INSERT INTO news_signal
                    (signal_date, score, article_count, bullish_count, bearish_count,
                     neutral_count, top_tickers_json, data_quality)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (signal_date) DO UPDATE SET
                    score=excluded.score, article_count=excluded.article_count,
                    bullish_count=excluded.bullish_count, bearish_count=excluded.bearish_count
                """,
                [
                    signal.signal_date,
                    signal.score,
                    signal.article_count,
                    signal.bullish_count,
                    signal.bearish_count,
                    signal.neutral_count,
                    str(signal.top_tickers),
                    signal.data_quality,
                ],
            )
        except Exception as exc:
            log.debug("news_signal.persist_failed", error=str(exc)[:100])
