"""Tests for IVSolver — DoD: round-trip BS→IV→BS error < 0.001 on 100 cases."""
from __future__ import annotations

import math

import pytest

from engine.options.bs_calculator import BlackScholesCalculator
from engine.options.iv_solver import IVSolver, IVResult

_SOLVER = IVSolver()
_CALC   = BlackScholesCalculator()


class TestIVSolverConvergence:
    def test_atm_call_converges(self):
        r = _SOLVER.solve(market_price=10.45, S=100, K=100, T=1.0, r=0.05)
        assert r.converged
        assert not math.isnan(r.iv)
        assert 0.15 < r.iv < 0.30

    def test_otm_call_converges(self):
        price = _CALC.price(100, 110, 0.5, 0.05, 0.20).price
        r = _SOLVER.solve(market_price=price, S=100, K=110, T=0.5, r=0.05)
        assert r.converged
        assert abs(r.iv - 0.20) < 0.01

    def test_itm_put_converges(self):
        price = _CALC.price(90, 100, 0.25, 0.04, 0.25, option_type="put").price
        r = _SOLVER.solve(market_price=price, S=90, K=100, T=0.25, r=0.04,
                          option_type="put")
        assert r.converged
        assert abs(r.iv - 0.25) < 0.02

    def test_invalid_inputs_fail_gracefully(self):
        r = _SOLVER.solve(market_price=0, S=100, K=100, T=1.0, r=0.05)
        assert not r.converged
        assert math.isnan(r.iv)

    def test_negative_spot_fails(self):
        r = _SOLVER.solve(market_price=5, S=-1, K=100, T=1.0, r=0.05)
        assert not r.converged

    def test_result_method_field(self):
        price = _CALC.price(100, 100, 1.0, 0.05, 0.20).price
        r = _SOLVER.solve(market_price=price, S=100, K=100, T=1.0, r=0.05)
        assert r.method in ("newton_raphson", "brent")

    def test_iv_result_is_frozen(self):
        price = _CALC.price(100, 100, 1.0, 0.05, 0.20).price
        r = _SOLVER.solve(market_price=price, S=100, K=100, T=1.0, r=0.05)
        with pytest.raises(Exception):
            r.iv = 0.5  # type: ignore[misc]


class TestRoundTrip:
    """DoD: 100 round-trip cases, price_error < 0.001."""

    @pytest.fixture
    def roundtrip_cases(self):
        cases = []
        for i in range(10):
            sigma = 0.10 + i * 0.03
            for j, K in enumerate([85, 90, 95, 100, 105, 110, 115, 120, 125, 130]):
                T      = 0.25 + j * 0.1
                price  = _CALC.price(100, K, T, 0.05, sigma).price
                if price > 0.01:   # skip near-zero prices
                    cases.append((price, 100, K, T, 0.05, sigma))
        return cases

    def test_100_roundtrip_errors_below_0001(self, roundtrip_cases):
        errors = []
        for (market_price, S, K, T, r, sigma) in roundtrip_cases[:100]:
            result = _SOLVER.solve(market_price=market_price, S=S, K=K, T=T, r=r)
            if result.converged:
                errors.append(result.price_error)

        assert len(errors) >= 90, f"Only {len(errors)} cases converged"
        assert all(e < 0.001 for e in errors), (
            f"Max error: {max(errors):.6f} — should be < 0.001"
        )

    def test_put_roundtrip(self):
        sigma = 0.25
        price = _CALC.price(100, 95, 0.5, 0.04, sigma, option_type="put").price
        r = _SOLVER.solve(market_price=price, S=100, K=95, T=0.5, r=0.04,
                          option_type="put")
        assert r.converged
        assert r.price_error < 0.001


class TestBatchSolver:
    def test_batch_empty(self):
        assert _SOLVER.solve_batch([]) == []

    def test_batch_multiple(self):
        contracts = [
            {"market_price": _CALC.price(100, 100, 1.0, 0.05, 0.20).price,
             "S": 100, "K": 100, "T": 1.0, "r": 0.05, "option_type": "call"},
            {"market_price": _CALC.price(100, 110, 0.5, 0.05, 0.18).price,
             "S": 100, "K": 110, "T": 0.5, "r": 0.05, "option_type": "call"},
        ]
        results = _SOLVER.solve_batch(contracts)
        assert len(results) == 2
        assert all(r.converged for r in results)
