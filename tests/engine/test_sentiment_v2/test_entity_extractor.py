"""Tests for EntityExtractor — DoD: precision ≥ 90% on 10 article fixture."""
from __future__ import annotations

import pytest

from engine.analytics.sentiment.entity_extractor import EntityExtractor

# ── 10-article fixture with expected entities (DoD criterion) ─────────────
_FIXTURE: list[tuple[str, list[str]]] = [
    ("$AAPL reports record quarterly earnings", ["AAPL"]),
    ("Apple shares hit all-time high after earnings beat", ["AAPL"]),
    ("Microsoft acquires gaming studio for $7 billion", ["MSFT"]),
    ("Tesla deliveries miss estimates in fourth quarter", ["TSLA"]),
    ("S&P 500 falls amid Federal Reserve rate hike fears", ["SPY"]),
    ("Nvidia chip shortage drives semiconductor sector rally", ["NVDA"]),
    ("$JPM quarterly profit rises on higher interest rates", ["JPM"]),
    ("Amazon AWS revenue growth accelerates in cloud boom", ["AMZN"]),
    ("VIX spikes to highest level as volatility returns", ["VIX"]),
    ("Goldman Sachs investment banking revenue declines", ["GS"]),
]


class TestEntityExtractorPrecision:
    """DoD: precision ≥ 90% on 10-article fixture."""

    def test_precision_on_fixture(self) -> None:
        extractor = EntityExtractor()
        correct = 0
        total   = 0

        for text, expected_tickers in _FIXTURE:
            extracted = set(extractor.extract_tickers(text))
            for expected in expected_tickers:
                total += 1
                if expected in extracted:
                    correct += 1

        precision = correct / total if total > 0 else 0.0
        assert precision >= 0.90, f"Precision {precision:.0%} < 90% DoD threshold"


class TestExplicitTickerPattern:
    def test_dollar_ticker_extracted(self) -> None:
        extractor = EntityExtractor()
        tickers = extractor.extract_tickers("$AAPL hits new high today")
        assert "AAPL" in tickers

    def test_multiple_dollar_tickers(self) -> None:
        extractor = EntityExtractor()
        tickers = extractor.extract_tickers("$MSFT and $GOOGL both rise on strong results")
        assert "MSFT" in tickers
        assert "GOOGL" in tickers

    def test_lowercase_company_name(self) -> None:
        extractor = EntityExtractor()
        tickers = extractor.extract_tickers("Tesla deliveries exceed expectations this quarter")
        assert "TSLA" in tickers


class TestSectorExtraction:
    def test_tech_sector_detected(self) -> None:
        extractor = EntityExtractor()
        entities = extractor.extract("Semiconductor chip shortage hits tech sector hard")
        types = {e.entity_type for e in entities}
        assert "sector" in types

    def test_energy_sector_detected(self) -> None:
        extractor = EntityExtractor()
        entities = extractor.extract("Oil prices surge on OPEC production cuts")
        sectors = [e.entity for e in entities if e.entity_type == "sector"]
        assert "energy" in sectors


class TestIndexExtraction:
    def test_vix_detected(self) -> None:
        extractor = EntityExtractor()
        entities = extractor.extract("VIX spikes to 35 as market volatility surges")
        indices = [e.entity for e in entities if e.entity_type == "index"]
        assert "VIX" in indices

    def test_sp500_detected(self) -> None:
        extractor = EntityExtractor()
        entities = extractor.extract("S&P 500 hits record high in strong session")
        indices = [e.entity for e in entities if e.entity_type == "index"]
        assert "SPY" in indices


class TestEdgeCases:
    def test_empty_string_returns_empty(self) -> None:
        extractor = EntityExtractor()
        assert extractor.extract("") == []

    def test_no_entities_in_generic_text(self) -> None:
        extractor = EntityExtractor()
        # Generic text with no financial entities
        entities = extractor.extract("The weather is nice today in the park")
        assert len(entities) == 0

    def test_deduplication_same_entity_twice(self) -> None:
        extractor = EntityExtractor()
        tickers = extractor.extract_tickers("$AAPL Apple both mentioned in same article")
        assert tickers.count("AAPL") == 1    # deduplicated
