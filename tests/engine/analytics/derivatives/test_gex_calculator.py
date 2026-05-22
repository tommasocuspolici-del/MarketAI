from __future__ import annotations

import math
import pytest
import numpy as np
import pandas as pd

from engine.analytics.derivatives.gex_calculator import (
    GEXCalculator,
    GEXResult,
    RISK_FREE_RATE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_option_chain() -> pd.DataFrame:
    return pd.DataFrame({
        "strike":           [490.0, 500.0, 510.0],
        "optionType":       ["call", "call", "put"],
        "openInterest":     [1000, 2000, 1500],
        "impliedVolatility": [0.18, 0.17, 0.19],
    })


@pytest.fixture()
def calc() -> GEXCalculator:
    return GEXCalculator()


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

class TestInstantiation:
    def test_default_risk_free_rate(self) -> None:
        c = GEXCalculator()
        assert c._r == RISK_FREE_RATE

    def test_custom_risk_free_rate(self) -> None:
        c = GEXCalculator(risk_free_rate=0.03)
        assert c._r == 0.03


# ---------------------------------------------------------------------------
# _black_scholes_gamma
# ---------------------------------------------------------------------------

class TestBlackScholesGamma:
    def test_returns_non_negative_float(self, calc: GEXCalculator) -> None:
        gamma = calc._black_scholes_gamma(S=500, K=500, T=30/365, r=0.05, sigma=0.2)
        assert isinstance(gamma, float)
        assert gamma >= 0.0

    def test_atm_gamma_positive(self, calc: GEXCalculator) -> None:
        gamma = calc._black_scholes_gamma(S=500, K=500, T=30/365, r=0.05, sigma=0.2)
        assert gamma > 0.0

    def test_zero_time_returns_zero(self, calc: GEXCalculator) -> None:
        gamma = calc._black_scholes_gamma(S=500, K=500, T=0.0, r=0.05, sigma=0.2)
        assert gamma == 0.0

    def test_zero_vol_returns_zero(self, calc: GEXCalculator) -> None:
        gamma = calc._black_scholes_gamma(S=500, K=500, T=30/365, r=0.05, sigma=0.0)
        assert gamma == 0.0

    def test_deep_itm_gamma_finite(self, calc: GEXCalculator) -> None:
        gamma = calc._black_scholes_gamma(S=1000, K=100, T=30/365, r=0.05, sigma=0.2)
        assert math.isfinite(gamma)

    def test_deep_otm_gamma_near_zero(self, calc: GEXCalculator) -> None:
        gamma = calc._black_scholes_gamma(S=100, K=1000, T=30/365, r=0.05, sigma=0.2)
        assert gamma >= 0.0
        assert gamma < 1.0  # not huge


# ---------------------------------------------------------------------------
# compute
# ---------------------------------------------------------------------------

class TestCompute:
    def test_returns_gex_result(self, calc: GEXCalculator) -> None:
        chain = _make_option_chain()
        result = calc.compute(chain, spot_price=500.0, days_to_expiry=30)
        assert isinstance(result, GEXResult)

    def test_total_gex_equals_call_minus_put(self, calc: GEXCalculator) -> None:
        chain = _make_option_chain()
        result = calc.compute(chain, spot_price=500.0, days_to_expiry=30)
        # put_gex is already negated in compute; total = call_gex + put_gex
        assert math.isclose(result.total_gex, result.call_gex + result.put_gex, rel_tol=1e-9)

    def test_call_gex_positive(self, calc: GEXCalculator) -> None:
        chain = _make_option_chain()
        result = calc.compute(chain, spot_price=500.0, days_to_expiry=30)
        assert result.call_gex > 0.0

    def test_put_gex_negative(self, calc: GEXCalculator) -> None:
        chain = _make_option_chain()
        result = calc.compute(chain, spot_price=500.0, days_to_expiry=30)
        assert result.put_gex < 0.0

    def test_is_positive_gamma_matches_total_gex(self, calc: GEXCalculator) -> None:
        chain = _make_option_chain()
        result = calc.compute(chain, spot_price=500.0, days_to_expiry=30)
        assert result.is_positive_gamma == (result.total_gex > 0)

    def test_gex_by_strike_is_dataframe(self, calc: GEXCalculator) -> None:
        chain = _make_option_chain()
        result = calc.compute(chain, spot_price=500.0, days_to_expiry=30)
        assert isinstance(result.gex_by_strike, pd.DataFrame)

    def test_gex_by_strike_has_correct_columns(self, calc: GEXCalculator) -> None:
        chain = _make_option_chain()
        result = calc.compute(chain, spot_price=500.0, days_to_expiry=30)
        assert "strike" in result.gex_by_strike.columns
        assert "gex" in result.gex_by_strike.columns

    def test_invalid_spot_returns_empty(self, calc: GEXCalculator) -> None:
        chain = _make_option_chain()
        result = calc.compute(chain, spot_price=0.0, days_to_expiry=30)
        assert result.total_gex == 0.0

    def test_invalid_dte_returns_empty(self, calc: GEXCalculator) -> None:
        chain = _make_option_chain()
        result = calc.compute(chain, spot_price=500.0, days_to_expiry=0)
        assert result.total_gex == 0.0

    def test_missing_columns_returns_empty(self, calc: GEXCalculator) -> None:
        chain = pd.DataFrame({"strike": [500.0], "openInterest": [100]})
        result = calc.compute(chain, spot_price=500.0, days_to_expiry=30)
        assert result.total_gex == 0.0

    def test_all_calls_positive_total_gex(self, calc: GEXCalculator) -> None:
        chain = pd.DataFrame({
            "strike":           [490.0, 500.0, 510.0],
            "optionType":       ["call", "call", "call"],
            "openInterest":     [1000, 2000, 1500],
            "impliedVolatility": [0.18, 0.17, 0.19],
        })
        result = calc.compute(chain, spot_price=500.0, days_to_expiry=30)
        assert result.total_gex > 0.0
        assert result.is_positive_gamma is True

    def test_all_puts_negative_total_gex(self, calc: GEXCalculator) -> None:
        chain = pd.DataFrame({
            "strike":           [490.0, 500.0, 510.0],
            "optionType":       ["put", "put", "put"],
            "openInterest":     [1000, 2000, 1500],
            "impliedVolatility": [0.18, 0.17, 0.19],
        })
        result = calc.compute(chain, spot_price=500.0, days_to_expiry=30)
        assert result.total_gex < 0.0
        assert result.is_positive_gamma is False
