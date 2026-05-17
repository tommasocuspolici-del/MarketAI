"""Tests — ForecastExtractor Stage 1: regex (Fase 8)."""
import pytest

from unittest.mock import MagicMock

from engine.ib_forecast.forecast_extractor import ForecastExtractor


@pytest.fixture
def extractor() -> ForecastExtractor:
    client = MagicMock()
    client.query.return_value = []
    client.execute.return_value = None
    return ForecastExtractor(client=client)


def test_extract_gdp(extractor: ForecastExtractor) -> None:
    text = "GDP growth expected to reach 2.5% in 2025"
    forecasts = extractor.extract(text, source="fed_speeches")
    gdp = [f for f in forecasts if f.indicator == "GDP"]
    assert len(gdp) >= 1
    assert gdp[0].value == pytest.approx(2.5)
    assert gdp[0].source == "fed_speeches"


def test_extract_cpi(extractor: ForecastExtractor) -> None:
    text = "Inflation rate of 3.2% expected for 2024"
    forecasts = extractor.extract(text, source="imf_blog")
    cpi = [f for f in forecasts if f.indicator == "CPI"]
    assert len(cpi) >= 1
    assert cpi[0].value == pytest.approx(3.2)


def test_extract_fedfunds(extractor: ForecastExtractor) -> None:
    text = "Federal funds rate to reach 4.5% by end of 2025"
    forecasts = extractor.extract(text, source="fed_press")
    rates = [f for f in forecasts if f.indicator == "FEDFUNDS"]
    assert len(rates) >= 1
    assert rates[0].value == pytest.approx(4.5)


def test_empty_text_returns_empty(extractor: ForecastExtractor) -> None:
    assert extractor.extract("", source="test") == []


def test_no_match_returns_empty(extractor: ForecastExtractor) -> None:
    text = "General market commentary without specific numbers"
    forecasts = extractor.extract(text, source="test")
    assert isinstance(forecasts, list)


def test_source_always_populated(extractor: ForecastExtractor) -> None:
    text = "GDP growth forecast 2.0% for 2025"
    forecasts = extractor.extract(text, source="imf_blog")
    for f in forecasts:
        assert f.source == "imf_blog"  # mai NULL — Regola 33


def test_extraction_method_is_regex(extractor: ForecastExtractor) -> None:
    text = "Economic growth of 1.8% is expected"
    forecasts = extractor.extract(text, source="bis_speeches")
    for f in forecasts:
        assert f.extraction_method == "regex"


def test_negative_gdp(extractor: ForecastExtractor) -> None:
    text = "Real GDP to contract by -1.5% in 2024"
    forecasts = extractor.extract(text, source="imf_weo")
    gdp = [f for f in forecasts if f.indicator == "GDP"]
    if gdp:
        assert gdp[0].value == pytest.approx(-1.5)
