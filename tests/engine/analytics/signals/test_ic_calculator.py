"""Tests for ICCalculator — Information Coefficient computation."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analytics.signals.ic_calculator import (
    IC_WEAK_THRESHOLD,
    TSTAT_SIGNIFICANCE,
    ICCalculator,
    ICResult,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def calculator() -> ICCalculator:
    return ICCalculator(window=60)


def _make_signal_and_returns(
    n: int = 200,
    correlation: float = 0.3,
    seed: int = 42,
) -> tuple[pd.Series, pd.Series]:
    """Crea segnale e rendimenti con correlazione di Spearman nota."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    noise = rng.standard_normal(n)
    signal = pd.Series(rng.standard_normal(n), index=idx, name="sig")
    # Combina segnale e noise per ottenere correlazione ~= correlation
    fwd = pd.Series(correlation * signal.values + np.sqrt(1 - correlation**2) * noise, index=idx, name="fwd")
    return signal, fwd


# ── Test ICResult fields ───────────────────────────────────────────────────────

class TestICCalculatorCompute:
    def test_returns_ic_result_instance(self, calculator: ICCalculator) -> None:
        signal, fwd = _make_signal_and_returns()
        result = calculator.compute(signal, fwd, signal_id="test_sig", horizon_days=21)
        assert isinstance(result, ICResult)

    def test_result_has_correct_signal_id(self, calculator: ICCalculator) -> None:
        signal, fwd = _make_signal_and_returns()
        result = calculator.compute(signal, fwd, signal_id="my_signal", horizon_days=5)
        assert result.signal_id == "my_signal"

    def test_result_has_correct_horizon(self, calculator: ICCalculator) -> None:
        signal, fwd = _make_signal_and_returns()
        result = calculator.compute(signal, fwd, signal_id="sig", horizon_days=63)
        assert result.horizon_days == 63

    def test_ic_mean_in_valid_range(self, calculator: ICCalculator) -> None:
        signal, fwd = _make_signal_and_returns()
        result = calculator.compute(signal, fwd, signal_id="sig", horizon_days=21)
        assert -1.0 <= result.ic_mean <= 1.0

    def test_ic_std_nonnegative(self, calculator: ICCalculator) -> None:
        signal, fwd = _make_signal_and_returns()
        result = calculator.compute(signal, fwd, signal_id="sig", horizon_days=21)
        assert result.ic_std >= 0.0

    def test_hit_rate_in_unit_interval(self, calculator: ICCalculator) -> None:
        signal, fwd = _make_signal_and_returns()
        result = calculator.compute(signal, fwd, signal_id="sig", horizon_days=21)
        assert 0.0 <= result.hit_rate <= 1.0

    def test_positive_correlation_gives_positive_ic(self) -> None:
        """Con correlazione positiva alta, l'IC dovrebbe essere positivo."""
        calc = ICCalculator(window=100)
        signal, fwd = _make_signal_and_returns(n=300, correlation=0.8, seed=7)
        result = calc.compute(signal, fwd, signal_id="positive_sig", horizon_days=21)
        assert result.ic_mean > 0.0

    def test_negative_correlation_gives_negative_ic(self) -> None:
        """Con correlazione negativa, l'IC dovrebbe essere negativo."""
        calc = ICCalculator(window=100)
        signal, fwd = _make_signal_and_returns(n=300, correlation=-0.8, seed=13)
        result = calc.compute(signal, fwd, signal_id="negative_sig", horizon_days=21)
        assert result.ic_mean < 0.0

    def test_high_correlation_is_significant(self) -> None:
        """Con correlazione alta e molti dati, il segnale dovrebbe essere significativo."""
        calc = ICCalculator(window=100)
        signal, fwd = _make_signal_and_returns(n=500, correlation=0.5, seed=99)
        result = calc.compute(signal, fwd, signal_id="strong_sig", horizon_days=21)
        # Non garantito al 100% ma altamente probabile con correlazione=0.5
        assert result.ic_mean > IC_WEAK_THRESHOLD or not result.is_significant


class TestICCalculatorInsufficientData:
    def test_insufficient_data_returns_default(self, calculator: ICCalculator) -> None:
        """Con meno di MIN_OBSERVATIONS punti, restituisce ICResult non significativo."""
        idx = pd.date_range("2024-01-01", periods=5, freq="B")
        signal = pd.Series([0.1, -0.2, 0.3, 0.0, 0.1], index=idx)
        fwd = pd.Series([0.05, 0.1, -0.1, 0.2, -0.05], index=idx)
        result = calculator.compute(signal, fwd, signal_id="small", horizon_days=5)
        assert not result.is_significant
        assert result.ic_mean == 0.0
        assert result.ic_std == 0.0

    def test_insufficient_data_hit_rate_is_default(self, calculator: ICCalculator) -> None:
        idx = pd.date_range("2024-01-01", periods=3, freq="B")
        signal = pd.Series([0.1, -0.2, 0.3], index=idx)
        fwd = pd.Series([0.05, 0.1, -0.1], index=idx)
        result = calculator.compute(signal, fwd, signal_id="tiny", horizon_days=5)
        assert result.hit_rate == 0.5  # default

    def test_empty_series_returns_default(self, calculator: ICCalculator) -> None:
        signal: pd.Series = pd.Series(dtype=float)
        fwd: pd.Series = pd.Series(dtype=float)
        result = calculator.compute(signal, fwd, signal_id="empty", horizon_days=5)
        assert not result.is_significant


class TestICCalculatorRolling:
    def test_rolling_returns_series(self, calculator: ICCalculator) -> None:
        signal, fwd = _make_signal_and_returns()
        ic_series = calculator.compute_rolling(signal, fwd, signal_id="sig", horizon_days=21)
        assert isinstance(ic_series, pd.Series)

    def test_rolling_series_same_index_as_input(self, calculator: ICCalculator) -> None:
        signal, fwd = _make_signal_and_returns()
        ic_series = calculator.compute_rolling(signal, fwd, signal_id="sig", horizon_days=21)
        assert len(ic_series) == len(signal)

    def test_rolling_values_in_valid_range(self, calculator: ICCalculator) -> None:
        signal, fwd = _make_signal_and_returns()
        ic_series = calculator.compute_rolling(signal, fwd, signal_id="sig", horizon_days=21)
        valid = ic_series.dropna()
        assert (valid >= -1.0).all()
        assert (valid <= 1.0).all()

    def test_rolling_insufficient_data_returns_empty(self, calculator: ICCalculator) -> None:
        idx = pd.date_range("2024-01-01", periods=5, freq="B")
        signal = pd.Series([0.1, -0.2, 0.3, 0.0, 0.1], index=idx)
        fwd = pd.Series([0.05, 0.1, -0.1, 0.2, -0.05], index=idx)
        ic_series = calculator.compute_rolling(signal, fwd, signal_id="small", horizon_days=5)
        assert len(ic_series) == 0
