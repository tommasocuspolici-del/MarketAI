"""Tests for pre-built indicators #1-6."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_indicators.library.entry_window_indicator import EntryWindowIndicator
from custom_indicators.library.liquidity_reserve_signal import LiquidityReserveSignal
from custom_indicators.library.macro_alignment_score import MacroAlignmentScore
from custom_indicators.library.personal_risk_budget import PersonalRiskBudgetIndicator
from custom_indicators.library.portfolio_momentum import PortfolioMomentumIndicator
from custom_indicators.library.stress_exposure_indicator import StressExposureIndicator
from shared.signal_registry import SignalRegistry
from shared.signal_types import Signal


def _reg(**signals: float) -> SignalRegistry:
    reg = SignalRegistry()
    for name, val in signals.items():
        reg.publish(Signal(name=name, value=val, confidence=0.8, source_module="test"))
    return reg


# ── #1 PersonalRiskBudget ─────────────────────────────────────────────────

class TestPersonalRiskBudget:
    def test_no_returns_neutral(self) -> None:
        ind = PersonalRiskBudgetIndicator()
        r = ind.compute()
        assert r.signal_value == pytest.approx(0.0)

    def test_low_var_positive_signal(self) -> None:
        ind = PersonalRiskBudgetIndicator(max_var_pct=0.15)
        returns = [0.001] * 252   # tiny daily returns → tiny VaR
        r = ind.compute(returns)
        assert r.signal_value > 0

    def test_high_var_negative_signal(self) -> None:
        ind = PersonalRiskBudgetIndicator(max_var_pct=0.01)
        returns = [-0.05] * 252   # large losses → VaR > max
        r = ind.compute(returns)
        assert r.signal_value < 0

    def test_signal_clamped(self) -> None:
        ind = PersonalRiskBudgetIndicator(max_var_pct=0.001)
        returns = [-0.10] * 252
        r = ind.compute(returns)
        assert -1.0 <= r.signal_value <= 1.0

    def test_to_signal_name(self) -> None:
        ind = PersonalRiskBudgetIndicator()
        s = ind.to_signal(ind.compute())
        assert s.name == "custom.personal_risk_budget"


# ── #2 PortfolioMomentum ──────────────────────────────────────────────────

class TestPortfolioMomentum:
    def test_empty_returns_neutral(self) -> None:
        ind = PortfolioMomentumIndicator()
        r = ind.compute()
        assert r.signal_value == pytest.approx(0.0)

    def test_positive_returns_positive_signal(self) -> None:
        ind = PortfolioMomentumIndicator()
        returns = [0.003] * 100   # steady positive daily returns
        r = ind.compute(returns)
        assert r.signal_value > 0

    def test_negative_returns_negative_signal(self) -> None:
        ind = PortfolioMomentumIndicator()
        returns = [-0.003] * 100
        r = ind.compute(returns)
        assert r.signal_value < 0

    def test_to_signal_name(self) -> None:
        ind = PortfolioMomentumIndicator()
        s = ind.to_signal(ind.compute([0.001] * 30))
        assert s.name == "custom.portfolio_momentum"


# ── #3 MacroAlignmentScore ────────────────────────────────────────────────

class TestMacroAlignmentScore:
    def test_positive_macro_positive_signal(self) -> None:
        reg = _reg(macro_conviction=0.6, real_yield_signal=0.4, credit_spread_signal=0.3)
        ind = MacroAlignmentScore()
        with patch("custom_indicators.library.macro_alignment_score.get_signal_registry",
                   return_value=reg):
            r = ind.compute()
        assert r.signal_value > 0

    def test_negative_macro_negative_signal(self) -> None:
        reg = _reg(macro_conviction=-0.6, real_yield_signal=-0.4, credit_spread_signal=-0.3)
        ind = MacroAlignmentScore()
        with patch("custom_indicators.library.macro_alignment_score.get_signal_registry",
                   return_value=reg):
            r = ind.compute()
        assert r.signal_value < 0

    def test_weights_normalised(self) -> None:
        ind = MacroAlignmentScore(macro_weight=1.0, yield_weight=1.0, credit_weight=1.0)
        assert abs(ind._w_macro + ind._w_yield + ind._w_credit - 1.0) < 1e-6

    def test_to_signal_name(self) -> None:
        reg = _reg()
        ind = MacroAlignmentScore()
        with patch("custom_indicators.library.macro_alignment_score.get_signal_registry",
                   return_value=reg):
            s = ind.to_signal(ind.compute())
        assert s.name == "custom.macro_alignment_score"


# ── #4 EntryWindowIndicator ───────────────────────────────────────────────

class TestEntryWindowIndicator:
    def test_all_conditions_met_positive(self) -> None:
        reg = _reg(macro_conviction=0.3, sentiment_composite=0.0, vix_signal=0.0)
        ind = EntryWindowIndicator(macro_threshold=0.0, sentiment_max=0.8, vix_min=14.0, vix_max=35.0)
        with patch("custom_indicators.library.entry_window_indicator.get_signal_registry",
                   return_value=reg):
            r = ind.compute()
        assert r.signal_value > 0

    def test_macro_negative_reduces_score(self) -> None:
        reg = _reg(macro_conviction=-0.5, sentiment_composite=0.0, vix_signal=0.0)
        ind = EntryWindowIndicator()
        with patch("custom_indicators.library.entry_window_indicator.get_signal_registry",
                   return_value=reg):
            r = ind.compute()
        assert not r.conditions_met["macro_positive"]

    def test_signal_in_range(self) -> None:
        reg = _reg()
        ind = EntryWindowIndicator()
        with patch("custom_indicators.library.entry_window_indicator.get_signal_registry",
                   return_value=reg):
            r = ind.compute()
        assert -1.0 <= r.signal_value <= 1.0

    def test_to_signal_name(self) -> None:
        reg = _reg()
        ind = EntryWindowIndicator()
        with patch("custom_indicators.library.entry_window_indicator.get_signal_registry",
                   return_value=reg):
            s = ind.to_signal(ind.compute())
        assert s.name == "custom.entry_window"


# ── #5 StressExposureIndicator ────────────────────────────────────────────

class TestStressExposureIndicator:
    def test_zero_exposure_positive_signal(self) -> None:
        reg = _reg()    # all stresses = 0
        ind = StressExposureIndicator()
        with patch("custom_indicators.library.stress_exposure_indicator.get_signal_registry",
                   return_value=reg):
            r = ind.compute()
        assert r.signal_value >= 0.0

    def test_high_exposure_negative_signal(self) -> None:
        reg = _reg(stress_gfc=0.9, stress_covid=0.9, stress_rate=0.9, stress_custom=0.9)
        ind = StressExposureIndicator()
        with patch("custom_indicators.library.stress_exposure_indicator.get_signal_registry",
                   return_value=reg):
            r = ind.compute()
        assert r.signal_value < 0

    def test_to_signal_name(self) -> None:
        reg = _reg()
        ind = StressExposureIndicator()
        with patch("custom_indicators.library.stress_exposure_indicator.get_signal_registry",
                   return_value=reg):
            s = ind.to_signal(ind.compute())
        assert s.name == "custom.stress_exposure"


# ── #6 LiquidityReserveSignal ─────────────────────────────────────────────

class TestLiquidityReserveSignal:
    def test_above_target_positive(self) -> None:
        ind = LiquidityReserveSignal(min_months=3.0, target_months=6.0)
        r = ind.compute(cash_reserve_months=9.0)
        assert r.signal_value > 0

    def test_below_min_negative(self) -> None:
        ind = LiquidityReserveSignal(min_months=3.0, target_months=6.0)
        r = ind.compute(cash_reserve_months=1.0)
        assert r.signal_value < 0

    def test_at_target_positive(self) -> None:
        ind = LiquidityReserveSignal(min_months=3.0, target_months=6.0)
        r = ind.compute(cash_reserve_months=6.0)
        assert r.signal_value >= 0

    def test_zero_cash_very_negative(self) -> None:
        ind = LiquidityReserveSignal(min_months=3.0, target_months=6.0)
        r = ind.compute(cash_reserve_months=0.0)
        assert r.signal_value < 0

    def test_signal_clamped(self) -> None:
        ind = LiquidityReserveSignal()
        r = ind.compute(cash_reserve_months=100.0)
        assert -1.0 <= r.signal_value <= 1.0

    def test_to_signal_name(self) -> None:
        ind = LiquidityReserveSignal()
        s = ind.to_signal(ind.compute(3.0))
        assert s.name == "custom.liquidity_reserve"
