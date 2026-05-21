"""Tests H1 Market Health Matrix — data loaders e cell builders."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from presentation.dashboard_engine.pages_v2.H1_Market_Health_Matrix import (
    HealthCell,
    HealthMatrixData,
    _cape_cell,
    _degraded_matrix,
    _earnings_cell,
    _f,
    _health_label,
    _hy_oas_cell,
    _iv_skew_cell,
    _labour_cell,
    _load_composite,
    _load_credit,
    _load_options_flow,
    _load_upcoming_earnings,
    _load_valuation,
    _load_vix,
    _load_yield_curve,
    _macro_conviction_cell,
    _pcr_cell,
    _sentiment_cell,
    _ted_spread_cell,
    _to_health_score,
    _vix_cell,
    _vol_surface_cell,
    _yield_curve_cell,
    _yield_curve_color,
    load_health_matrix,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _mock_db(query_result=None):
    db = MagicMock()
    db.query.return_value = query_result or []
    return db


# ─── load_health_matrix ───────────────────────────────────────────────────────

class TestLoadHealthMatrix:
    def test_returns_health_matrix_data(self):
        with patch(
            "shared.db.duckdb_client.get_duckdb_client",
            return_value=_mock_db(),
        ):
            result = load_health_matrix()
        assert isinstance(result, HealthMatrixData)

    def test_degraded_on_db_error(self):
        with patch(
            "shared.db.duckdb_client.get_duckdb_client",
            side_effect=RuntimeError("no db"),
        ):
            result = load_health_matrix()
        assert result.is_degraded

    def test_categories_present_when_db_ok(self):
        with patch(
            "shared.db.duckdb_client.get_duckdb_client",
            return_value=_mock_db(),
        ):
            result = load_health_matrix()
        assert len(result.categories) > 0

    def test_health_score_in_range(self):
        with patch(
            "shared.db.duckdb_client.get_duckdb_client",
            return_value=_mock_db(),
        ):
            result = load_health_matrix()
        assert 0 <= result.health_score <= 100


# ─── _load_composite ──────────────────────────────────────────────────────────

class TestLoadComposite:
    def test_returns_none_when_no_rows(self):
        db = _mock_db([])
        assert _load_composite(db) is None

    def test_returns_dict_with_score(self):
        db = _mock_db([(0.45, 0.2, 0.1, "BUY", "HIGH", "bull", "expansion", "normal")])
        result = _load_composite(db)
        assert result is not None
        assert result["composite_score"] == pytest.approx(0.45)
        assert result["action"] == "BUY"

    def test_returns_none_on_exception(self):
        db = MagicMock()
        db.query.side_effect = Exception("DB error")
        assert _load_composite(db) is None


class TestLoadYieldCurve:
    def test_returns_none_when_no_rows(self):
        assert _load_yield_curve(_mock_db([])) is None

    def test_returns_dict(self):
        db = _mock_db([(25.0, "normal", 0.12)])
        result = _load_yield_curve(db)
        assert result["spread"] == pytest.approx(25.0)
        assert result["regime"] == "normal"

    def test_returns_none_on_exception(self):
        db = MagicMock()
        db.query.side_effect = Exception("fail")
        assert _load_yield_curve(db) is None


class TestLoadCredit:
    def test_returns_none_when_no_rows(self):
        assert _load_credit(_mock_db([])) is None

    def test_returns_dict_with_hy_oas(self):
        db = _mock_db([(380.0, 35.0, "moderate", -0.3)])
        result = _load_credit(db)
        assert result["hy_oas"] == pytest.approx(380.0)
        assert result["stress_level"] == "moderate"

    def test_returns_none_on_exception(self):
        db = MagicMock()
        db.query.side_effect = Exception("fail")
        assert _load_credit(db) is None


class TestLoadVix:
    def test_returns_none_when_no_rows(self):
        assert _load_vix(_mock_db([])) is None

    def test_returns_dict(self):
        db = _mock_db([(16.5, 0.3, "elevated")])
        result = _load_vix(db)
        assert result["level"] == pytest.approx(16.5)
        assert result["regime"] == "elevated"

    def test_returns_none_on_exception(self):
        db = MagicMock()
        db.query.side_effect = Exception("fail")
        assert _load_vix(db) is None


class TestLoadValuation:
    def test_returns_none_when_empty(self):
        assert _load_valuation(_mock_db([])) is None

    def test_returns_cape(self):
        db = _mock_db([(33.5, 1.2, 22.0)])
        r = _load_valuation(db)
        assert r["cape"] == pytest.approx(33.5)

    def test_returns_none_on_exception(self):
        db = MagicMock()
        db.query.side_effect = Exception("fail")
        assert _load_valuation(db) is None


class TestLoadUpcomingEarnings:
    def test_returns_empty_list_when_no_rows(self):
        result = _load_upcoming_earnings(_mock_db([]))
        assert result == []

    def test_returns_list_of_dicts(self):
        from datetime import date
        db = _mock_db([("AAPL", "Apple Inc", date(2026, 5, 22), "AMC", 1.5)])
        result = _load_upcoming_earnings(db)
        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"

    def test_returns_empty_on_exception(self):
        db = MagicMock()
        db.query.side_effect = Exception("fail")
        assert _load_upcoming_earnings(db) == []


class TestLoadOptionsFlow:
    def test_returns_none_when_empty(self):
        assert _load_options_flow(_mock_db([])) is None

    def test_returns_dict_with_pcr(self):
        db = _mock_db([(0.87, 0.03, 0.17)])
        r = _load_options_flow(db)
        assert r["pcr"] == pytest.approx(0.87)

    def test_returns_none_on_exception(self):
        db = MagicMock()
        db.query.side_effect = Exception("fail")
        assert _load_options_flow(db) is None


# ─── Cell builders ────────────────────────────────────────────────────────────

class TestYieldCurveCell:
    def test_none_data_returns_gray(self):
        cell = _yield_curve_cell(None)
        assert cell.color == "gray"

    def test_normal_regime_is_green(self):
        cell = _yield_curve_cell({"spread": 25.0, "regime": "normal", "recession_prob": 0.1})
        assert cell.color == "green"

    def test_inverted_regime_is_red(self):
        cell = _yield_curve_cell({"spread": -20.0, "regime": "inverted", "recession_prob": 0.45})
        assert cell.color == "red"

    def test_flat_regime_is_yellow(self):
        cell = _yield_curve_cell({"spread": 5.0, "regime": "flat", "recession_prob": 0.2})
        assert cell.color == "yellow"

    def test_value_str_shows_regime(self):
        cell = _yield_curve_cell({"spread": 30.0, "regime": "steep", "recession_prob": 0.05})
        assert "STEEP" in cell.value_str


class TestVixCell:
    def test_none_data_returns_gray(self):
        assert _vix_cell(None).color == "gray"

    def test_low_vix_is_green(self):
        cell = _vix_cell({"level": 14.0, "zscore": -0.5, "regime": "calm"})
        assert cell.color == "green"

    def test_high_vix_is_red(self):
        cell = _vix_cell({"level": 30.0, "zscore": 1.8, "regime": "high_stress"})
        assert cell.color == "red"

    def test_medium_vix_is_yellow(self):
        cell = _vix_cell({"level": 20.0, "zscore": 0.5, "regime": "elevated"})
        assert cell.color == "yellow"

    def test_value_str_contains_level(self):
        cell = _vix_cell({"level": 18.5, "zscore": 0.3, "regime": "elevated"})
        assert "18.5" in cell.value_str


class TestHyOasCell:
    def test_none_data_returns_gray(self):
        assert _hy_oas_cell(None).color == "gray"

    def test_low_oas_is_green(self):
        cell = _hy_oas_cell({"hy_oas": 350.0, "ted_spread": 30.0, "stress_level": "low", "stress_score": 0.2})
        assert cell.color == "green"

    def test_high_oas_is_red(self):
        cell = _hy_oas_cell({"hy_oas": 600.0, "ted_spread": 80.0, "stress_level": "elevated", "stress_score": -0.5})
        assert cell.color == "red"

    def test_none_hy_returns_gray(self):
        cell = _hy_oas_cell({"hy_oas": None, "stress_level": "low"})
        assert cell.color == "gray"


class TestTedSpreadCell:
    def test_none_data_returns_gray(self):
        assert _ted_spread_cell(None).color == "gray"

    def test_low_ted_is_green(self):
        cell = _ted_spread_cell({"ted_spread": 30.0, "stress_level": "low"})
        assert cell.color == "green"

    def test_high_ted_is_red(self):
        cell = _ted_spread_cell({"ted_spread": 150.0, "stress_level": "elevated"})
        assert cell.color == "red"


class TestMacroConvictionCell:
    def test_none_data_returns_gray(self):
        assert _macro_conviction_cell(None).color == "gray"

    def test_positive_score_is_green(self):
        cell = _macro_conviction_cell({"macro_component": 0.35, "action": "BUY"})
        assert cell.color == "green"

    def test_negative_score_is_red(self):
        cell = _macro_conviction_cell({"macro_component": -0.3, "action": "REDUCE"})
        assert cell.color == "red"

    def test_near_zero_is_yellow(self):
        cell = _macro_conviction_cell({"macro_component": 0.05, "action": "HOLD"})
        assert cell.color == "yellow"


class TestSentimentCell:
    def test_none_data_returns_gray(self):
        assert _sentiment_cell(None).color == "gray"

    def test_extreme_greed_is_red(self):
        cell = _sentiment_cell({"cnn_fg": 0.80})
        assert cell.color == "red"
        assert "GREED" in cell.regime_label

    def test_extreme_fear_is_green(self):
        cell = _sentiment_cell({"cnn_fg": 0.15})
        assert cell.color == "green"

    def test_normalized_score(self):
        # Score <= 1.0 viene convertito in percentuale
        cell = _sentiment_cell({"cnn_fg": 0.62})
        assert "62" in cell.value_str


class TestCapeCell:
    def test_none_data_returns_gray(self):
        assert _cape_cell(None).color == "gray"

    def test_low_cape_is_green(self):
        cell = _cape_cell({"cape": 20.0, "cape_zscore": -0.5, "pe_trailing": 18.0})
        assert cell.color == "green"
        assert "CHEAP" in cell.regime_label

    def test_high_cape_is_red(self):
        cell = _cape_cell({"cape": 38.0, "cape_zscore": 2.1, "pe_trailing": 30.0})
        assert cell.color == "red"
        assert "EXPENSIVE" in cell.regime_label

    def test_none_cape_value_returns_gray(self):
        cell = _cape_cell({"cape": None})
        assert cell.color == "gray"


class TestEarningsCell:
    def test_empty_list_returns_gray(self):
        assert _earnings_cell([]).color == "gray"

    def test_with_earnings_returns_yellow(self):
        from datetime import date
        cell = _earnings_cell([
            {"ticker": "AAPL", "company_name": "Apple", "report_date": date(2026, 5, 22),
             "report_time": "AMC", "eps_estimate": 1.5}
        ])
        assert cell.color == "yellow"
        assert "AAPL" in cell.regime_label

    def test_count_in_value_str(self):
        from datetime import date
        items = [
            {"ticker": f"T{i}", "company_name": None, "report_date": date(2026, 5, 22),
             "report_time": None, "eps_estimate": None}
            for i in range(3)
        ]
        cell = _earnings_cell(items)
        assert "3" in cell.value_str


class TestPcrCell:
    def test_none_returns_gray(self):
        assert _pcr_cell(None).color == "gray"

    def test_neutral_pcr_is_green(self):
        cell = _pcr_cell({"pcr": 0.85, "iv_skew": 0.02})
        assert cell.color == "green"

    def test_high_pcr_is_red(self):
        cell = _pcr_cell({"pcr": 1.6, "iv_skew": 0.05})
        assert cell.color == "red"
        assert "BEARISH" in cell.regime_label

    def test_none_pcr_returns_gray(self):
        assert _pcr_cell({"pcr": None}).color == "gray"


class TestIvSkewCell:
    def test_none_returns_gray(self):
        assert _iv_skew_cell(None).color == "gray"

    def test_large_put_skew_is_red(self):
        cell = _iv_skew_cell({"iv_skew": 0.07, "iv_atm": 0.18})
        assert cell.color == "red"
        assert "PUT PREMIUM" in cell.regime_label

    def test_normal_skew_is_green(self):
        cell = _iv_skew_cell({"iv_skew": 0.01, "iv_atm": 0.17})
        assert cell.color == "green"

    def test_none_skew_returns_gray(self):
        assert _iv_skew_cell({"iv_skew": None}).color == "gray"


# ─── Helpers ──────────────────────────────────────────────────────────────────

class TestToHealthScore:
    @pytest.mark.parametrize("score,expected", [
        (1.0,  100),
        (-1.0, 0),
        (0.0,  50),
        (0.4,  70),
        (-0.4, 30),
    ])
    def test_conversion(self, score, expected):
        assert _to_health_score(score) == expected

    def test_clamped_to_0_100(self):
        assert _to_health_score(2.0)  == 100
        assert _to_health_score(-2.0) == 0


class TestHealthLabel:
    @pytest.mark.parametrize("score,expected_fragment", [
        (80, "RIALZISTA"),
        (60, "RIALZISTA"),
        (50, "NEUTRO"),
        (35, "RIBASSISTA"),
        (10, "RIBASSISTA"),
    ])
    def test_label(self, score, expected_fragment):
        assert expected_fragment in _health_label(score)


class TestYieldCurveColor:
    def test_normal_is_green(self):
        assert _yield_curve_color("NORMAL") == "green"

    def test_steep_is_green(self):
        assert _yield_curve_color("STEEP") == "green"

    def test_flat_is_yellow(self):
        assert _yield_curve_color("FLAT") == "yellow"

    def test_inverted_is_red(self):
        assert _yield_curve_color("INVERTED") == "red"


class TestDegradedMatrix:
    def test_is_degraded(self):
        d = _degraded_matrix()
        assert d.is_degraded
        assert d.health_score == 50


class TestF:
    def test_valid_float(self):
        assert _f(1.5) == 1.5

    def test_none_returns_none(self):
        assert _f(None) is None

    def test_nan_returns_none(self):
        import math
        assert _f(math.nan) is None

    def test_string_float(self):
        assert _f("3.14") == pytest.approx(3.14)

    def test_invalid_string_returns_none(self):
        assert _f("N/D") is None
