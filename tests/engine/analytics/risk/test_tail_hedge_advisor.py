from __future__ import annotations

import pytest
from unittest.mock import patch

from engine.analytics.risk.tail_hedge_advisor import (
    TailHedgeAdvisor,
    HedgeRecommendation,
    FEATURE_FLAG,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def advisor() -> TailHedgeAdvisor:
    return TailHedgeAdvisor()


def _recommend_enabled(
    advisor: TailHedgeAdvisor,
    cvar: float = 0.20,
    vol_regime: str = "high",
    portfolio_value: float = 100_000.0,
    current_regime: str = "expansion",
) -> list[HedgeRecommendation]:
    with patch("engine.analytics.risk.tail_hedge_advisor.is_enabled", return_value=True):
        return advisor.recommend(
            cvar_blended_95=cvar,
            vol_regime=vol_regime,
            portfolio_value_usd=portfolio_value,
            current_regime=current_regime,
        )


# ---------------------------------------------------------------------------
# Feature flag disabled
# ---------------------------------------------------------------------------

class TestFeatureFlagDisabled:
    def test_disabled_returns_empty_list(self, advisor: TailHedgeAdvisor) -> None:
        with patch("engine.analytics.risk.tail_hedge_advisor.is_enabled", return_value=False):
            result = advisor.recommend(
                cvar_blended_95=0.25,
                vol_regime="high",
                portfolio_value_usd=100_000.0,
            )
        assert result == []

    def test_disabled_regardless_of_inputs(self, advisor: TailHedgeAdvisor) -> None:
        for vol_regime in ("calm", "normal", "high", "extreme"):
            for cvar in (0.05, 0.15, 0.30):
                with patch("engine.analytics.risk.tail_hedge_advisor.is_enabled", return_value=False):
                    result = advisor.recommend(
                        cvar_blended_95=cvar,
                        vol_regime=vol_regime,
                        portfolio_value_usd=50_000.0,
                    )
                assert result == []


# ---------------------------------------------------------------------------
# Feature flag enabled — high vol regime
# ---------------------------------------------------------------------------

class TestHighVolRegime:
    def test_high_vol_returns_non_empty(self, advisor: TailHedgeAdvisor) -> None:
        result = _recommend_enabled(advisor, cvar=0.20, vol_regime="high")
        assert len(result) > 0

    def test_extreme_vol_returns_non_empty(self, advisor: TailHedgeAdvisor) -> None:
        result = _recommend_enabled(advisor, cvar=0.20, vol_regime="extreme")
        assert len(result) > 0

    def test_high_vol_includes_spy_put(self, advisor: TailHedgeAdvisor) -> None:
        result = _recommend_enabled(advisor, cvar=0.20, vol_regime="high")
        instruments = [r.instrument for r in result]
        assert any("SPY put" in i for i in instruments)

    def test_high_vol_includes_vix_call(self, advisor: TailHedgeAdvisor) -> None:
        result = _recommend_enabled(advisor, cvar=0.20, vol_regime="high")
        instruments = [r.instrument for r in result]
        assert any("VIX" in i for i in instruments)

    def test_returns_list_of_hedge_recommendations(self, advisor: TailHedgeAdvisor) -> None:
        result = _recommend_enabled(advisor, cvar=0.20, vol_regime="high")
        for rec in result:
            assert isinstance(rec, HedgeRecommendation)

    def test_recommendation_fields_populated(self, advisor: TailHedgeAdvisor) -> None:
        result = _recommend_enabled(advisor, cvar=0.20, vol_regime="high")
        for rec in result:
            assert isinstance(rec.instrument, str) and len(rec.instrument) > 0
            assert isinstance(rec.rationale, str) and len(rec.rationale) > 0
            assert isinstance(rec.estimated_cost_pct, float)
            assert rec.estimated_cost_pct >= 0.0
            assert rec.protection_level in ("partial", "substantial", "full")
            assert isinstance(rec.regime_trigger, str)


# ---------------------------------------------------------------------------
# Feature flag enabled — calm/low CVaR
# ---------------------------------------------------------------------------

class TestCalmLowCVar:
    def test_calm_low_cvar_returns_empty(self, advisor: TailHedgeAdvisor) -> None:
        result = _recommend_enabled(advisor, cvar=0.05, vol_regime="calm")
        assert result == []

    def test_normal_low_cvar_returns_empty(self, advisor: TailHedgeAdvisor) -> None:
        result = _recommend_enabled(advisor, cvar=0.05, vol_regime="normal")
        assert result == []


# ---------------------------------------------------------------------------
# Contraction regime
# ---------------------------------------------------------------------------

class TestContractionRegime:
    def test_contraction_triggers_sh_recommendation(self, advisor: TailHedgeAdvisor) -> None:
        result = _recommend_enabled(
            advisor, cvar=0.05, vol_regime="calm", current_regime="contraction"
        )
        instruments = [r.instrument for r in result]
        assert any("SH" in i for i in instruments)

    def test_high_cvar_triggers_sh(self, advisor: TailHedgeAdvisor) -> None:
        result = _recommend_enabled(advisor, cvar=0.20, vol_regime="calm")
        instruments = [r.instrument for r in result]
        assert any("SH" in i for i in instruments)


# ---------------------------------------------------------------------------
# Normal regime + high CVaR
# ---------------------------------------------------------------------------

class TestNormalRegimeHighCVar:
    def test_normal_regime_high_cvar_suggests_collar(self, advisor: TailHedgeAdvisor) -> None:
        result = _recommend_enabled(advisor, cvar=0.20, vol_regime="normal")
        instruments = [r.instrument for r in result]
        assert any("collar" in i.lower() for i in instruments)


# ---------------------------------------------------------------------------
# CVAR_THRESHOLD constant
# ---------------------------------------------------------------------------

class TestCvarThreshold:
    def test_cvar_threshold_is_015(self) -> None:
        assert TailHedgeAdvisor.CVAR_THRESHOLD == 0.15
