"""Tests for engine.backtesting.performance."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.backtesting.performance import (
    PerformanceReport,
    compute_performance_report,
)


def _equity_curve(returns: list[float], initial: float = 10_000.0) -> pd.Series:
    """Build an equity curve from a list of period returns."""
    eq = [initial]
    for r in returns:
        eq.append(eq[-1] * (1.0 + r))
    return pd.Series(eq, dtype="float64")


class TestComputePerformanceReport:
    def test_constant_equity_no_returns(self) -> None:
        # Curva piatta: tutti i metric devono essere zero (no error)
        eq = pd.Series([10_000.0] * 100, dtype="float64")
        report = compute_performance_report(eq)
        assert report.total_return == pytest.approx(0.0)
        assert report.sharpe_ratio == pytest.approx(0.0)
        assert report.max_drawdown == pytest.approx(0.0)

    def test_steadily_growing_equity(self) -> None:
        # 1% per giorno per 252 giorni → ~12x crescita
        rets = [0.01] * 252
        eq = _equity_curve(rets)
        report = compute_performance_report(eq)
        assert report.total_return > 10.0
        assert report.sharpe_ratio > 0.0  # crescita positiva
        # MaxDD nullo (mai un giorno in negativo)
        assert report.max_drawdown == pytest.approx(0.0, abs=1e-9)
        # Win rate = 100%
        assert report.win_rate == pytest.approx(1.0, abs=1e-9)

    def test_drawdown_detected(self) -> None:
        # Salita poi crollo: 100 → 200 → 50
        eq = pd.Series([100.0, 200.0, 50.0], dtype="float64")
        report = compute_performance_report(eq)
        # MaxDD dovrebbe essere ~ -75%
        assert report.max_drawdown < -0.7

    def test_sharpe_positive_for_bullish_curve(self) -> None:
        rng = np.random.default_rng(seed=42)
        rets = rng.normal(0.001, 0.01, size=252).tolist()  # drift positivo
        eq = _equity_curve(rets)
        report = compute_performance_report(eq)
        assert report.sharpe_ratio > 0.5  # rapporto info ragionevole

    def test_sortino_only_uses_downside(self) -> None:
        # Per una serie con drift positivo, Sortino dovrebbe essere >= Sharpe
        # perché la deviation negativa < std totale. Usiamo seed e drift
        # garantiti positivi per evitare il caso patologico (drift negativo
        # dove Sortino può andare peggio del Sharpe).
        rng = np.random.default_rng(seed=10)
        rets = rng.normal(0.002, 0.008, size=300).tolist()  # drift forte positivo
        eq = _equity_curve(rets)
        report = compute_performance_report(eq)
        # Sanity check: la serie deve essere effettivamente bullish
        assert report.sharpe_ratio > 0.0
        # Per una serie bullish, il Sortino dovrebbe essere >= Sharpe
        assert report.sortino_ratio >= report.sharpe_ratio - 0.1

    def test_profit_factor_positive_strategy(self) -> None:
        # Strategia con più gain che loss in valore assoluto
        rets = [0.02, -0.005, 0.015, -0.01, 0.025]
        eq = _equity_curve(rets)
        report = compute_performance_report(eq)
        assert report.profit_factor > 1.0

    def test_calmar_zero_when_no_drawdown(self) -> None:
        # Crescita pura: maxdd=0 → calmar=0 (per definizione del fallback)
        rets = [0.005] * 50
        eq = _equity_curve(rets)
        report = compute_performance_report(eq)
        assert report.calmar_ratio == pytest.approx(0.0)

    def test_empty_series_returns_empty_report(self) -> None:
        eq = pd.Series([], dtype="float64")
        report = compute_performance_report(eq)
        assert report.total_return == 0.0
        assert report.sharpe_ratio == 0.0

    def test_to_dict_structure(self) -> None:
        eq = _equity_curve([0.01, -0.005, 0.02])
        report = compute_performance_report(eq)
        d = report.to_dict()
        for key in (
            "total_return", "sharpe_ratio", "sortino_ratio", "max_drawdown",
            "calmar_ratio", "win_rate", "profit_factor", "n_periods",
        ):
            assert key in d


class TestPerformanceReportDataclass:
    def test_frozen(self) -> None:
        report = PerformanceReport(
            total_return=0.1, annualized_return=0.1, annualized_vol=0.15,
            sharpe_ratio=0.7, sortino_ratio=1.0, max_drawdown=-0.05,
            calmar_ratio=2.0, win_rate=0.55, profit_factor=1.8, n_periods=252,
        )
        with pytest.raises(AttributeError):
            report.total_return = 999.0  # type: ignore[misc]
