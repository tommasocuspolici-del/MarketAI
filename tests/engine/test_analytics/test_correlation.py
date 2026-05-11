"""Tests for engine.analytics.correlation."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from engine.analytics.correlation import (
    CorrelationAnalyzer,
    CorrelationReport,
    LeadLagPair,
    RegimeDetector,
    RegimeReport,
)
from shared.exceptions import CorrelationError, InsufficientDataError


def _make_prices(
    n_assets: int = 5, n_obs: int = 252, seed: int = 42, vol: float = 0.018,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n_obs, freq="D", tz="UTC")
    return pd.DataFrame({
        f"TICK{i}": 100 * np.exp(np.cumsum(rng.normal(0.0003, vol, n_obs)))
        for i in range(n_assets)
    }, index=dates)


# ═══════════════════════════════════════════════════════════════════════════
# CorrelationAnalyzer
# ═══════════════════════════════════════════════════════════════════════════
class TestCorrelationAnalyzer:
    def test_basic_run(self) -> None:
        analyzer = CorrelationAnalyzer()
        prices = _make_prices(n_assets=4, n_obs=252)
        rep = analyzer.run(prices)
        assert isinstance(rep, CorrelationReport)
        assert rep.n_assets == 4
        assert rep.n_observations == 251
        assert rep.static_corr.shape == (4, 4)
        # Diagonal of static corr is 1.0
        np.testing.assert_array_almost_equal(
            np.diag(rep.static_corr.to_numpy()), np.ones(4)
        )

    def test_dynamic_correlation_shape(self) -> None:
        analyzer = CorrelationAnalyzer()
        prices = _make_prices(n_assets=3, n_obs=200)
        rep = analyzer.run(prices)
        assert rep.dynamic_corr is not None
        assert rep.dynamic_corr.shape == (3, 3)

    def test_empty_dataframe_raises(self) -> None:
        analyzer = CorrelationAnalyzer()
        with pytest.raises(CorrelationError, match="empty"):
            analyzer.run(pd.DataFrame())

    def test_single_asset_raises(self) -> None:
        analyzer = CorrelationAnalyzer()
        prices = _make_prices(n_assets=1, n_obs=200)
        with pytest.raises(CorrelationError, match="at least 2"):
            analyzer.run(prices)

    def test_insufficient_data_raises(self) -> None:
        analyzer = CorrelationAnalyzer()
        prices = _make_prices(n_assets=3, n_obs=30)
        with pytest.raises(InsufficientDataError):
            analyzer.run(prices)

    def test_invalid_lambda_raises(self) -> None:
        with pytest.raises(CorrelationError, match="ewma_lambda"):
            CorrelationAnalyzer(ewma_lambda=1.5)

    def test_lead_lag_returns_list(self) -> None:
        analyzer = CorrelationAnalyzer()
        prices = _make_prices(n_assets=4, n_obs=252)
        rep = analyzer.run(prices)
        assert isinstance(rep.lead_lag_pairs, list)
        # All pairs should have valid lag > 0 and threshold-passing corr
        for pair in rep.lead_lag_pairs:
            assert isinstance(pair, LeadLagPair)
            assert pair.lag_periods > 0
            assert abs(pair.correlation) >= 0.20


# ═══════════════════════════════════════════════════════════════════════════
# RegimeDetector
# ═══════════════════════════════════════════════════════════════════════════
class TestRegimeDetector:
    def test_basic_run(self) -> None:
        detector = RegimeDetector(n_regimes=4)
        prices = _make_prices(n_assets=1, n_obs=252)["TICK0"]
        rep = detector.run(prices)
        assert isinstance(rep, RegimeReport)
        assert rep.n_regimes == 4
        assert rep.current_regime.label in ("bull", "bear", "transition", "stress")
        assert 0.0 <= rep.current_regime.confidence <= 1.0

    def test_3_regimes(self) -> None:
        detector = RegimeDetector(n_regimes=3)
        prices = _make_prices(n_assets=1, n_obs=252)["TICK0"]
        rep = detector.run(prices)
        assert rep.n_regimes == 3
        assert rep.current_regime.label in ("bull", "bear", "transition")

    def test_invalid_n_regimes_raises(self) -> None:
        with pytest.raises(CorrelationError, match="n_regimes"):
            RegimeDetector(n_regimes=5)

    def test_invalid_input_type_raises(self) -> None:
        detector = RegimeDetector()
        with pytest.raises(CorrelationError, match="Series"):
            detector.run(_make_prices(n_assets=2))   # DataFrame, not Series

    def test_insufficient_data_raises(self) -> None:
        detector = RegimeDetector()
        prices = _make_prices(n_assets=1, n_obs=30)["TICK0"]
        with pytest.raises(InsufficientDataError):
            detector.run(prices)

    def test_history_length(self) -> None:
        detector = RegimeDetector(n_regimes=4, vol_window=20)
        prices = _make_prices(n_assets=1, n_obs=252)["TICK0"]
        rep = detector.run(prices)
        # history = n_obs - 1 (returns) - vol_window + 1 (rolling) ≈ 232
        assert len(rep.regime_history) > 100

    def test_regime_means_consistent(self) -> None:
        """bull regime mean return > bear regime mean return."""
        detector = RegimeDetector(n_regimes=4)
        prices = _make_prices(n_assets=1, n_obs=252)["TICK0"]
        rep = detector.run(prices)
        # By construction (sorted ascending in detector)
        assert rep.regime_means["bull"] > rep.regime_means["bear"]
        assert rep.regime_means["bear"] >= rep.regime_means["stress"]

    def test_deterministic_with_seed(self) -> None:
        detector = RegimeDetector(n_regimes=4)
        prices = _make_prices(n_assets=1, n_obs=200)["TICK0"]
        r1 = detector.run(prices, seed=42)
        r2 = detector.run(prices, seed=42)
        assert r1.current_regime.label == r2.current_regime.label


# ═══════════════════════════════════════════════════════════════════════════
# Performance — DoD: 20 assets < 10s
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.benchmark
class TestCorrelationPerformance:
    def test_20_assets_under_10s(self) -> None:
        """DoD Phase 8: DCC-GARCH-lite 20 assets < 10s."""
        analyzer = CorrelationAnalyzer()
        prices = _make_prices(n_assets=20, n_obs=252)
        t0 = time.monotonic()
        rep = analyzer.run(prices)
        elapsed = time.monotonic() - t0
        assert rep.n_assets == 20
        assert elapsed < 10.0, f"expected <10s, got {elapsed:.2f}s"
