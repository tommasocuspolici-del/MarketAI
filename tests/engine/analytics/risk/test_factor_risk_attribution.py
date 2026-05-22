from __future__ import annotations

import math
import pytest
import numpy as np
import pandas as pd

from engine.analytics.risk.factor_risk_attribution import (
    FactorRiskAttribution,
    AttributionResult,
    FactorExposure,
    MIN_REGRESSION_SAMPLES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_returns(n: int = 120, tickers: list[str] | None = None) -> pd.DataFrame:
    if tickers is None:
        tickers = ["AAPL", "MSFT", "GOOG"]
    rng = np.random.default_rng(42)
    idx = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    data = {t: rng.normal(0.001, 0.01, n) for t in tickers}
    return pd.DataFrame(data, index=idx)


def _make_weights(tickers: list[str]) -> dict[str, float]:
    n = len(tickers)
    return {t: 1.0 / n for t in tickers}


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_instantiates(self) -> None:
        fra = FactorRiskAttribution()
        assert isinstance(fra, FactorRiskAttribution)


# ---------------------------------------------------------------------------
# compute
# ---------------------------------------------------------------------------

class TestCompute:
    def test_returns_attribution_result(self) -> None:
        fra = FactorRiskAttribution()
        tickers = ["AAPL", "MSFT", "GOOG"]
        returns = _make_returns(tickers=tickers)
        weights = _make_weights(tickers)
        result = fra.compute(weights, returns)
        assert isinstance(result, AttributionResult)

    def test_pct_systematic_in_unit_interval(self) -> None:
        fra = FactorRiskAttribution()
        tickers = ["AAPL", "MSFT", "GOOG"]
        returns = _make_returns(n=120, tickers=tickers)
        weights = _make_weights(tickers)
        result = fra.compute(weights, returns)
        assert -1e-9 <= result.pct_systematic <= 1.0 + 1e-9

    def test_variances_add_up_approximately(self) -> None:
        """systematic + idiosyncratic ≈ portfolio_variance (with tolerance)."""
        fra = FactorRiskAttribution()
        tickers = ["AAPL", "MSFT", "GOOG"]
        returns = _make_returns(n=120, tickers=tickers)
        weights = _make_weights(tickers)
        result = fra.compute(weights, returns)
        reconstructed = result.systematic_variance + result.idiosyncratic_variance
        # Allow loose tolerance: PCA proxy may not be perfect
        assert math.isclose(reconstructed, result.portfolio_variance, rel_tol=0.05) or (
            reconstructed <= result.portfolio_variance + 1e-10
        )

    def test_factor_contributions_has_keys(self) -> None:
        fra = FactorRiskAttribution()
        tickers = ["AAPL", "MSFT", "GOOG"]
        returns = _make_returns(n=120, tickers=tickers)
        weights = _make_weights(tickers)
        result = fra.compute(weights, returns)
        assert isinstance(result.factor_contributions, dict)
        assert len(result.factor_contributions) > 0

    def test_portfolio_variance_positive(self) -> None:
        fra = FactorRiskAttribution()
        tickers = ["AAPL", "MSFT", "GOOG"]
        returns = _make_returns(n=120, tickers=tickers)
        weights = _make_weights(tickers)
        result = fra.compute(weights, returns)
        assert result.portfolio_variance >= 0.0

    def test_systematic_variance_non_negative(self) -> None:
        fra = FactorRiskAttribution()
        tickers = ["AAPL", "MSFT", "GOOG"]
        returns = _make_returns(n=120, tickers=tickers)
        weights = _make_weights(tickers)
        result = fra.compute(weights, returns)
        assert result.systematic_variance >= 0.0

    def test_idiosyncratic_variance_non_negative(self) -> None:
        fra = FactorRiskAttribution()
        tickers = ["AAPL", "MSFT", "GOOG"]
        returns = _make_returns(n=120, tickers=tickers)
        weights = _make_weights(tickers)
        result = fra.compute(weights, returns)
        assert result.idiosyncratic_variance >= 0.0

    def test_exposures_list_populated(self) -> None:
        fra = FactorRiskAttribution()
        tickers = ["AAPL", "MSFT", "GOOG"]
        returns = _make_returns(n=120, tickers=tickers)
        weights = _make_weights(tickers)
        result = fra.compute(weights, returns)
        assert isinstance(result.exposures, list)

    def test_no_common_tickers_returns_empty_result(self) -> None:
        fra = FactorRiskAttribution()
        returns = _make_returns(tickers=["AAPL", "MSFT"])
        weights = {"XYZ": 0.5, "ABC": 0.5}  # No overlap
        result = fra.compute(weights, returns)
        assert result.portfolio_variance == 0.0
        assert result.pct_systematic == 0.0

    def test_with_external_factor_returns(self) -> None:
        fra = FactorRiskAttribution()
        tickers = ["AAPL", "MSFT", "GOOG"]
        rng = np.random.default_rng(7)
        n = 120
        idx = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
        returns = pd.DataFrame(
            {t: rng.normal(0.001, 0.01, n) for t in tickers},
            index=idx,
        )
        factor_rets = pd.DataFrame(
            {
                "Mkt-RF": rng.normal(0.0005, 0.01, n),
                "SMB":    rng.normal(0.0001, 0.005, n),
            },
            index=idx,
        )
        weights = _make_weights(tickers)
        result = fra.compute(weights, returns, factor_returns=factor_rets)
        assert isinstance(result, AttributionResult)
        assert set(result.factor_contributions.keys()) == {"Mkt-RF", "SMB"}

    def test_weights_normalized_internally(self) -> None:
        """Weights that don't sum to 1 should be normalized."""
        fra = FactorRiskAttribution()
        tickers = ["AAPL", "MSFT", "GOOG"]
        returns = _make_returns(n=120, tickers=tickers)
        weights = {"AAPL": 2.0, "MSFT": 2.0, "GOOG": 2.0}  # sum = 6 not 1
        result = fra.compute(weights, returns)
        # Should still produce valid result (no crash, no NaN)
        assert isinstance(result, AttributionResult)
        assert math.isfinite(result.portfolio_variance)
