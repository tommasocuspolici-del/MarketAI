"""engine.news — News Engine Avanzato (Fase 7).

Moduli:
  schemas.py              — NewsArticle, NewsCluster, NewsSignal
  rss_fetcher.py          — Feed RSS 6 fonti (Regola 33 + 34)
  article_cleaner.py      — Dedup SHA256 + TTL check prima del fetch
  news_classifier.py      — 7 categorie senza LLM (keyword dict)
  entity_resolver.py      — mapping mention → ticker (top 50 watched)
  news_event_clusterer.py — TF-IDF (500 features) + DBSCAN (eps=0.25)
  relevance_scorer.py     — Filtra per portafoglio utente
  news_signal_generator.py — ★ CP-01 — segnale [-1,1] per Composite
  news_aggregator.py      — Orchestratore
"""
from __future__ import annotations

__version__ = "1.0.0"
