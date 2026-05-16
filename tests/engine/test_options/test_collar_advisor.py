"""Tests for CollarAdvisor — DoD: collar suggestion in P2 if portfolio_beta > 1.3."""
from __future__ import annotations

import pytest

from engine.options.collar_advisor import CollarAdvisor, CollarSuggestion

_ADVISOR = CollarAdvisor()


class TestCollarNotSuggested:
    def test_beta_below_threshold(self):
        r = _ADVISOR.evaluate(portfolio_beta=0.80, spot=100.0, iv=0.20, t_years=0.25)
        assert not r.suggested

    def test_beta_exactly_at_threshold(self):
        r = _ADVISOR.evaluate(portfolio_beta=1.30, spot=100.0, iv=0.20, t_years=0.25)
        assert not r.suggested    # threshold is strict >

    def test_no_strategy_when_not_suggested(self):
        r = _ADVISOR.evaluate(portfolio_beta=1.0, spot=100.0, iv=0.20, t_years=0.25)
        assert r.strategy is None

    def test_reason_contains_beta(self):
        r = _ADVISOR.evaluate(portfolio_beta=0.90, spot=100.0, iv=0.20, t_years=0.25)
        assert "0.90" in r.reason or "0.9" in r.reason


class TestCollarSuggested:
    def test_beta_above_threshold(self):
        r = _ADVISOR.evaluate(portfolio_beta=1.45, spot=100.0, iv=0.20, t_years=0.25)
        assert r.suggested

    def test_strategy_present_when_suggested(self):
        r = _ADVISOR.evaluate(portfolio_beta=1.50, spot=100.0, iv=0.20, t_years=0.25)
        assert r.strategy is not None
        assert r.strategy.strategy_name == "collar"

    def test_k_put_below_spot(self):
        r = _ADVISOR.evaluate(portfolio_beta=1.50, spot=100.0, iv=0.20, t_years=0.25)
        assert r.k_put < r.spot

    def test_k_call_above_spot(self):
        r = _ADVISOR.evaluate(portfolio_beta=1.50, spot=100.0, iv=0.20, t_years=0.25)
        assert r.k_call > r.spot

    def test_reason_contains_beta(self):
        r = _ADVISOR.evaluate(portfolio_beta=1.80, spot=100.0, iv=0.20, t_years=0.25)
        assert "1.80" in r.reason or "1.8" in r.reason

    def test_reason_contains_floor_and_cap(self):
        r = _ADVISOR.evaluate(portfolio_beta=1.50, spot=100.0, iv=0.20, t_years=0.25)
        assert "Floor" in r.reason or "floor" in r.reason.lower()


class TestCollarAdvisorCustomThreshold:
    def test_custom_threshold(self):
        advisor = CollarAdvisor(beta_threshold=1.0)
        r = _ADVISOR.evaluate(portfolio_beta=1.10, spot=100.0, iv=0.20, t_years=0.25)
        # With default threshold 1.3, beta 1.10 is NOT suggested
        assert not r.suggested

    def test_custom_threshold_triggers(self):
        advisor = CollarAdvisor(beta_threshold=1.0)
        r = advisor.evaluate(portfolio_beta=1.10, spot=100.0, iv=0.20, t_years=0.25)
        assert r.suggested

    def test_custom_offsets(self):
        advisor = CollarAdvisor(put_offset=0.10, call_offset=0.10)
        r = advisor.evaluate(portfolio_beta=1.50, spot=100.0, iv=0.20, t_years=0.25)
        assert r.k_put == pytest.approx(90.0, rel=0.01)
        assert r.k_call == pytest.approx(110.0, rel=0.01)


class TestCollarSuggestionFrozen:
    def test_frozen(self):
        r = _ADVISOR.evaluate(portfolio_beta=1.50, spot=100.0, iv=0.20, t_years=0.25)
        with pytest.raises(Exception):
            r.suggested = False  # type: ignore[misc]


class TestMockBeta:
    """Test con mock: valori beta tipici del portafoglio utente."""

    @pytest.mark.parametrize("beta,should_suggest", [
        (0.50, False),
        (0.82, False),    # default demo beta in P2
        (1.00, False),
        (1.30, False),    # exactly at threshold → no
        (1.31, True),     # just above → yes
        (1.50, True),
        (2.00, True),
    ])
    def test_beta_thresholds(self, beta, should_suggest):
        r = _ADVISOR.evaluate(portfolio_beta=beta, spot=500.0, iv=0.18, t_years=0.25)
        assert r.suggested == should_suggest, (
            f"beta={beta}: expected suggested={should_suggest}, got {r.suggested}"
        )
