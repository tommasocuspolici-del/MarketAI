"""Smoke tests for Phase 7 — verifies all pages and components import OK
and exercise their pure ``build_*`` functions with mock data.

These tests do NOT require Streamlit installed (Streamlit-dependent code
paths are wrapped in try/except and skipped). They validate:
  · All 23 pages import without errors
  · All 18 components import without errors
  · Each component's pure function (build_xxx) returns the expected type
  · Page bodies are callable with DESIGN_TOKENS
"""
from __future__ import annotations

import importlib

import pytest

from presentation.ui.theme import load_design_tokens

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════
ENGINE_PAGES: list[str] = [
    "E1_Market_Overview", "E2_Equities", "E3_Bonds", "E4_Commodities",
    "E5_Forex_Options", "E6_Macro", "E7_Sentiment", "E8_Correlations",
    "E9_Forecasting", "E10_Delta_Tracker", "E11_Analysis_Pipeline",
    "E12_Backtesting", "E13_Stress_Test", "E14_Alerts",
]

PERSONAL_PAGES: list[str] = [
    "P1_Overview_Patrimonio", "P2_Portafoglio_eToro", "P3_Cash_Flow",
    "P4_Net_Worth", "P5_Goals", "P6_Profilo_Investitore",
    "P7_Scenari_Ricchezza", "P8_Fiscale", "P9_Alerts_Personali",
]

COMPONENTS: list[str] = [
    "kpi_card", "health_status_bar", "data_quality_badge",
    "latency_indicator", "regime_badge", "candlestick_pro",
    "sentiment_radar", "pipeline_stepper",
    "correlation_network", "profile_card", "goal_tracker",
    "net_worth_chart", "cash_flow_waterfall", "wealth_scenario_chart",
    "backtest_report", "stress_test_viewer",
]


@pytest.fixture
def tokens():  # type: ignore[no-untyped-def]
    """Load DESIGN_TOKENS once per test."""
    load_design_tokens.cache_clear()
    return load_design_tokens()


# ═══════════════════════════════════════════════════════════════════════════
# Theme + Layout
# ═══════════════════════════════════════════════════════════════════════════
class TestTheme:
    def test_load_design_tokens(self, tokens) -> None:  # type: ignore[no-untyped-def]
        assert tokens.colors.bg_primary.startswith("#")
        assert len(tokens.colors.bg_primary) == 7   # hex color

    def test_color_helpers(self, tokens) -> None:  # type: ignore[no-untyped-def]
        # Test for_pnl
        assert tokens.colors.for_pnl(1.0) == tokens.colors.positive
        assert tokens.colors.for_pnl(-1.0) == tokens.colors.negative
        assert tokens.colors.for_pnl(0.0) == tokens.colors.neutral

    def test_quality_score_colors(self, tokens) -> None:  # type: ignore[no-untyped-def]
        assert tokens.colors.for_quality_score(0.95) == tokens.colors.quality_excellent
        assert tokens.colors.for_quality_score(0.75) == tokens.colors.quality_good
        assert tokens.colors.for_quality_score(0.55) == tokens.colors.quality_fair
        assert tokens.colors.for_quality_score(0.30) == tokens.colors.quality_poor

    def test_regime_colors(self, tokens) -> None:  # type: ignore[no-untyped-def]
        for regime in ("bull", "bear", "transition", "stress"):
            color = tokens.colors.for_regime(regime)
            assert color.startswith("#")


class TestLayout:
    def test_build_custom_css(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.ui.layout import build_custom_css
        css = build_custom_css(tokens)
        assert "<style>" in css
        assert tokens.colors.bg_primary in css
        assert tokens.colors.text_primary in css

    def test_setup_page_no_streamlit(self, tokens) -> None:  # type: ignore[no-untyped-def]
        """Without Streamlit installed, setup_page just returns tokens."""
        from presentation.ui.layout import setup_page
        result = setup_page(title="Test", icon="🧪", require_auth_gate=False)
        assert result.colors.bg_primary == tokens.colors.bg_primary


# ═══════════════════════════════════════════════════════════════════════════
# Components — import + smoke
# ═══════════════════════════════════════════════════════════════════════════
class TestComponentsImport:
    @pytest.mark.parametrize("component_name", COMPONENTS)
    def test_component_imports(self, component_name: str) -> None:
        module = importlib.import_module(
            f"presentation.ui.components.{component_name}"
        )
        # Ogni componente DEVE esporre __version__ e __all__
        assert hasattr(module, "__version__")
        assert hasattr(module, "__all__")


class TestComponentBuilders:
    """Pure ``build_*`` functions for each component (Streamlit not needed)."""

    def test_kpi_card_html(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.ui.components.kpi_card import _build_kpi_html
        html = _build_kpi_html(tokens, "Label", "100.00")
        assert "Label" in html
        assert "100.00" in html

    def test_health_status_bar_html(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.ui.components.health_status_bar import build_health_html
        from presentation.ui.page_factory import build_mock_health
        health = build_mock_health()
        html = build_health_html(tokens, health)
        assert "OPERATIONAL" in html

    def test_quality_badge_html(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.ui.components.data_quality_badge import build_quality_badge_html
        html = build_quality_badge_html(tokens, 0.85)
        assert "GOOD" in html

    def test_latency_indicator_html(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from datetime import timedelta

        from presentation.ui.components.latency_indicator import build_latency_html
        from shared.types import now_utc
        html = build_latency_html(tokens, "TestSrc", now_utc() - timedelta(seconds=30))
        assert "TestSrc" in html
        assert "s ago" in html

    def test_regime_badge_html(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.ui.components.regime_badge import build_regime_html
        html = build_regime_html(tokens, "bull")
        assert "BULL" in html

    def test_candlestick_figure(self, tokens) -> None:  # type: ignore[no-untyped-def]
        # v7.2 (fix B2): build_mock_ohlcv vive in tests/fixtures/, non in E2_Equities
        from tests.fixtures import build_mock_ohlcv
        from presentation.ui.components.candlestick_pro import build_candlestick_figure
        ohlcv = build_mock_ohlcv(50)
        fig = build_candlestick_figure(tokens, ohlcv, title="Test")
        # Plotly Figure has .data attribute
        assert hasattr(fig, "data")

    def test_sentiment_radar_figure(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.ui.components.sentiment_radar import build_sentiment_radar_figure
        fig = build_sentiment_radar_figure(tokens, {"A": 0.5, "B": -0.2, "C": 0.1})
        assert hasattr(fig, "data")

    def test_correlation_network_figure(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.dashboard_engine.pages.E8_Correlations import (
            build_mock_correlation_matrix,
        )
        from presentation.ui.components.correlation_network import (
            build_correlation_network_figure,
        )
        matrix = build_mock_correlation_matrix()
        fig = build_correlation_network_figure(tokens, matrix, threshold=0.3)
        assert hasattr(fig, "data")

    def test_profile_card_html(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from personal.investor_profile import (
            InvestmentHorizon,
            InvestorProfile,
            RiskTolerance,
        )
        from presentation.ui.components.profile_card import build_profile_card_html
        profile = InvestorProfile(
            profile_id="p", name="Test User",
            risk_tolerance=RiskTolerance.MODERATE, max_drawdown_pct=0.20,
            investment_horizon=InvestmentHorizon.LONG, horizon_years=15,
            liquidity_reserve_months=6, financial_knowledge=3,
        )
        html = build_profile_card_html(tokens, profile)
        assert "Test User" in html
        assert "MODERATE" in html

    def test_goal_tracker_html(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from datetime import date, timedelta

        from personal.goals import Goal
        from presentation.ui.components.goal_tracker import build_goal_tracker_html
        goal = Goal(
            profile_id="p", name="Casa",
            target_amount=50_000, current_amount=15_000,
            target_date=date.today() + timedelta(days=365 * 3),
        )
        html = build_goal_tracker_html(tokens, goal)
        assert "Casa" in html
        assert "30" in html  # 15k/50k = 30%

    def test_net_worth_figure(self, tokens) -> None:  # type: ignore[no-untyped-def]
        # v7.2 (fix B2): _build_mock_snapshots vive in tests/fixtures/
        from tests.fixtures import build_mock_snapshots as _build_mock_snapshots
        from presentation.ui.components.net_worth_chart import build_net_worth_figure
        snapshots = _build_mock_snapshots()
        fig = build_net_worth_figure(tokens, snapshots)
        assert hasattr(fig, "data")

    def test_waterfall_figure(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.ui.components.cash_flow_waterfall import build_waterfall_figure
        fig = build_waterfall_figure(
            tokens,
            categories=["A", "B", "Net"],
            amounts=[100, -30, 70],
        )
        assert hasattr(fig, "data")

    def test_waterfall_length_mismatch_raises(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.ui.components.cash_flow_waterfall import build_waterfall_figure
        with pytest.raises(ValueError, match="same length"):
            build_waterfall_figure(tokens, categories=["A"], amounts=[1, 2])

    def test_wealth_fan_figure(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from personal.wealth_scenarios import WealthSimulator
        from presentation.ui.components.wealth_scenario_chart import (
            build_wealth_fan_figure,
        )
        sim = WealthSimulator()
        result = sim.simulate(
            initial_wealth=10_000, monthly_savings=500,
            annual_return_mean=0.07, annual_return_std=0.15,
            years=5, n_simulations=500, seed=42,
        )
        fig = build_wealth_fan_figure(tokens, result)
        assert hasattr(fig, "data")

    def test_backtest_report_metrics(self, tokens) -> None:  # type: ignore[no-untyped-def]
        # v7.2 (fix B2): build_mock_backtest_result vive in tests/fixtures/
        from tests.fixtures import build_mock_backtest_result as build_mock_backtest
        from presentation.ui.components.backtest_report import (
            build_drawdown_figure,
            build_equity_curve_figure,
            build_metrics_table,
        )
        result = build_mock_backtest()
        eq_fig = build_equity_curve_figure(tokens, result)
        dd_fig = build_drawdown_figure(tokens, result)
        table = build_metrics_table(result)
        assert hasattr(eq_fig, "data")
        assert hasattr(dd_fig, "data")
        assert "Sharpe Ratio" in table["Metric"].values

    def test_stress_test_viewer(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.dashboard_engine.pages.E13_Stress_Test import (
            build_mock_stress_report,
        )
        from presentation.ui.components.stress_test_viewer import (
            build_impact_chart,
            build_scenario_table,
        )
        report = build_mock_stress_report()
        chart = build_impact_chart(tokens, report)
        table = build_scenario_table(report)
        assert hasattr(chart, "data")
        assert len(table) == report.n_scenarios

    def test_pipeline_stepper_dataclass(self) -> None:
        from presentation.ui.components.pipeline_stepper import PipelineStep
        step = PipelineStep(name="Fetch", status="success", duration_ms=120.0)
        assert step.name == "Fetch"
        assert step.duration_ms == 120.0


# ═══════════════════════════════════════════════════════════════════════════
# Pages — import smoke
# ═══════════════════════════════════════════════════════════════════════════
class TestEnginePagesImport:
    @pytest.mark.parametrize("page_name", ENGINE_PAGES)
    def test_engine_page_imports(self, page_name: str) -> None:
        module = importlib.import_module(
            f"presentation.dashboard_engine.pages.{page_name}"
        )
        # Ogni pagina espone __all__ con almeno una body_* function
        assert hasattr(module, "__all__")
        body_fns = [name for name in module.__all__ if name.startswith("body_")]
        assert len(body_fns) >= 1, f"page {page_name} has no body_* function"


class TestPersonalPagesImport:
    @pytest.mark.parametrize("page_name", PERSONAL_PAGES)
    def test_personal_page_imports(self, page_name: str) -> None:
        module = importlib.import_module(
            f"presentation.dashboard_personal.pages.{page_name}"
        )
        assert hasattr(module, "__all__")
        body_fns = [name for name in module.__all__ if name.startswith("body_")]
        assert len(body_fns) >= 1


class TestAppEntryPoints:
    def test_engine_app_imports(self) -> None:
        module = importlib.import_module("presentation.dashboard_engine.app")
        assert hasattr(module, "main")

    def test_personal_app_imports(self) -> None:
        module = importlib.import_module("presentation.dashboard_personal.app")
        assert hasattr(module, "main")


# ═══════════════════════════════════════════════════════════════════════════
# Page bodies — actually call them with mock tokens (no Streamlit → no-op)
# ═══════════════════════════════════════════════════════════════════════════
class TestPageBodiesCallable:
    """Each body_*(tokens) must execute without errors when Streamlit
    is not installed (returns None silently)."""

    def test_e1_market_overview_body(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.dashboard_engine.pages.E1_Market_Overview import (
            body_market_overview,
        )
        # No Streamlit → tutte le chiamate render_* sono no-op
        result = body_market_overview(tokens)
        assert result is None

    def test_p1_overview_body(self, tokens) -> None:  # type: ignore[no-untyped-def]
        from presentation.dashboard_personal.pages.P1_Overview_Patrimonio import (
            body_overview_patrimonio,
        )
        result = body_overview_patrimonio(tokens)
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
# Page factory
# ═══════════════════════════════════════════════════════════════════════════
class TestPageFactory:
    def test_build_mock_health(self) -> None:
        from presentation.ui.page_factory import build_mock_health
        health = build_mock_health()
        assert len(health.components) == 4
        assert health.is_operational

    def test_build_mock_market_kpis(self) -> None:
        from presentation.ui.page_factory import build_mock_market_kpis
        kpis = build_mock_market_kpis()
        assert len(kpis) == 7
        assert all("label" in k and "value" in k for k in kpis)
