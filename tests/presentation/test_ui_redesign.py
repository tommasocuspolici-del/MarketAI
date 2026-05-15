"""Test suite — Roadmap Unificata Settimane 6-7: UI Redesign.

Smoke test: ogni pagina importa senza errori e le funzioni body_* esistono.
Test componenti: rendering HTML corretto, graceful su None input.
"""
from __future__ import annotations

import sys
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ─── Fixtures ────────────────────────────────────────────────────────────────

class _MockTokens:
    class colors:
        positive = "#10B981"
        negative = "#EF4444"
        neutral  = "#6B7280"
        primary  = "#3B82F6"


def _mock_st():
    st = MagicMock()
    st.columns.return_value = [MagicMock(), MagicMock(), MagicMock()]
    st.expander.return_value.__enter__ = MagicMock(return_value=MagicMock())
    st.expander.return_value.__exit__  = MagicMock(return_value=False)
    return st


TOKENS = _MockTokens()


# ─── Pagine da testare ────────────────────────────────────────────────────────

ALL_PAGES = [
    "S0_Health_API_Status",
    "S1_Analysis_Pipeline",
    "M1_Macro_Dashboard",
    "M2_Yield_Curve",
    "M3_Labour_Market",
    "M4_PMI_Leading_Indicators",
    "K1_Market_Overview",
    "K2_Equity",
    "K3_Bonds_Credit",
    "K4_Commodity_Futures",
    "K5_Forex_Options",
    "Q1_VIX_Based_Analysis",
    "Q2_Sentiment",
    "Q3_Correlations",
    "Q4_Forecasting",
    "Q5_Delta",
    "T1_Backtesting",
    "T2_Stress_Test",
    "T3_Alerts",
]


# ═══════════════════════════════════════════════════════════════════════════
# Test: importazione pagine
# ═══════════════════════════════════════════════════════════════════════════

class TestPageImports:
    """Ogni pagina v8 deve importare senza errori."""

    @pytest.mark.parametrize("page_name", ALL_PAGES)
    def test_page_imports(self, page_name: str):
        """Smoke test: import del modulo pagina senza errori."""
        module = importlib.import_module(
            f"presentation.dashboard_engine.pages_v2.{page_name}"
        )
        assert module is not None
        assert hasattr(module, "__version__"), \
            f"{page_name} manca di __version__"
        assert isinstance(module.__version__, str) and module.__version__, \
            f"{page_name} ha __version__ non valido: {module.__version__}"

    @pytest.mark.parametrize("page_name", ALL_PAGES)
    def test_body_function_exists(self, page_name: str):
        """Ogni pagina ha una funzione body_<nome> callable."""
        module = importlib.import_module(
            f"presentation.dashboard_engine.pages_v2.{page_name}"
        )
        fn_name = f"body_{page_name.lower()}"
        assert hasattr(module, fn_name), \
            f"{page_name} manca di funzione {fn_name}"
        assert callable(getattr(module, fn_name)), \
            f"{page_name}.{fn_name} non è callable"

    @pytest.mark.parametrize("page_name", ALL_PAGES)
    def test_all_exports_in_all(self, page_name: str):
        """__all__ definito e non vuoto."""
        module = importlib.import_module(
            f"presentation.dashboard_engine.pages_v2.{page_name}"
        )
        assert hasattr(module, "__all__"), f"{page_name} manca __all__"
        assert len(module.__all__) > 0


# ═══════════════════════════════════════════════════════════════════════════
# Test: componenti UI
# ═══════════════════════════════════════════════════════════════════════════

class TestRegimeCompositeBadge:

    def test_renders_without_crash_all_values(self):
        """badge con tutti i valori noti non crasha."""
        from presentation.ui.components.regime_composite_badge import (
            render_regime_composite_badge,
        )
        st = _mock_st()
        render_regime_composite_badge(
            st, regime="bear", credit_stress="elevated",
            claims_regime="stagflation", vix_action="BUY",
        )
        st.markdown.assert_called_once()

    def test_renders_with_none_values(self):
        """badge con None non crasha → mostra N/D."""
        from presentation.ui.components.regime_composite_badge import (
            render_regime_composite_badge,
        )
        st = _mock_st()
        render_regime_composite_badge(st, None, None, None, None)
        html = st.markdown.call_args[0][0]
        assert "N/D" in html

    def test_html_contains_all_four_badges(self):
        """HTML output contiene tutti e 4 i label badge."""
        from presentation.ui.components.regime_composite_badge import (
            render_regime_composite_badge,
        )
        st = _mock_st()
        render_regime_composite_badge(
            st, "bull", "low", "goldilocks", "hold"
        )
        html = st.markdown.call_args[0][0]
        for label in ["HMM", "Credit", "Claims", "VIX"]:
            assert label in html, f"Label {label} mancante nell'HTML"

    def test_unknown_values_get_default_color(self):
        """Valori non mappati → colore grigio default."""
        from presentation.ui.components.regime_composite_badge import (
            render_regime_composite_badge,
        )
        st = _mock_st()
        render_regime_composite_badge(
            st, "unknown_regime", "unknown_credit",
            "unknown_claims", "unknown_vix",
        )
        html = st.markdown.call_args[0][0]
        assert "#6B7280" in html


class TestYieldCurveChart:

    def test_renders_none_snapshot_gracefully(self):
        """None snapshot → st.info, nessun crash."""
        from presentation.ui.components.yield_curve_chart import render_yield_curve_chart
        st = _mock_st()
        render_yield_curve_chart(st, None)
        st.info.assert_called_once()

    def test_renders_valid_snapshot(self):
        """Snapshot valido → st.plotly_chart chiamato."""
        from presentation.ui.components.yield_curve_chart import render_yield_curve_chart
        from shared.db.macro_repo import YieldCurveSnapshot
        from engine.alpha_generation.schemas import CurveRegime

        snapshot = YieldCurveSnapshot(
            snapshot_date=None,
            y_3m=5.1, y_2y=4.8, y_5y=4.6, y_10y=4.5, y_30y=4.7,
            spread_10y_2y=-0.3, spread_10y_3m=-0.6,
            breakeven_10y=2.2, fed_funds=5.25,
            inversion_signal=True, recession_prob_12m=0.35,
            curve_regime="inverted",
        )
        st = _mock_st()
        render_yield_curve_chart(st, snapshot)
        st.plotly_chart.assert_called_once()

    def test_renders_snapshot_with_none_tenors(self):
        """Snapshot con alcuni tenor None → non crasha."""
        from presentation.ui.components.yield_curve_chart import render_yield_curve_chart
        from shared.db.macro_repo import YieldCurveSnapshot

        snapshot = YieldCurveSnapshot(
            snapshot_date=None,
            y_3m=None, y_2y=4.8, y_5y=None, y_10y=4.5, y_30y=None,
            spread_10y_2y=None, spread_10y_3m=None,
            breakeven_10y=None, fed_funds=None,
            inversion_signal=False, recession_prob_12m=None,
            curve_regime=None,
        )
        st = _mock_st()
        render_yield_curve_chart(st, snapshot)
        # 2 valori validi → deve plottare
        st.plotly_chart.assert_called_once()


class TestClaimsCrossPanel:

    def test_renders_none_gracefully(self):
        """None signal → st.info."""
        from presentation.ui.components.claims_cross_panel import render_claims_cross_panel
        st = _mock_st()
        render_claims_cross_panel(st, None)
        st.info.assert_called_once()

    def test_renders_goldilocks_regime(self):
        """Regime goldilocks → colore verde e label corretto."""
        from presentation.ui.components.claims_cross_panel import render_claims_cross_panel
        from shared.db.macro_repo import ClaimsInflationSignal
        from engine.alpha_generation.schemas import ClaimsRegime

        signal = ClaimsInflationSignal(
            computed_at=None,
            icsa_4wk_ma=220_000, icsa_yoy_change_pct=-0.02, cpi_yoy=2.3,
            stagflation_signal=False, goldilocks_signal=True,
            overheating_signal=False, recession_watch=False,
            regime_label="goldilocks", regime_score=0.8,
        )
        st = _mock_st()
        render_claims_cross_panel(st, signal)
        # Deve chiamare st.metric almeno 3 volte (3 metriche)
        assert st.metric.call_count >= 3

    def test_renders_all_regimes_without_crash(self):
        """Tutti i regime label non causano crash."""
        from presentation.ui.components.claims_cross_panel import render_claims_cross_panel
        from shared.db.macro_repo import ClaimsInflationSignal

        for regime in ["goldilocks", "stagflation", "overheating", "recession", "neutral"]:
            signal = ClaimsInflationSignal(
                computed_at=None, icsa_4wk_ma=250_000,
                icsa_yoy_change_pct=None, cpi_yoy=3.0,
                stagflation_signal=False, goldilocks_signal=False,
                overheating_signal=False, recession_watch=False,
                regime_label=regime, regime_score=0.0,
            )
            st = _mock_st()
            render_claims_cross_panel(st, signal)
            html = st.markdown.call_args[0][0]
            assert regime.upper() in html, f"Regime {regime} mancante nell'HTML"


class TestFuturesTermStructurePanel:

    def test_renders_empty_list_gracefully(self):
        """Lista vuota → st.info."""
        from presentation.ui.components.futures_term_structure_panel import (
            render_futures_term_structure_panel,
        )
        st = _mock_st()
        render_futures_term_structure_panel(st, [])
        st.info.assert_called_once()

    def test_renders_analyses(self):
        """Lista con analisi → st.columns chiamato."""
        from presentation.ui.components.futures_term_structure_panel import (
            render_futures_term_structure_panel,
        )
        from engine.futures_analysis.schemas import (
            CommodityAnalysis, CommodityRegime, TermStructure,
            RollYieldResult, BasisResult, OpenInterestResult, OISignal,
        )
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)

        roll = RollYieldResult(
            ticker="CL=F", computed_at=now, roll_yield_22d=-0.018,
            roll_yield_annual=-0.207, term_structure=TermStructure.CONTANGO,
            front_close=71.5, second_proxy=73.0,
            roll_pct_rank=0.3, signal="bearish",
        )
        basis = BasisResult(
            ticker="CL=F", spot_ticker="USO", computed_at=now,
            basis=1.5, basis_pct=2.1, basis_zscore=0.5, signal="neutral",
        )
        oi = OpenInterestResult(
            ticker="CL=F", computed_at=now,
            oi_signal=OISignal.TREND_CONFIRMED_BULLISH,
            oi_current=250_000, oi_change_pct=2.5,
            price_change_pct=1.5, oi_pct_rank=0.65,
            institutional_bias="long_bias",
        )
        analysis = CommodityAnalysis(
            ticker="CL=F", computed_at=now,
            regime=CommodityRegime.CONTANGO_TRAP,
            score=-0.7, roll_result=roll, basis_result=basis,
            oi_result=oi, confidence="HIGH",
            summary="CL=F contango_trap (score=-0.70)",
        )

        st = _mock_st()
        st.columns.return_value = [MagicMock()]
        render_futures_term_structure_panel(st, [analysis])
        st.columns.assert_called_once()


class TestEngineSignalSummary:

    def test_renders_none_gracefully(self):
        """None signal → st.info."""
        from presentation.ui.components.engine_signal_summary import (
            render_engine_signal_summary,
        )
        st = _mock_st()
        render_engine_signal_summary(st, None)
        st.info.assert_called_once()

    def test_renders_valid_signal(self):
        """Segnale valido → st.markdown chiamato con HTML."""
        from presentation.ui.components.engine_signal_summary import (
            render_engine_signal_summary,
        )
        from shared.db.macro_repo import EngineCompositeSignal
        from datetime import datetime, timezone
        import json

        signal = EngineCompositeSignal(
            computed_at=datetime.now(timezone.utc),
            composite_score=0.42,
            recommended_action="BUY",
            confidence="HIGH",
            regime="bear",
            credit_stress="moderate",
            claims_regime="goldilocks",
            yield_curve_regime="flat",
            component_breakdown_json=json.dumps(
                {"vix": 0.6, "credit": 0.3, "claims": 0.5}
            ),
        )
        st = _mock_st()
        render_engine_signal_summary(st, signal)
        assert st.markdown.called
        html = st.markdown.call_args[0][0]
        assert "BUY" in html
        assert "0.420" in html

    def test_all_actions_render(self):
        """BUY, HOLD, REDUCE renderizzano senza crash."""
        from presentation.ui.components.engine_signal_summary import (
            render_engine_signal_summary,
        )
        from shared.db.macro_repo import EngineCompositeSignal
        from datetime import datetime, timezone

        for action, score in [("BUY", 0.5), ("HOLD", 0.0), ("REDUCE", -0.5)]:
            sig = EngineCompositeSignal(
                computed_at=datetime.now(timezone.utc),
                composite_score=score, recommended_action=action,
                confidence="MEDIUM", regime=None, credit_stress=None,
                claims_regime=None, yield_curve_regime=None,
                component_breakdown_json=None,
            )
            st = _mock_st()
            render_engine_signal_summary(st, sig)
            html = st.markdown.call_args[0][0]
            assert action in html


class TestMacroHeatmap:

    def test_renders_empty_data(self):
        """Dizionario vuoto → nessun crash."""
        from presentation.ui.components.macro_heatmap import render_macro_heatmap
        st = _mock_st()
        render_macro_heatmap(st, {})
        st.markdown.assert_called_once()

    def test_renders_partial_data(self):
        """Dati parziali (alcuni None) → nessun crash."""
        from presentation.ui.components.macro_heatmap import render_macro_heatmap
        st = _mock_st()
        data = {
            "CPIAUCSL": 2.5, "DGS10": 4.5, "ICSA": 220_000,
            "BAMLH0A0HYM2": 350.0, "VIXCLS": None, "UNRATE": 4.2,
        }
        render_macro_heatmap(st, data)
        html = st.markdown.call_args[0][0]
        assert "🟢" in html or "🟡" in html or "🔴" in html or "⚫" in html

    def test_traffic_light_classification(self):
        """Verifica logica semaforo per CPI (positive_good=False)."""
        from presentation.ui.components.macro_heatmap import _classify_traffic
        # CPI: positive_good=False, green<2.5, yellow<4.0
        color, emoji = _classify_traffic(2.0, False, 2.5, 4.0)
        assert emoji == "🟢"

        color, emoji = _classify_traffic(3.2, False, 2.5, 4.0)
        assert emoji == "🟡"

        color, emoji = _classify_traffic(5.0, False, 2.5, 4.0)
        assert emoji == "🔴"

        color, emoji = _classify_traffic(None, False, 2.5, 4.0)
        assert emoji == "⚫"

    def test_traffic_light_positive_good(self):
        """Logica semaforo per payrolls (positive_good=True)."""
        from presentation.ui.components.macro_heatmap import _classify_traffic
        # Payrolls: positive_good=True, green>=150k, yellow>=0
        color, emoji = _classify_traffic(200_000, True, 150_000, 0)
        assert emoji == "🟢"

        color, emoji = _classify_traffic(80_000, True, 150_000, 0)
        assert emoji == "🟡"

        color, emoji = _classify_traffic(-50_000, True, 150_000, 0)
        assert emoji == "🔴"


# ═══════════════════════════════════════════════════════════════════════════
# Test app_v8.py navigazione
# ═══════════════════════════════════════════════════════════════════════════

class TestAppV8Navigation:

    def test_all_pages_in_navigation(self):
        """Tutte le pagine nella PAGES dict dell'app."""
        import importlib
        app = importlib.import_module(
            "presentation.dashboard_engine.app_v8"
        )
        all_modules = [
            m for pages in app.PAGES.values()
            for _, m in pages
        ]
        # Verifica che tutte le pagine chiave siano presenti
        required = [
            "S0_Health_API_Status", "S1_Analysis_Pipeline",
            "M1_Macro_Dashboard", "M2_Yield_Curve",
            "M3_Labour_Market", "M4_PMI_Leading_Indicators",
            "K1_Market_Overview", "K4_Commodity_Futures",
            "Q1_VIX_Based_Analysis",
            "T1_Backtesting",
        ]
        for req in required:
            assert req in all_modules, f"{req} non trovato nella navigazione"

    def test_pages_dict_has_five_groups(self):
        """Esattamente 5 gruppi di navigazione."""
        import importlib
        app = importlib.import_module(
            "presentation.dashboard_engine.app_v8"
        )
        assert len(app.PAGES) == 5

    def test_total_page_count(self):
        """19 pagine totali (2+4+5+5+3)."""
        import importlib
        app = importlib.import_module(
            "presentation.dashboard_engine.app_v8"
        )
        total = sum(len(pages) for pages in app.PAGES.values())
        assert total == 19, f"Attese 19 pagine, trovate {total}"

    def test_new_pages_are_starred(self):
        """Le 5 nuove pagine hanno ★ nel label."""
        import importlib
        app = importlib.import_module(
            "presentation.dashboard_engine.app_v8"
        )
        starred = [
            label
            for pages in app.PAGES.values()
            for label, _ in pages
            if "★" in label
        ]
        assert len(starred) >= 5, f"Trovate solo {len(starred)} pagine ★"
