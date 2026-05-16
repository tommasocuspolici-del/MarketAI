"""Tests for StrategyBuilder — straddle, collar, covered_call, vertical spread."""
from __future__ import annotations

import pytest

from engine.options.strategy_builder import StrategyBuilder, StrategyResult

_BUILDER = StrategyBuilder()

# Common parameters
_S = 100.0
_T = 0.25
_R = 0.05
_SIG = 0.20


class TestStrategyResult:
    def test_result_is_frozen(self):
        r = _BUILDER.straddle(S=_S, K=_S, T=_T, r=_R, sigma=_SIG)
        with pytest.raises(Exception):
            r.net_premium = 0.0  # type: ignore[misc]

    def test_pnl_profile_has_100_points(self):
        r = _BUILDER.straddle(S=_S, K=_S, T=_T, r=_R, sigma=_SIG)
        assert len(r.pnl_profile) == 100

    def test_pnl_profile_covers_range(self):
        r = _BUILDER.straddle(S=_S, K=_S, T=_T, r=_R, sigma=_SIG)
        spots = [p[0] for p in r.pnl_profile]
        assert min(spots) == pytest.approx(_S * 0.5, rel=0.01)
        assert max(spots) == pytest.approx(_S * 1.5, rel=0.01)


class TestStraddle:
    def _r(self, **kwargs):
        defaults = dict(S=_S, K=_S, T=_T, r=_R, sigma=_SIG)
        defaults.update(kwargs)
        return _BUILDER.straddle(**defaults)

    def test_name(self):
        assert self._r().strategy_name == "straddle"

    def test_net_premium_positive(self):
        r = self._r()
        assert r.net_premium > 0    # debit strategy

    def test_max_loss_equals_negative_premium(self):
        r = self._r()
        assert r.max_loss == pytest.approx(-r.net_premium, rel=1e-9)

    def test_two_breakevens(self):
        r = self._r()
        assert len(r.breakevens) == 2
        assert r.breakevens[0] < _S < r.breakevens[1]

    def test_pnl_at_atm_is_negative(self):
        r = self._r()
        # At spot == K, both options expire worthless: P&L = -premium
        pnl_at_k = next(pnl for (spot, pnl) in r.pnl_profile
                        if abs(spot - _S) < 1.0)
        assert pnl_at_k < 0

    def test_pnl_far_otm_positive(self):
        r = self._r()
        # At spot = S * 1.5 (far ITM for call), P&L should be positive
        pnl_far = r.pnl_profile[-1][1]
        assert pnl_far > 0

    def test_two_legs(self):
        r = self._r()
        assert len(r.legs) == 2
        types = {leg["type"] for leg in r.legs}
        assert types == {"long_call", "long_put"}

    def test_high_vol_higher_premium(self):
        r_low  = self._r(sigma=0.10)
        r_high = self._r(sigma=0.40)
        assert r_high.net_premium > r_low.net_premium


class TestCollar:
    def _r(self, **kwargs):
        defaults = dict(S=_S, K_put=92.0, K_call=108.0, T=_T, r=_R, sigma=_SIG)
        defaults.update(kwargs)
        return _BUILDER.collar(**defaults)

    def test_name(self):
        assert self._r().strategy_name == "collar"

    def test_three_legs(self):
        r = self._r()
        assert len(r.legs) == 3
        types = {leg["type"] for leg in r.legs}
        assert types == {"long_stock", "long_put", "short_call"}

    def test_max_profit_finite(self):
        r = self._r()
        assert r.max_profit < 1e9    # capped upside

    def test_max_loss_finite(self):
        r = self._r()
        assert r.max_loss > -1e9    # floor (limited downside)

    def test_max_loss_less_than_max_profit(self):
        r = self._r()
        assert r.max_loss < r.max_profit

    def test_pnl_at_floor_bounded(self):
        r = self._r()
        # Below floor (K_put=92) P&L should be flat ≈ max_loss (within rounding)
        pnl_at_80 = next(pnl for (spot, pnl) in r.pnl_profile if abs(spot - 80) < 1.5)
        pnl_at_60 = next(pnl for (spot, pnl) in r.pnl_profile if abs(spot - 60) < 1.5)
        # Both well below K_put=92: P&L should be approximately equal (flat collar floor)
        assert abs(pnl_at_80 - pnl_at_60) < 1.0

    def test_collar_near_zero_net(self):
        # Zero-cost collar: symmetric strikes
        r = _BUILDER.collar(S=100, K_put=95, K_call=105, T=0.5, r=0.05, sigma=0.20)
        # Net premium should be small (positive or negative)
        assert abs(r.net_premium) < 5.0


class TestCoveredCall:
    def _r(self, **kwargs):
        defaults = dict(S=_S, K=108.0, T=_T, r=_R, sigma=_SIG)
        defaults.update(kwargs)
        return _BUILDER.covered_call(**defaults)

    def test_name(self):
        assert self._r().strategy_name == "covered_call"

    def test_two_legs(self):
        r = self._r()
        types = {leg["type"] for leg in r.legs}
        assert types == {"long_stock", "short_call"}

    def test_net_premium_negative_credit(self):
        r = self._r()
        assert r.net_premium < 0    # credit received

    def test_max_profit_capped(self):
        r = self._r(K=108.0)
        # Max profit: (K - S + call_premium) * shares
        assert r.max_profit > 0
        assert r.max_profit < 2000   # sanity: < (108-100+10)*100

    def test_breakeven_below_spot(self):
        r = self._r()
        assert r.breakevens[0] < _S   # premium reduces breakeven (per-share)

    def test_pnl_above_strike_is_flat(self):
        r = self._r(K=108.0)
        # P&L at 120 and 130 should be nearly identical (capped by short call)
        pnl_120 = next(pnl for (s, pnl) in r.pnl_profile if abs(s - 120) < 2)
        pnl_130 = next(pnl for (s, pnl) in r.pnl_profile if abs(s - 130) < 2)
        assert abs(pnl_120 - pnl_130) < 1.0   # should be flat above K


class TestVerticalSpread:
    def test_bull_call_spread_name(self):
        r = _BUILDER.vertical_spread(S=_S, K_long=100, K_short=110,
                                      T=_T, r=_R, sigma=_SIG, option_type="call")
        assert r.strategy_name == "vertical_call_spread"

    def test_bear_put_spread_name(self):
        r = _BUILDER.vertical_spread(S=_S, K_long=100, K_short=90,
                                      T=_T, r=_R, sigma=_SIG, option_type="put")
        assert r.strategy_name == "vertical_put_spread"

    def test_bull_call_debit(self):
        r = _BUILDER.vertical_spread(S=_S, K_long=100, K_short=110,
                                      T=_T, r=_R, sigma=_SIG, option_type="call")
        assert r.net_premium > 0    # debit

    def test_bull_call_max_loss_equals_negative_premium(self):
        r = _BUILDER.vertical_spread(S=_S, K_long=100, K_short=110,
                                      T=_T, r=_R, sigma=_SIG, option_type="call")
        assert r.max_loss == pytest.approx(-r.net_premium, rel=1e-9)

    def test_bull_call_max_profit(self):
        K_long, K_short = 100.0, 110.0
        r = _BUILDER.vertical_spread(S=_S, K_long=K_long, K_short=K_short,
                                      T=_T, r=_R, sigma=_SIG, option_type="call")
        # Max profit = spread width - net debit
        assert r.max_profit == pytest.approx(
            (K_short - K_long) - r.net_premium, rel=1e-9
        )

    def test_two_legs(self):
        r = _BUILDER.vertical_spread(S=_S, K_long=100, K_short=110,
                                      T=_T, r=_R, sigma=_SIG, option_type="call")
        assert len(r.legs) == 2

    def test_bear_put_spread_max_profit(self):
        K_long, K_short = 100.0, 90.0
        r = _BUILDER.vertical_spread(S=_S, K_long=K_long, K_short=K_short,
                                      T=_T, r=_R, sigma=_SIG, option_type="put")
        assert r.max_profit == pytest.approx(
            abs(K_long - K_short) - r.net_premium, rel=1e-9
        )

    def test_pnl_profile_not_empty(self):
        r = _BUILDER.vertical_spread(S=_S, K_long=100, K_short=110,
                                      T=_T, r=_R, sigma=_SIG, option_type="call")
        assert len(r.pnl_profile) == 100
