"""Tests for ExpectedMoveCalculator — DoD: expected_move = IV * spot * sqrt(T)."""
from __future__ import annotations

import math

import pytest

from engine.options.expected_move import ExpectedMoveCalculator, ExpectedMoveResult

_CALC = ExpectedMoveCalculator()


class TestExpectedMoveFormula:
    def test_basic_formula(self):
        r = _CALC.calculate(spot=100.0, iv=0.20, t_years=1.0)
        # IV=20%, T=1y → move = 0.20 * 100 * 1 = 20
        assert r.move_abs == pytest.approx(20.0, rel=1e-9)

    def test_quarterly(self):
        r = _CALC.calculate(spot=100.0, iv=0.20, t_years=0.25)
        expected = 0.20 * 100.0 * math.sqrt(0.25)
        assert r.move_abs == pytest.approx(expected, rel=1e-9)

    def test_move_pct_equals_iv_times_sqrt_t(self):
        r = _CALC.calculate(spot=100.0, iv=0.20, t_years=0.5)
        assert r.move_pct == pytest.approx(0.20 * math.sqrt(0.5), rel=1e-9)

    def test_upper_lower_1sigma(self):
        r = _CALC.calculate(spot=100.0, iv=0.20, t_years=1.0)
        assert r.upper_1sigma == pytest.approx(120.0, rel=1e-9)
        assert r.lower_1sigma == pytest.approx(80.0, rel=1e-9)

    def test_upper_lower_2sigma(self):
        r = _CALC.calculate(spot=100.0, iv=0.20, t_years=1.0)
        assert r.upper_2sigma == pytest.approx(140.0, rel=1e-9)
        assert r.lower_2sigma == pytest.approx(60.0, rel=1e-9)

    def test_symmetry(self):
        r = _CALC.calculate(spot=200.0, iv=0.15, t_years=0.5)
        assert r.upper_1sigma - r.spot == pytest.approx(r.spot - r.lower_1sigma, rel=1e-9)


class TestEdgeCases:
    def test_zero_spot_returns_zero_move(self):
        r = _CALC.calculate(spot=0.0, iv=0.20, t_years=1.0)
        assert r.move_abs == 0.0

    def test_zero_iv_returns_zero_move(self):
        r = _CALC.calculate(spot=100.0, iv=0.0, t_years=1.0)
        assert r.move_abs == 0.0

    def test_zero_t_returns_zero_move(self):
        r = _CALC.calculate(spot=100.0, iv=0.20, t_years=0.0)
        assert r.move_abs == 0.0

    def test_result_is_frozen(self):
        r = _CALC.calculate(spot=100.0, iv=0.20, t_years=1.0)
        with pytest.raises(Exception):
            r.move_abs = 0.0  # type: ignore[misc]


class TestCalculateDays:
    def test_30_days_equivalent(self):
        r_days  = _CALC.calculate_days(spot=100.0, iv=0.20, days=30)
        r_years = _CALC.calculate(spot=100.0, iv=0.20, t_years=30 / 365.0)
        assert r_days.move_abs == pytest.approx(r_years.move_abs, rel=1e-9)

    def test_365_days_equals_annual(self):
        r = _CALC.calculate_days(spot=100.0, iv=0.20, days=365)
        assert r.move_abs == pytest.approx(20.0, rel=1e-4)

    def test_high_vol(self):
        r = _CALC.calculate_days(spot=500.0, iv=0.50, days=30)
        expected = 0.50 * 500.0 * math.sqrt(30 / 365.0)
        assert r.move_abs == pytest.approx(expected, rel=1e-9)

    def test_fields_stored(self):
        r = _CALC.calculate(spot=150.0, iv=0.25, t_years=0.5)
        assert r.spot == 150.0
        assert r.iv == 0.25
        assert r.t_years == 0.5
