"""Extra coverage: LeadLagAnalyzer persist path and null result branch."""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from engine.analytics.correlation.lead_lag_analyzer import LeadLagAnalyzer, LeadLagResult


def _make_returns(tickers: list[str], n: int = 120) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    return pd.DataFrame(
        rng.normal(0, 0.01, (n, len(tickers))),
        columns=tickers,
    )


class TestLeadLagPersist:
    def test_test_pair_calls_persist_with_db(self):
        db = MagicMock()
        analyzer = LeadLagAnalyzer(client=db)
        returns = _make_returns(["HYG", "SPY"], n=120)
        result = analyzer.test_pair(returns, "HYG", "SPY")
        assert isinstance(result, LeadLagResult)
        assert db.execute.called

    def test_test_pair_no_persist_without_db(self):
        analyzer = LeadLagAnalyzer(client=None)
        returns = _make_returns(["HYG", "SPY"], n=120)
        result = analyzer.test_pair(returns, "HYG", "SPY")
        assert isinstance(result, LeadLagResult)

    def test_null_result_on_missing_ticker(self):
        analyzer = LeadLagAnalyzer(client=None)
        returns = _make_returns(["SPY"], n=120)
        # "HYG" not in returns
        result = analyzer.test_pair(returns, "HYG", "SPY")
        assert result.lead_signal == "neutral"
        assert result.granger_pvalue == 1.0

    def test_null_result_on_short_series(self):
        analyzer = LeadLagAnalyzer(client=None)
        returns = _make_returns(["HYG", "SPY"], n=10)  # < 60 rows
        result = analyzer.test_pair(returns, "HYG", "SPY")
        assert result.lead_signal == "neutral"

    def test_test_all_pairs_with_persist(self):
        db = MagicMock()
        analyzer = LeadLagAnalyzer(client=db)
        returns = _make_returns(["HYG", "SPY", "TLT"], n=120)
        results = analyzer.test_all_pairs(returns)
        assert len(results) == 3  # 3 pairs from 3 assets
        assert all(isinstance(r, LeadLagResult) for r in results)
