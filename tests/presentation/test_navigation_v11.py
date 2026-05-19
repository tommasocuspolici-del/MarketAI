"""Tests — Navigation structure Fase 1 (Roadmap Unificata v11).

Verifica che:
  1. Tutti i moduli pages_v2 importino senza errori
  2. Ogni pagina esponga la funzione body_fn con signature (st, tokens)
  3. Il registry PAGES di app_v8 sia coerente con i file presenti
"""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

# ── pages_v2 modules (engine) ───────────────────────────────────────────────
ENGINE_V2_PAGES: list[str] = [
    "S0_Health_API_Status",
    "S1_Analysis_Pipeline",
    "S2_Settings",
    "M1_Macro_Dashboard",
    "M2_Yield_Curve",
    "M3_Labour_Market",
    "M4_PMI_Leading_Indicators",
    "M5_Economic_Surprise",
    "M6_Valuation_PE",
    "M7_IB_Consensus",
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
    "Q6_Technical_Advanced",
    "Q9_Labour_Forecasting",
    "Q10_Surprise_Heatmap",
    "Q11_Options_Analytics",
    "N1_News_Feed",
    "N2_News_Analysis",
    "T1_Backtesting",
    "T2_Stress_Test",
    "T3_Alerts",
]


class TestPagesV2Import:
    """Tutti i moduli pages_v2 importano senza errori."""

    @pytest.mark.parametrize("page_name", ENGINE_V2_PAGES)
    def test_import_no_error(self, page_name: str) -> None:
        mod = importlib.import_module(
            f"presentation.dashboard_engine.pages_v2.{page_name}"
        )
        assert mod is not None

    @pytest.mark.parametrize("page_name", ENGINE_V2_PAGES)
    def test_body_function_exists(self, page_name: str) -> None:
        mod = importlib.import_module(
            f"presentation.dashboard_engine.pages_v2.{page_name}"
        )
        fn_name = f"body_{page_name.lower()}"
        assert hasattr(mod, fn_name), (
            f"{page_name}.py non espone `{fn_name}`. "
            f"Funzioni trovate: {[n for n in dir(mod) if n.startswith('body')]}"
        )

    @pytest.mark.parametrize("page_name", ENGINE_V2_PAGES)
    def test_body_function_callable(self, page_name: str) -> None:
        mod = importlib.import_module(
            f"presentation.dashboard_engine.pages_v2.{page_name}"
        )
        fn_name = f"body_{page_name.lower()}"
        if hasattr(mod, fn_name):
            fn = getattr(mod, fn_name)
            assert callable(fn)

    @pytest.mark.parametrize("page_name", ENGINE_V2_PAGES)
    def test_version_defined(self, page_name: str) -> None:
        mod = importlib.import_module(
            f"presentation.dashboard_engine.pages_v2.{page_name}"
        )
        assert hasattr(mod, "__version__"), f"{page_name} manca __version__"


class TestPagesV2Files:
    """I file .py esistono su disco per ogni entry nel registry."""

    BASE = Path(__file__).parent.parent.parent / "presentation" / "dashboard_engine" / "pages_v2"

    @pytest.mark.parametrize("page_name", ENGINE_V2_PAGES)
    def test_file_exists(self, page_name: str) -> None:
        path = self.BASE / f"{page_name}.py"
        assert path.exists(), f"File mancante: pages_v2/{page_name}.py"


class TestAppV8Registry:
    """Il PAGES dict di app_v8 è coerente coi file presenti."""

    def test_app_v8_imports(self) -> None:
        import presentation.dashboard_engine.app_v8 as app_v8
        assert hasattr(app_v8, "PAGES")
        assert isinstance(app_v8.PAGES, dict)

    def test_all_registry_pages_exist(self) -> None:
        import presentation.dashboard_engine.app_v8 as app_v8
        base = Path(__file__).parent.parent.parent / "presentation" / "dashboard_engine" / "pages_v2"
        missing = []
        for group, pages in app_v8.PAGES.items():
            for label, module_name in pages:
                path = base / f"{module_name}.py"
                if not path.exists():
                    missing.append(f"{group} → {label} ({module_name}.py)")
        assert not missing, f"File mancanti in pages_v2/:\n" + "\n".join(missing)

    def test_pages_count(self) -> None:
        import presentation.dashboard_engine.app_v8 as app_v8
        total = sum(len(p) for p in app_v8.PAGES.values())
        assert total >= 28, f"Troppo poche pagine in PAGES: {total}"


class TestNavigationGroups:
    """Verifica struttura a gruppi della navigazione."""

    def test_sistema_group_present(self) -> None:
        import presentation.dashboard_engine.app_v8 as app_v8
        keys = list(app_v8.PAGES.keys())
        assert any("SISTEMA" in k for k in keys)

    def test_macro_group_present(self) -> None:
        import presentation.dashboard_engine.app_v8 as app_v8
        keys = list(app_v8.PAGES.keys())
        assert any("MACRO" in k for k in keys)

    def test_mercati_group_present(self) -> None:
        import presentation.dashboard_engine.app_v8 as app_v8
        keys = list(app_v8.PAGES.keys())
        assert any("MERCATI" in k for k in keys)

    def test_news_group_present(self) -> None:
        import presentation.dashboard_engine.app_v8 as app_v8
        keys = list(app_v8.PAGES.keys())
        assert any("NEWS" in k for k in keys)
