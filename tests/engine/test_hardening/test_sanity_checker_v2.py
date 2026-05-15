"""Tests per engine.market_data.sanity_checker — SanityCheckerV2."""
from __future__ import annotations

import pytest

from engine.market_data.sanity_checker import SanityCheckerV2, SanityResult


@pytest.fixture
def checker() -> SanityCheckerV2:
    return SanityCheckerV2()


class TestCheckVix:
    def test_normal_vix_is_ok(self, checker) -> None:
        r = checker.check_vix(18.5)
        assert r.level == "OK"
        assert r.passed is True
        assert r.value == pytest.approx(18.5)

    def test_vix_zero_is_critical(self, checker) -> None:
        r = checker.check_vix(0.0)
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_vix_negative_is_critical(self, checker) -> None:
        r = checker.check_vix(-1.0)
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_vix_above_50_is_warn(self, checker) -> None:
        r = checker.check_vix(55.0)
        assert r.level == "WARN"
        assert r.passed is True  # WARN non blocca

    def test_vix_80_still_warn(self, checker) -> None:
        r = checker.check_vix(80.0)
        assert r.level == "WARN"

    def test_vix_above_100_is_critical(self, checker) -> None:
        r = checker.check_vix(101.0)
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_vix_exactly_50_is_ok(self, checker) -> None:
        r = checker.check_vix(50.0)
        assert r.level == "OK"

    def test_rule_name_correct(self, checker) -> None:
        r = checker.check_vix(20.0)
        assert r.rule == "vix_range_check"


class TestCheckRollYield:
    def test_normal_roll_ok(self, checker) -> None:
        r = checker.check_roll_yield(0.05, "CL=F")
        assert r.level == "OK"
        assert r.passed is True

    def test_high_roll_warn(self, checker) -> None:
        r = checker.check_roll_yield(0.20, "NG=F")
        assert r.level == "WARN"
        assert r.passed is True

    def test_negative_high_roll_warn(self, checker) -> None:
        r = checker.check_roll_yield(-0.20, "NG=F")
        assert r.level == "WARN"

    def test_over_100pct_roll_critical(self, checker) -> None:
        r = checker.check_roll_yield(1.5, "CL=F")
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_negative_over_100pct_critical(self, checker) -> None:
        r = checker.check_roll_yield(-1.5, "CL=F")
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_rule_name(self, checker) -> None:
        r = checker.check_roll_yield(0.01, "ES=F")
        assert r.rule == "roll_yield_range_check"

    def test_ticker_in_message(self, checker) -> None:
        r = checker.check_roll_yield(0.01, "MY_TICKER")
        assert "MY_TICKER" in r.message


class TestCheckFuturesSpotDiscrepancy:
    def test_small_discrepancy_ok(self, checker) -> None:
        r = checker.check_futures_spot_discrepancy(
            futures_price=100.5, spot_price=100.0,
            futures_ticker="ES=F", spot_ticker="SPY",
        )
        assert r.level == "OK"
        assert r.passed is True

    def test_large_discrepancy_warn(self, checker) -> None:
        r = checker.check_futures_spot_discrepancy(
            futures_price=110.0, spot_price=100.0,
            futures_ticker="ES=F", spot_ticker="SPY",
        )
        assert r.level == "WARN"

    def test_spot_zero_warns(self, checker) -> None:
        r = checker.check_futures_spot_discrepancy(
            futures_price=100.0, spot_price=0.0,
            futures_ticker="ES=F", spot_ticker="SPY",
        )
        assert r.level == "WARN"
        assert r.passed is False

    def test_custom_threshold(self, checker) -> None:
        r = checker.check_futures_spot_discrepancy(
            futures_price=107.0, spot_price=100.0,
            futures_ticker="CL=F", spot_ticker="USO",
            threshold_pct=10.0,
        )
        assert r.level == "OK"

    def test_rule_name(self, checker) -> None:
        r = checker.check_futures_spot_discrepancy(100.0, 100.0, "A", "B")
        assert r.rule == "futures_spot_discrepancy_check"


class TestCheckYieldSpread:
    def test_normal_spread_ok(self, checker) -> None:
        r = checker.check_yield_spread(1.5)
        assert r.level == "OK"
        assert r.passed is True

    def test_inverted_spread_ok(self, checker) -> None:
        r = checker.check_yield_spread(-0.5)
        assert r.level == "OK"

    def test_extreme_spread_critical(self, checker) -> None:
        r = checker.check_yield_spread(20.0)
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_extreme_negative_critical(self, checker) -> None:
        r = checker.check_yield_spread(-20.0)
        assert r.level == "CRITICAL"
        assert r.passed is False

    def test_rule_name(self, checker) -> None:
        r = checker.check_yield_spread(1.0)
        assert r.rule == "yield_spread_range_check"


class TestRunAll:
    def test_empty_dict_returns_empty_list(self, checker) -> None:
        results = checker.run_all({})
        assert results == []

    def test_vix_only(self, checker) -> None:
        results = checker.run_all({"vix": 20.0})
        assert len(results) == 1
        assert results[0].rule == "vix_range_check"

    def test_all_keys_present(self, checker) -> None:
        results = checker.run_all({
            "vix": 20.0,
            "roll_yield_clf": 0.05,
            "spread_10y_2y": 1.0,
        })
        assert len(results) == 3

    def test_unknown_keys_ignored(self, checker) -> None:
        results = checker.run_all({"unknown_key": 99.9})
        assert results == []

    def test_string_values_coerced_to_float(self, checker) -> None:
        results = checker.run_all({"vix": "18.5"})
        assert len(results) == 1


class TestHasCritical:
    def test_no_critical(self, checker) -> None:
        results = [
            SanityResult(passed=True, level="OK", rule="r", message="m"),
            SanityResult(passed=True, level="WARN", rule="r", message="m"),
        ]
        assert SanityCheckerV2.has_critical(results) is False

    def test_with_critical(self, checker) -> None:
        results = [
            SanityResult(passed=True, level="OK", rule="r", message="m"),
            SanityResult(passed=False, level="CRITICAL", rule="r", message="m"),
        ]
        assert SanityCheckerV2.has_critical(results) is True

    def test_empty_list(self, checker) -> None:
        assert SanityCheckerV2.has_critical([]) is False


class TestSanityResult:
    def test_frozen(self) -> None:
        r = SanityResult(passed=True, level="OK", rule="r", message="m")
        with pytest.raises((AttributeError, TypeError)):
            r.passed = False  # type: ignore[misc]

    def test_value_optional(self) -> None:
        r = SanityResult(passed=True, level="OK", rule="r", message="m")
        assert r.value is None

    def test_value_stored(self) -> None:
        r = SanityResult(passed=True, level="OK", rule="r", message="m", value=42.0)
        assert r.value == pytest.approx(42.0)
