"""Tests for BlackScholesCalculator — DoD: put-call parity verified, batch < 200ms."""
from __future__ import annotations

import time

import pytest

from engine.options.bs_calculator import BlackScholesCalculator, BSGreeks, BSResult

_CALC = BlackScholesCalculator()


class TestBSPrice:
    def test_call_positive(self):
        r = _CALC.price(S=100, K=100, T=1.0, r=0.05, sigma=0.20)
        assert r.price > 0

    def test_put_positive(self):
        r = _CALC.price(S=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="put")
        assert r.price > 0

    def test_call_deep_itm(self):
        r = _CALC.price(S=200, K=100, T=1.0, r=0.05, sigma=0.20)
        # Deep ITM call ≈ intrinsic value
        assert r.price > 90

    def test_put_deep_itm(self):
        r = _CALC.price(S=50, K=100, T=1.0, r=0.05, sigma=0.20, option_type="put")
        assert r.price > 40

    def test_zero_expiry_returns_zero(self):
        r = _CALC.price(S=100, K=100, T=0, r=0.05, sigma=0.20)
        assert r.price == 0.0

    def test_zero_sigma_returns_zero(self):
        r = _CALC.price(S=100, K=100, T=1.0, r=0.05, sigma=0.0)
        assert r.price == 0.0

    def test_result_is_frozen_dataclass(self):
        r = _CALC.price(S=100, K=100, T=1.0, r=0.05, sigma=0.20)
        with pytest.raises(Exception):
            r.price = 99.0  # type: ignore[misc]

    def test_known_bs_value(self):
        # S=100, K=100, T=1, r=0.05, sigma=0.20 → ~10.45 (standard textbook)
        r = _CALC.price(S=100, K=100, T=1.0, r=0.05, sigma=0.20)
        assert 10.0 < r.price < 11.0

    def test_put_known_value(self):
        r = _CALC.price(S=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="put")
        assert 5.0 < r.price < 7.0


class TestBSGreeks:
    def _r(self, **kwargs):
        defaults = dict(S=100, K=100, T=1.0, r=0.05, sigma=0.20, q=0.0)
        defaults.update(kwargs)
        return _CALC.price(**defaults)

    def test_call_delta_range(self):
        r = self._r()
        assert 0.0 < r.greeks.delta < 1.0

    def test_put_delta_negative(self):
        r = self._r(option_type="put")
        assert -1.0 < r.greeks.delta < 0.0

    def test_atm_call_delta_near_half(self):
        r = self._r()
        assert 0.45 < r.greeks.delta < 0.65

    def test_gamma_positive(self):
        r = self._r()
        assert r.greeks.gamma > 0

    def test_vega_positive(self):
        r = self._r()
        assert r.greeks.vega > 0

    def test_call_theta_negative(self):
        r = self._r()
        assert r.greeks.theta < 0

    def test_put_theta_negative(self):
        r = self._r(option_type="put")
        assert r.greeks.theta < 0

    def test_call_rho_positive(self):
        r = self._r()
        assert r.greeks.rho > 0

    def test_put_rho_negative(self):
        r = self._r(option_type="put")
        assert r.greeks.rho < 0

    def test_greeks_frozen(self):
        r = self._r()
        with pytest.raises(Exception):
            r.greeks.delta = 0.5  # type: ignore[misc]


class TestPutCallParity:
    """DoD: put-call parity |C - P - (S*e^{-qT} - K*e^{-rT})| < 1e-6."""

    @pytest.mark.parametrize("S,K,T,r,sigma,q", [
        (100, 100, 1.0, 0.05, 0.20, 0.0),
        (100, 110, 0.5, 0.03, 0.25, 0.0),
        (150,  90, 0.25, 0.04, 0.30, 0.0),
        ( 80, 100, 2.0, 0.02, 0.15, 0.0),
        (200, 180, 0.1, 0.05, 0.40, 0.0),
        (100, 100, 1.0, 0.05, 0.20, 0.02),
        (100,  95, 0.75, 0.04, 0.18, 0.01),
        (120, 125, 0.5, 0.03, 0.22, 0.0),
        ( 50,  55, 1.5, 0.06, 0.35, 0.0),
        (300, 280, 0.25, 0.05, 0.12, 0.0),
    ])
    def test_parity(self, S, K, T, r, sigma, q):
        err = _CALC.put_call_parity_check(S=S, K=K, T=T, r=r, sigma=sigma, q=q)
        assert err < 1e-6, f"Put-call parity error {err:.2e} for S={S}, K={K}"


class TestBatchPerformance:
    """DoD: 200 options batch < 200ms."""

    def test_batch_200_under_200ms(self):
        opts = [
            {"S": 100, "K": 100 + (i % 20) * 2, "T": 0.25, "r": 0.05,
             "sigma": 0.20, "q": 0.0, "option_type": "call" if i % 2 == 0 else "put"}
            for i in range(200)
        ]
        t0 = time.perf_counter()
        results = _CALC.price_batch(opts)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert len(results) == 200
        assert elapsed_ms < 200, f"Batch took {elapsed_ms:.1f}ms > 200ms"

    def test_batch_empty(self):
        assert _CALC.price_batch([]) == []

    def test_batch_single(self):
        results = _CALC.price_batch([{"S": 100, "K": 100, "T": 1.0,
                                       "r": 0.05, "sigma": 0.20}])
        assert len(results) == 1
        assert results[0].price > 0
