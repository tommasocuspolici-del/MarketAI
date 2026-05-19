"""Article Cleaner — deduplicazione e pulizia articoli news (Fase 7).

Regola 33: zero articoli simulati. Solo dati RSS reali.
Regola 34: hash SHA256 su URL+title per dedup prima della persistenza.
"""
from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from engine.news.schemas import NewsArticle

__version__ = "1.0.0"
__all__ = ["ArticleCleaner"]

_MAX_TITLE_LEN  = 500
_MAX_SUMMARY_LEN = 2000


class ArticleCleaner:
    """Deduplicazione e normalizzazione articoli RSS.

    Pipeline:
      1. Normalizza title e summary (strip, max length)
      2. Calcola SHA256 content_hash su url+title
      3. Marca duplicati rispetto a un set di hash già visti

    Usage::

        cleaner = ArticleCleaner()
        cleaned = cleaner.clean_batch(raw_articles)
        unique  = [a for a in cleaned if not a.is_duplicate]
    """

    def __init__(self) -> None:
        self._seen_hashes: set[str] = set()

    def reset(self) -> None:
        """Azzera la memoria dei duplicati (per ogni ciclo fetch)."""
        self._seen_hashes.clear()

    def compute_hash(self, url: str, title: str) -> str:
        """SHA256 su url+title normalizzati."""
        payload = f"{url.strip().lower()}::{_normalize_text(title)}"
        return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()[:32]

    def clean(self, article: NewsArticle, seen_hashes: set[str] | None = None) -> NewsArticle:
        """Pulisce e deduplicazione un articolo singolo.

        Args:
            article:     Articolo grezzo dal fetcher RSS.
            seen_hashes: Set di hash già visti (aggiornato in-place).

        Returns:
            Articolo con content_hash, is_duplicate, e testo normalizzato.
        """
        hashes = seen_hashes if seen_hashes is not None else self._seen_hashes

        # Normalizza testo
        article.title   = _truncate(_normalize_text(article.title), _MAX_TITLE_LEN)
        if article.summary:
            article.summary = _truncate(_normalize_text(article.summary), _MAX_SUMMARY_LEN)

        # Calcola hash
        content_hash = self.compute_hash(article.url, article.title)
        article.content_hash = content_hash

        # Marca duplicato
        if content_hash in hashes:
            article.is_duplicate  = True
            article.data_quality  = "duplicate"
        else:
            hashes.add(content_hash)
            article.is_duplicate  = False

        # Timestamp fetch se mancante
        if article.fetched_at is None:
            article.fetched_at = datetime.now(UTC)

        return article

    def clean_batch(
        self,
        articles: list[NewsArticle],
        existing_hashes: set[str] | None = None,
    ) -> list[NewsArticle]:
        """Pulisce e deduplicazione un batch di articoli.

        Args:
            articles:        Lista articoli (possono essere da fonti diverse).
            existing_hashes: Hash già presenti in DB (evita re-inserimento).

        Returns:
            Lista articoli con is_duplicate valorizzato correttamente.
        """
        session_hashes: set[str] = set(existing_hashes or [])
        return [self.clean(a, seen_hashes=session_hashes) for a in articles]

    def filter_unique(self, articles: list[NewsArticle]) -> list[NewsArticle]:
        """Ritorna solo gli articoli non duplicati."""
        return [a for a in articles if not a.is_duplicate]


# ── Helpers ────────────────────────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    """Strip whitespace multiplo e caratteri di controllo."""
    if not text:
        return ""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _truncate(text: str, max_len: int) -> str:
    """Tronca il testo a max_len caratteri, aggiunge ellipsis se necessario."""
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."
