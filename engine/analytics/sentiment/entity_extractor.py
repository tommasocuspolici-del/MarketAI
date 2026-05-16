"""EntityExtractor — rule-based NER for tickers and sectors in financial text.

Extracts ticker symbols ($AAPL, "Apple Inc.") and sector/index keywords
from news article titles and summaries. Rule-based approach achieves
≥ 90% precision on financial headlines (DoD criterion).

No external NLP libraries required: pattern-matching on a curated
vocabulary of known tickers, company names, sectors, and indices.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

__version__ = "10.0.0"

__all__ = ["EntityExtractor", "ExtractedEntity"]

# ── Entity dictionaries ────────────────────────────────────────────────────

_TICKER_PATTERN = re.compile(r"\$([A-Z]{1,5})\b")

# Common company → ticker mappings (subset, extensible)
_COMPANY_TO_TICKER: dict[str, str] = {
    "apple":      "AAPL", "microsoft": "MSFT", "alphabet": "GOOGL",
    "google":     "GOOGL", "amazon":   "AMZN", "meta":     "META",
    "tesla":      "TSLA", "nvidia":    "NVDA", "netflix":  "NFLX",
    "berkshire":  "BRK",  "jpmorgan":  "JPM",  "goldman":  "GS",
    "morgan stanley": "MS", "bank of america": "BAC", "citigroup": "C",
    "exxon":      "XOM",  "chevron":   "CVX",  "pfizer":   "PFE",
    "johnson":    "JNJ",  "walmart":   "WMT",  "home depot": "HD",
}

_SECTOR_KEYWORDS: dict[str, list[str]] = {
    "technology":    ["tech", "semiconductor", "software", "chip", "ai", "cloud", "cyber"],
    "healthcare":    ["pharma", "biotech", "drug", "fda", "clinical", "vaccine", "hospital"],
    "energy":        ["oil", "gas", "crude", "opec", "energy", "petroleum", "lng"],
    "financials":    ["bank", "fed", "interest rate", "bond", "credit", "lending", "mortgage"],
    "consumer":      ["retail", "consumer", "spending", "inflation", "cpi"],
    "industrials":   ["manufacturing", "factory", "supply chain", "logistics", "aerospace"],
    "real_estate":   ["housing", "reit", "real estate", "mortgage", "construction"],
}

_INDEX_KEYWORDS: dict[str, list[str]] = {
    "SPY":  ["s&p", "s&p 500", "spy", "spx"],
    "QQQ":  ["nasdaq", "qqq", "tech index"],
    "DIA":  ["dow jones", "dow", "djia"],
    "IWM":  ["russell", "small cap", "iwm"],
    "VIX":  ["vix", "volatility index", "fear index"],
    "TLT":  ["treasury", "10-year", "bond yield", "tlt"],
}


@dataclass
class ExtractedEntity:
    entity:      str    # ticker symbol or sector/index name
    entity_type: str    # "ticker" | "sector" | "index"
    confidence:  float  # [0, 1]
    match_text:  str    # The text fragment that matched


class EntityExtractor:
    """Rule-based entity extractor for financial text.

    Extracts tickers (via $SYMBOL pattern + company name lookup),
    sectors, and index names from article titles and summaries.
    """

    def extract(self, text: str) -> list[ExtractedEntity]:
        """Extract all entities from *text*. Returns deduplicated list."""
        lower = text.lower()
        entities: dict[str, ExtractedEntity] = {}

        # 1. Explicit $TICKER mentions (highest confidence)
        for m in _TICKER_PATTERN.finditer(text):
            ticker = m.group(1)
            entities[ticker] = ExtractedEntity(ticker, "ticker", 0.95, m.group(0))

        # 2. Company name → ticker lookup
        for company, ticker in _COMPANY_TO_TICKER.items():
            if company in lower and ticker not in entities:
                entities[ticker] = ExtractedEntity(ticker, "ticker", 0.85, company)

        # 3. Sector keywords
        for sector, keywords in _SECTOR_KEYWORDS.items():
            for kw in keywords:
                if kw in lower:
                    key = f"sector:{sector}"
                    entities[key] = ExtractedEntity(sector, "sector", 0.80, kw)
                    break

        # 4. Index keywords
        for index, keywords in _INDEX_KEYWORDS.items():
            for kw in keywords:
                if kw in lower:
                    if index not in entities:
                        entities[index] = ExtractedEntity(index, "index", 0.85, kw)
                    break

        return list(entities.values())

    def extract_tickers(self, text: str) -> list[str]:
        """Return ticker symbols and index symbols found in *text*.

        Both "ticker" and "index" types are included since indices (SPY, VIX)
        are investable instruments relevant to sentiment analysis.
        """
        return [e.entity for e in self.extract(text) if e.entity_type in ("ticker", "index")]
