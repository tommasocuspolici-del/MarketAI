"""Tests for VolSurfaceBuilder."""
from __future__ import annotations

import numpy as np
import pytest

from engine.options.bs_calculator import BlackScholesCalculator
from engine.options.vol_surface_builder import VolSurfaceBuilder, VolSurface

_BUILDER = VolSurfaceBuilder()
_CALC    = BlackScholesCalculator()


def _make_contracts(n_strikes=5, n_expiries=3, sigma=0.20, S=100.0):
    """Generate synthetic contracts using BS prices."""
    contracts = []
    strikes  = [S * (0.9 + 0.05 * i) for i in range(n_strikes)]
    expiries = [0.25 + 0.25 * j for j in range(n_expiries)]
    for T in expiries:
        for K in strikes:
            price = _CALC.price(S, K, T, 0.05, sigma).price
            contracts.append({"market_price": price, "S": S, "K": K, "T": T,
                               "r": 0.05, "q": 0.0, "option_type": "call"})
    return contracts


class TestVolSurfaceBuilderBasic:
    def test_empty_contracts(self):
        surface = _BUILDER.build([], spot=100.0)
        assert surface.n_contracts == 0
        assert surface.strikes == []
        assert surface.expiries == []

    def test_builds_surface(self):
        contracts = _make_contracts()
        surface = _BUILDER.build(contracts, spot=100.0)
        assert surface.n_contracts > 0

    def test_strike_count(self):
        contracts = _make_contracts(n_strikes=5)
        surface = _BUILDER.build(contracts, spot=100.0)
        assert len(surface.strikes) == 5

    def test_expiry_count(self):
        contracts = _make_contracts(n_expiries=3)
        surface = _BUILDER.build(contracts, spot=100.0)
        assert len(surface.expiries) == 3

    def test_iv_matrix_shape(self):
        contracts = _make_contracts(n_strikes=4, n_expiries=2)
        surface = _BUILDER.build(contracts, spot=100.0)
        assert surface.iv_matrix.shape == (2, 4)

    def test_iv_values_positive(self):
        contracts = _make_contracts()
        surface = _BUILDER.build(contracts, spot=100.0)
        valid = surface.iv_matrix[~np.isnan(surface.iv_matrix)]
        assert all(v > 0 for v in valid)

    def test_iv_recovery_near_input(self):
        contracts = _make_contracts(sigma=0.25)
        surface = _BUILDER.build(contracts, spot=100.0)
        valid = surface.iv_matrix[~np.isnan(surface.iv_matrix)]
        # Recovered IV should be near 0.25
        assert all(abs(v - 0.25) < 0.02 for v in valid)


class TestATMAndSkew:
    def test_atm_iv_present_for_each_expiry(self):
        contracts = _make_contracts(n_expiries=3)
        surface = _BUILDER.build(contracts, spot=100.0)
        assert len(surface.atm_iv_by_expiry) == 3

    def test_atm_iv_positive(self):
        contracts = _make_contracts()
        surface = _BUILDER.build(contracts, spot=100.0)
        for iv in surface.atm_iv_by_expiry.values():
            assert iv > 0

    def test_skew_present(self):
        contracts = _make_contracts(n_strikes=5)
        surface = _BUILDER.build(contracts, spot=100.0)
        # Skew requires ≥ 2 valid strikes per expiry
        assert len(surface.skew_by_expiry) > 0

    def test_no_contracts_invalid_prices(self):
        contracts = [{"market_price": -1, "S": 100, "K": 100, "T": 0.25,
                      "r": 0.05, "q": 0.0, "option_type": "call"}]
        surface = _BUILDER.build(contracts, spot=100.0)
        assert surface.n_contracts == 0
