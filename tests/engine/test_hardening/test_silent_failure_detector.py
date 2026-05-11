"""Test del SilentFailureDetector."""
from __future__ import annotations

import pandas as pd
import pytest

from engine.market_data.hardening.silent_failure_detector import (
    SilentFailureDetector,
    SilentFailureError,
)


def test_yfinance_empty_info_raises() -> None:
    """info dict vuoto deve sollevare SilentFailureError."""
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_yfinance_info({}, "AAPL")
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_yfinance_info(None, "AAPL")


def test_yfinance_all_none_prices_raises() -> None:
    """Tutti i campi prezzo None = silent failure."""
    info = {
        "regularMarketPrice": None,
        "currentPrice": None,
        "previousClose": None,
        "longName": "Apple Inc",  # campo non critico
    }
    with pytest.raises(SilentFailureError) as exc_info:
        SilentFailureDetector.check_yfinance_info(info, "AAPL")
    assert "AAPL" in str(exc_info.value)


def test_yfinance_valid_info_passes() -> None:
    """Info dict con prezzi reali = no exception."""
    info = {
        "regularMarketPrice": 187.42,
        "currentPrice": 187.42,
        "previousClose": 185.10,
    }
    SilentFailureDetector.check_yfinance_info(info, "AAPL")


def test_yfinance_empty_history_raises() -> None:
    """history() vuoto = silent failure."""
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_yfinance_history(pd.DataFrame(), "AAPL")
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_yfinance_history(None, "AAPL")


def test_yfinance_valid_history_passes() -> None:
    """history() con dati = no exception."""
    df = pd.DataFrame(
        {
            "Open": [100, 101, 102],
            "Close": [101, 102, 103],
            "Volume": [1000, 1100, 1200],
        }
    )
    SilentFailureDetector.check_yfinance_history(df, "AAPL")


def test_alpha_vantage_information_is_rate_limit() -> None:
    """Risposta con 'Information' = rate limit AV."""
    response = {"Information": "Standard API rate limit reached..."}
    with pytest.raises(SilentFailureError) as exc_info:
        SilentFailureDetector.check_alpha_vantage_response(response, "TIME_SERIES")
    assert exc_info.value.source == "alpha_vantage"


def test_alpha_vantage_note_is_throttling() -> None:
    """Risposta con 'Note' = throttling free tier."""
    response = {"Note": "Thank you for using Alpha Vantage..."}
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_alpha_vantage_response(response, "QUOTE")


def test_alpha_vantage_error_message() -> None:
    """Risposta con 'Error Message' = errore."""
    response = {"Error Message": "Invalid API call"}
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_alpha_vantage_response(response, "QUOTE")


def test_alpha_vantage_valid_response_passes() -> None:
    """Risposta valida = no exception."""
    response = {"Time Series (Daily)": {"2025-01-15": {"4. close": "187.42"}}}
    SilentFailureDetector.check_alpha_vantage_response(response, "TIME_SERIES_DAILY")


def test_finnhub_empty_metrics_raises() -> None:
    """metric dict vuoto = silent failure."""
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_finnhub_metrics({}, "AAPL")
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_finnhub_metrics(None, "AAPL")


def test_finnhub_all_null_metrics_raises() -> None:
    """Tutti campi key None = ticker non disponibile."""
    metrics = {
        "peBasicExclExtraTTM": None,
        "epsBasicExclExtraTTM": 0,
        "marketCapitalization": None,
        "bookValuePerShareAnnual": None,
    }
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_finnhub_metrics(metrics, "ENEL.MI")


def test_finnhub_pe_zero_raises() -> None:
    """P/E = 0 = silent failure (Finnhub bug noto)."""
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_finnhub_pe_zero(0.0, "ENEL.MI")


def test_finnhub_pe_real_passes() -> None:
    """P/E reale (es. -50 o +30) = no exception."""
    SilentFailureDetector.check_finnhub_pe_zero(28.5, "AAPL")
    SilentFailureDetector.check_finnhub_pe_zero(-50.0, "MSFT")  # legittimo


def test_sec_edgar_invalid_cik_raises() -> None:
    """CIK '0000000000' o vuoto = ticker non in EDGAR."""
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_sec_edgar_cik("0000000000", "FOREIGN")
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_sec_edgar_cik("", "FOREIGN")
    with pytest.raises(SilentFailureError):
        SilentFailureDetector.check_sec_edgar_cik(None, "FOREIGN")


def test_sec_edgar_valid_cik_passes() -> None:
    """CIK valido (es. 0000320193 per Apple) = no exception."""
    SilentFailureDetector.check_sec_edgar_cik("0000320193", "AAPL")


def test_sanitize_string_none_handles_na() -> None:
    """Stringhe 'N/A', 'None', '-' etc. -> None."""
    fn = SilentFailureDetector.sanitize_string_none
    assert fn("N/A") is None
    assert fn("None") is None
    assert fn("-") is None
    assert fn("") is None
    assert fn("null") is None
    assert fn("--") is None
    assert fn("nan") is None


def test_sanitize_string_none_keeps_numeric() -> None:
    """Numeri validi vengono convertiti a float."""
    fn = SilentFailureDetector.sanitize_string_none
    assert fn("187.42") == 187.42
    assert fn("1234") == 1234.0
    # Comma as decimal separator (EU format)
    assert fn("187,42") == 187.42


def test_sanitize_string_none_handles_garbage() -> None:
    """Stringhe non parsabili -> None."""
    fn = SilentFailureDetector.sanitize_string_none
    assert fn("abc") is None
    assert fn("12abc") is None


def test_sanitize_string_none_passes_through_numbers() -> None:
    """Input gia' numerici restano numerici."""
    fn = SilentFailureDetector.sanitize_string_none
    assert fn(187.42) == 187.42
    assert fn(0) == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
