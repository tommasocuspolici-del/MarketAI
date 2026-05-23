"""Tests for ComponentVaRCalculator."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from shared.exceptions import MarketAIError

from engine.analytics.risk.component_var import (
    ComponentVaRCalculator,
    ComponentVaRResult,
    CONFIDENCE_DEFAULT,
)


def _make_returns_matrix(
    n_assets: int = 4,
    n_obs: int = 252,
    seed: int = 42,
) -> tuple[pd.DataFrame, list[str]]:
    """Genera matrice rendimenti sintetici e lista ticker."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n_obs, freq="B", tz="UTC")
    tickers = [f"TICK{i}" for i in range(n_assets)]
    rets = rng.normal(0.0, 0.01, (n_obs, n_assets))
    df = pd.DataFrame(rets, index=dates, columns=tickers)
    return df, tickers


class TestComponentVaRCalculator:
    """Test suite per ComponentVaRCalculator."""

    def test_compute_returns_list_of_results(self) -> None:
        """compute() restituisce lista di ComponentVaRResult."""
        rets, tickers = _make_returns_matrix(4, 252)
        weights = np.array([0.25, 0.25, 0.25, 0.25])
        calc = ComponentVaRCalculator()
        results = calc.compute(weights, rets, tickers)
        assert isinstance(results, list)
        assert len(results) == 4

    def test_result_types(self) -> None:
        """Ogni elemento è ComponentVaRResult con campi float."""
        rets, tickers = _make_returns_matrix(3, 200)
        weights = np.array([0.5, 0.3, 0.2])
        results = ComponentVaRCalculator().compute(weights, rets, tickers)
        for r in results:
            assert isinstance(r, ComponentVaRResult)
            assert isinstance(r.ticker, str)
            assert isinstance(r.weight, float)
            assert isinstance(r.marginal_var, float)
            assert isinstance(r.component_var, float)
            assert isinstance(r.pct_risk, float)

    def test_tickers_match(self) -> None:
        """Ticker nei risultati corrispondono all'input."""
        rets, tickers = _make_returns_matrix(4, 252)
        weights = np.array([0.4, 0.2, 0.2, 0.2])
        results = ComponentVaRCalculator().compute(weights, rets, tickers)
        result_tickers = [r.ticker for r in results]
        assert result_tickers == tickers

    def test_component_var_sum_approx_portfolio_var(self) -> None:
        """Σ component_var ≈ portfolio VaR (proprietà additività)."""
        rets, tickers = _make_returns_matrix(5, 500)
        weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
        calc = ComponentVaRCalculator(confidence=CONFIDENCE_DEFAULT)
        results = calc.compute(weights, rets, tickers)

        # Portfolio VaR parametrico
        cov = np.cov(rets.to_numpy(dtype=float), rowvar=False)
        port_vol = np.sqrt(weights @ cov @ weights)
        from scipy.stats import norm
        z = float(-norm.ppf(1 - CONFIDENCE_DEFAULT))
        port_var = z * port_vol

        comp_var_sum = sum(r.component_var for r in results)
        # Additività: differenza deve essere piccola (< 1% del VaR)
        assert abs(comp_var_sum - port_var) < max(port_var * 0.02, 1e-8), (
            f"Sum component VaR={comp_var_sum:.6f} vs port VaR={port_var:.6f}"
        )

    def test_pct_risk_sums_to_one(self) -> None:
        """Σ pct_risk ≈ 1.0 (100% del rischio allocato)."""
        rets, tickers = _make_returns_matrix(4, 300)
        weights = np.array([0.3, 0.3, 0.2, 0.2])
        results = ComponentVaRCalculator().compute(weights, rets, tickers)
        total_pct = sum(r.pct_risk for r in results)
        assert abs(total_pct - 1.0) < 0.02, f"Sum pct_risk={total_pct}"

    def test_weights_in_results(self) -> None:
        """I pesi nei risultati corrispondono ai pesi normalizzati."""
        rets, tickers = _make_returns_matrix(3, 200)
        raw_weights = np.array([1.0, 1.0, 1.0])  # non normalizzati
        results = ComponentVaRCalculator().compute(raw_weights, rets, tickers)
        # Normalizzati a 1/3 ciascuno
        for r in results:
            assert abs(r.weight - 1.0 / 3) < 1e-6, f"weight={r.weight}"

    def test_concentrated_portfolio_high_component_var(self) -> None:
        """Asset con peso maggiore ha component VaR più alto (volatilità uguale)."""
        rng = np.random.default_rng(99)
        dates = pd.date_range("2020-01-01", periods=300, freq="B", tz="UTC")
        # Volatilità uguale per tutti
        rets_data = rng.normal(0, 0.01, (300, 3))
        rets = pd.DataFrame(rets_data, index=dates, columns=["A", "B", "C"])
        weights = np.array([0.70, 0.15, 0.15])
        results = ComponentVaRCalculator().compute(weights, rets, ["A", "B", "C"])
        by_ticker = {r.ticker: r for r in results}
        # A ha peso 70%, deve avere component VaR > B e C
        assert by_ticker["A"].component_var > by_ticker["B"].component_var
        assert by_ticker["A"].component_var > by_ticker["C"].component_var

    def test_length_mismatch_raises(self) -> None:
        """Mismatch tra weights e tickers solleva ValueError."""
        rets, tickers = _make_returns_matrix(4, 100)
        weights = np.array([0.5, 0.5])  # solo 2 pesi per 4 tickers
        with pytest.raises((ValueError, MarketAIError)):
            ComponentVaRCalculator().compute(weights, rets, tickers)

    def test_single_asset(self) -> None:
        """Funziona anche con un singolo asset."""
        rng = np.random.default_rng(42)
        dates = pd.date_range("2020-01-01", periods=200, freq="B", tz="UTC")
        rets = pd.DataFrame({"SPY": rng.normal(0, 0.01, 200)}, index=dates)
        weights = np.array([1.0])
        results = ComponentVaRCalculator().compute(weights, rets, ["SPY"])
        assert len(results) == 1
        assert results[0].pct_risk == pytest.approx(1.0, abs=0.01)
