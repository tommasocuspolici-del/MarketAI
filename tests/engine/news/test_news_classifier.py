"""Tests — NewsClassifier (Fase 7)."""
import pytest

from engine.news.news_classifier import NewsClassifier
from engine.news.schemas import NewsCategory


@pytest.fixture
def clf() -> NewsClassifier:
    return NewsClassifier()


def test_classify_central_bank(clf: NewsClassifier) -> None:
    text = "Federal Reserve raises interest rates by 25 basis points"
    assert clf.classify(text) == NewsCategory.CENTRAL_BANK


def test_classify_macro(clf: NewsClassifier) -> None:
    text = "GDP growth slows to 1.8% amid rising unemployment rate"
    assert clf.classify(text) == NewsCategory.MACRO


def test_classify_earnings(clf: NewsClassifier) -> None:
    text = "Apple beats earnings estimates, EPS 2.10 vs 1.95 expected"
    assert clf.classify(text) == NewsCategory.EARNINGS


def test_classify_crypto(clf: NewsClassifier) -> None:
    text = "Bitcoin surges 10% as Ethereum breaks resistance level"
    assert clf.classify(text) == NewsCategory.CRYPTO


def test_classify_commodities(clf: NewsClassifier) -> None:
    text = "Crude oil WTI falls 3% on OPEC supply increase"
    assert clf.classify(text) == NewsCategory.COMMODITIES


def test_classify_geopolitics(clf: NewsClassifier) -> None:
    text = "New trade war sanctions imposed between US and China"
    assert clf.classify(text) == NewsCategory.GEOPOLITICS


def test_classify_equity(clf: NewsClassifier) -> None:
    text = "NASDAQ rally continues as tech stocks surge on analyst upgrades"
    assert clf.classify(text) == NewsCategory.EQUITY


def test_classify_unknown(clf: NewsClassifier) -> None:
    result = clf.classify("Lorem ipsum dolor sit amet")
    assert result == NewsCategory.UNKNOWN


def test_classify_empty_string(clf: NewsClassifier) -> None:
    assert clf.classify("") == NewsCategory.UNKNOWN


def test_batch_classify(clf: NewsClassifier) -> None:
    texts = [
        "Fed cuts rates to zero",
        "Bitcoin crashes 20%",
        "Apple reports record earnings",
    ]
    results = clf.batch_classify(texts)
    assert len(results) == 3
    assert results[0] == NewsCategory.CENTRAL_BANK
    assert results[1] == NewsCategory.CRYPTO
    assert results[2] == NewsCategory.EARNINGS
