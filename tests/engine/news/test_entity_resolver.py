"""Tests — EntityResolver (Fase 7)."""
import pytest

from engine.news.entity_resolver import EntityResolver


@pytest.fixture
def resolver() -> EntityResolver:
    return EntityResolver()


def test_resolve_known_entity(resolver: EntityResolver) -> None:
    assert resolver.resolve("apple") == "AAPL"
    assert resolver.resolve("microsoft") == "MSFT"
    assert resolver.resolve("bitcoin") == "BTC-USD"


def test_resolve_unknown(resolver: EntityResolver) -> None:
    assert resolver.resolve("unknown_company_xyz_123") is None


def test_extract_tickers_from_text(resolver: EntityResolver) -> None:
    text = "Apple beat earnings estimates, NVIDIA surges on AI demand"
    tickers = resolver.extract_tickers(text)
    assert "AAPL" in tickers
    assert "NVDA" in tickers


def test_extract_tickers_dollar_sign(resolver: EntityResolver) -> None:
    text = "Watch $AAPL and $MSFT closely this week"
    tickers = resolver.extract_tickers(text)
    assert "AAPL" in tickers
    assert "MSFT" in tickers


def test_extract_crypto(resolver: EntityResolver) -> None:
    tickers = resolver.extract_tickers("Bitcoin breaks $50k, Ethereum follows")
    assert "BTC-USD" in tickers
    assert "ETH-USD" in tickers


def test_extract_empty(resolver: EntityResolver) -> None:
    assert resolver.extract_tickers("") == []


def test_add_mapping(resolver: EntityResolver) -> None:
    resolver.add_mapping("Acme Corp", "ACME")
    assert resolver.resolve("acme corp") == "ACME"
    assert "ACME" in resolver.extract_tickers("Acme Corp reports earnings")
