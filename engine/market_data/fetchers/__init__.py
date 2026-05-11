"""Fetchers package — implementations of BaseFetcher.

Each fetcher pulls raw data from an external provider, then delegates
the rest of the Rule-12 pipeline (clean → validate → duckdb_write → cache → return)
to BaseFetcher.
"""
from __future__ import annotations

from engine.market_data.fetchers.alpha_vantage_fetcher import AlphaVantageFetcher
from engine.market_data.fetchers.base_fetcher import (
    BaseMacroFetcher,
    BaseOhlcvFetcher,
    FetchOutcome,
)
from engine.market_data.fetchers.edgar_fetcher import EdgarFact, SECEdgarFetcher
from engine.market_data.fetchers.finnhub_fetcher import FinnhubFetcher, NewsSentiment
from engine.market_data.fetchers.fred_fetcher import FRED_KEY_SERIES, FREDFetcher
from engine.market_data.fetchers.yahoo_fetcher import YahooFetcher

__version__ = "6.0.0"

__all__ = [
    "FRED_KEY_SERIES",
    "AlphaVantageFetcher",
    "BaseMacroFetcher",
    "BaseOhlcvFetcher",
    "EdgarFact",
    "FREDFetcher",
    "FetchOutcome",
    "FinnhubFetcher",
    "NewsSentiment",
    "SECEdgarFetcher",
    "YahooFetcher",
]
