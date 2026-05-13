"""Tests for AlphaVantageFundamentalsFetcher.

Roadmap v3.0 — Settimana 1 — coverage target ≥ 80%.

Tutti i test mockano aiohttp e feature flags — nessuna chiamata di rete reale.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ─── Fixtures & helpers ───────────────────────────────────────────────────────

_OVERVIEW_PAYLOAD: dict = {
    "Symbol": "AAPL",
    "PERatio": "28.5",
    "ForwardPE": "25.0",
    "PriceToBookRatio": "42.0",
    "PriceToSalesRatioTTM": "7.5",
    "EVToEBITDA": "22.0",
    "DividendYield": "0.005",
    "PayoutRatio": "0.15",
    "Beta": "1.24",
    "MarketCapitalization": "2500000000000",
}

_INCOME_PAYLOAD: dict = {
    "quarterlyReports": [
        {
            "fiscalDateEnding": "2024-12-31",
            "totalRevenue": "124300000000",
            "grossProfit": "55000000000",
            "operatingIncome": "38000000000",
            "netIncome": "30000000000",
            "reportedEPS": "1.89",
        },
        {
            "fiscalDateEnding": "2024-09-28",
            "totalRevenue": "94900000000",
            "grossProfit": "42000000000",
            "operatingIncome": "30000000000",
            "netIncome": "22000000000",
            "reportedEPS": "1.33",
        },
    ]
}

_BALANCE_PAYLOAD: dict = {
    "quarterlyReports": [
        {
            "fiscalDateEnding": "2024-12-31",
            "totalAssets": "364840000000",
            "longTermDebt": "97000000000",
            "currentDebt": "22000000000",
            "totalShareholderEquity": "56950000000",
        }
    ]
}


def _make_fetcher(monkeypatch):
    """Costruisce un AlphaVantageFundamentalsFetcher con flag e env mockati."""
    # Abilita il feature flag
    monkeypatch.setenv("ALPHA_VANTAGE_KEY", "test_key_123")
    with patch("engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher.is_enabled",
               return_value=True):
        from engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher import (
            AlphaVantageFundamentalsFetcher,
        )
        rate_limiter = MagicMock()
        rate_limiter.acquire = AsyncMock(return_value=None)
        return AlphaVantageFundamentalsFetcher(
            rate_limiter=rate_limiter,
            api_key="test_key_123",
        )


# ─── Test: feature flag ───────────────────────────────────────────────────────

def test_raises_if_flag_disabled() -> None:
    """Costruttore lancia FeatureDisabledError se alpha_vantage_premium è off."""
    with patch(
        "engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher.is_enabled",
        return_value=False,
    ):
        from engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher import (
            AlphaVantageFundamentalsFetcher,
        )
        from shared.exceptions import FeatureDisabledError

        with pytest.raises(FeatureDisabledError):
            AlphaVantageFundamentalsFetcher(api_key="dummy")


def test_raises_if_no_api_key(monkeypatch) -> None:
    """Costruttore lancia ConfigurationError se ALPHA_VANTAGE_KEY mancante."""
    monkeypatch.delenv("ALPHA_VANTAGE_KEY", raising=False)
    with patch(
        "engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher.is_enabled",
        return_value=True,
    ):
        from engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher import (
            AlphaVantageFundamentalsFetcher,
        )
        from shared.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError):
            AlphaVantageFundamentalsFetcher()  # no api_key


# ─── Test: fetch_valuation ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_valuation_returns_dataframe(monkeypatch) -> None:
    """fetch_valuation con payload valido → DataFrame single row."""
    fetcher = _make_fetcher(monkeypatch)

    with patch.object(fetcher, "_get_json", return_value=_OVERVIEW_PAYLOAD):
        with patch(
            "engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher.is_enabled",
            return_value=True,
        ):
            df = await fetcher.fetch_valuation("AAPL")

    assert not df.empty
    assert len(df) == 1
    assert df.iloc[0]["ticker"] == "AAPL"
    assert df.iloc[0]["pe_ttm"] == pytest.approx(28.5)
    assert df.iloc[0]["beta"] == pytest.approx(1.24)


@pytest.mark.asyncio
async def test_fetch_valuation_numeric_columns_float64(monkeypatch) -> None:
    """Colonne numeriche devono essere float64 (Regola 8)."""
    fetcher = _make_fetcher(monkeypatch)

    with patch.object(fetcher, "_get_json", return_value=_OVERVIEW_PAYLOAD):
        with patch(
            "engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher.is_enabled",
            return_value=True,
        ):
            df = await fetcher.fetch_valuation("AAPL")

    for col in ("pe_ttm", "pe_forward", "pb", "ev_ebitda", "beta", "market_cap"):
        assert df[col].dtype == np.float64, f"{col} non è float64"


@pytest.mark.asyncio
async def test_fetch_valuation_none_values_become_nan(monkeypatch) -> None:
    """Campi AV con valore 'None' → NaN nel DataFrame."""
    payload = {**_OVERVIEW_PAYLOAD, "PERatio": "None", "ForwardPE": "-"}
    fetcher = _make_fetcher(monkeypatch)

    with patch.object(fetcher, "_get_json", return_value=payload):
        with patch(
            "engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher.is_enabled",
            return_value=True,
        ):
            df = await fetcher.fetch_valuation("AAPL")

    assert np.isnan(df.iloc[0]["pe_ttm"])
    assert np.isnan(df.iloc[0]["pe_forward"])


@pytest.mark.asyncio
async def test_fetch_valuation_empty_payload_returns_empty(monkeypatch) -> None:
    """Payload senza 'Symbol' → DataFrame vuoto (graceful degradation)."""
    fetcher = _make_fetcher(monkeypatch)

    with patch.object(fetcher, "_get_json", return_value={}):
        with patch(
            "engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher.is_enabled",
            return_value=True,
        ):
            df = await fetcher.fetch_valuation("AAPL")

    assert df.empty


# ─── Test: fetch_income_statement ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_income_statement_returns_quarters(monkeypatch) -> None:
    """fetch_income_statement con 2 quarter → DataFrame 2 righe."""
    fetcher = _make_fetcher(monkeypatch)

    with patch.object(fetcher, "_get_json", return_value=_INCOME_PAYLOAD):
        with patch(
            "engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher.is_enabled",
            return_value=True,
        ):
            df = await fetcher.fetch_income_statement("AAPL", limit_quarters=4)

    assert len(df) == 2
    assert df.iloc[0]["revenue"] == pytest.approx(124_300_000_000.0)
    assert df.iloc[0]["eps_diluted"] == pytest.approx(1.89)


@pytest.mark.asyncio
async def test_fetch_income_statement_limit_respected(monkeypatch) -> None:
    """limit_quarters limita il numero di righe restituite."""
    fetcher = _make_fetcher(monkeypatch)

    with patch.object(fetcher, "_get_json", return_value=_INCOME_PAYLOAD):
        with patch(
            "engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher.is_enabled",
            return_value=True,
        ):
            df = await fetcher.fetch_income_statement("AAPL", limit_quarters=1)

    assert len(df) == 1


# ─── Test: fetch_balance_sheet ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_balance_sheet_debt_sum(monkeypatch) -> None:
    """total_debt = longTermDebt + currentDebt."""
    fetcher = _make_fetcher(monkeypatch)

    with patch.object(fetcher, "_get_json", return_value=_BALANCE_PAYLOAD):
        with patch(
            "engine.market_data.fetchers.alpha_vantage_fundamentals_fetcher.is_enabled",
            return_value=True,
        ):
            df = await fetcher.fetch_balance_sheet("AAPL")

    expected_debt = 97_000_000_000.0 + 22_000_000_000.0
    assert df.iloc[0]["total_debt"] == pytest.approx(expected_debt)


# ─── Test: _check_payload_for_errors ─────────────────────────────────────────

def test_check_payload_rate_limit_raises(monkeypatch) -> None:
    """Payload con 'Note' (rate limit AV) → FetchError.

    ANTI-REGRESSIONE: AV usa HTTP 200 + 'Note' per segnalare rate limit.
    Questo comportamento si è già manifestato in produzione (v6.x).
    """
    fetcher = _make_fetcher(monkeypatch)
    from shared.exceptions import FetchError

    with pytest.raises(FetchError, match="rate limited"):
        fetcher._check_payload_for_errors({"Note": "API call limit reached"})


def test_check_payload_error_message_raises(monkeypatch) -> None:
    """Payload con 'Error Message' → FetchError."""
    fetcher = _make_fetcher(monkeypatch)
    from shared.exceptions import FetchError

    with pytest.raises(FetchError):
        fetcher._check_payload_for_errors({"Error Message": "Invalid API key."})


def test_check_payload_valid_does_not_raise(monkeypatch) -> None:
    """Payload valido (con Symbol) non lancia eccezioni."""
    fetcher = _make_fetcher(monkeypatch)
    fetcher._check_payload_for_errors(_OVERVIEW_PAYLOAD)  # nessuna eccezione
