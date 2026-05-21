"""Tests for P1-P5 pure loader functions — no Streamlit dependency."""
from __future__ import annotations

import pandas as pd
from unittest.mock import MagicMock, patch


# ─── P1 Overview Patrimonio ───────────────────────────────────────────────────

class TestP1OverviewLoaders:
    def test_load_networth_summary_returns_dict(self) -> None:
        from presentation.dashboard_personal.pages.P1_Overview_Patrimonio import _load_networth_summary
        result = _load_networth_summary()
        assert isinstance(result, dict)

    def test_load_networth_summary_has_required_keys(self) -> None:
        from presentation.dashboard_personal.pages.P1_Overview_Patrimonio import _load_networth_summary
        result = _load_networth_summary()
        for key in ("total_assets", "total_liabilities", "net_worth", "liquid_assets"):
            assert key in result, f"Missing key: {key}"

    def test_load_networth_summary_graceful_on_db_error(self) -> None:
        from presentation.dashboard_personal.pages.P1_Overview_Patrimonio import _load_networth_summary
        with patch(
            "presentation.dashboard_personal.pages.P1_Overview_Patrimonio.net_worth_summary",
            side_effect=RuntimeError,
        ):
            result = _load_networth_summary()
        assert result["total_assets"] == 0.0
        assert result["net_worth"] == 0.0

    def test_load_networth_summary_values_are_numeric(self) -> None:
        from presentation.dashboard_personal.pages.P1_Overview_Patrimonio import _load_networth_summary
        result = _load_networth_summary()
        assert isinstance(result["total_assets"], (int, float))
        assert isinstance(result["net_worth"], (int, float))


# ─── P2 Portafoglio eToro ────────────────────────────────────────────────────

class TestP2PortfolioLoaders:
    def test_load_positions_returns_list(self) -> None:
        from presentation.dashboard_personal.pages.P2_Portafoglio_eToro import _load_positions
        result = _load_positions()
        assert isinstance(result, list)

    def test_load_positions_graceful_on_db_error(self) -> None:
        from presentation.dashboard_personal.pages.P2_Portafoglio_eToro import _load_positions
        with patch(
            "personal.data_entry.position_form.list_positions",
            side_effect=RuntimeError,
        ):
            result = _load_positions()
        assert result == []

    def test_load_portfolio_snapshot_returns_dataframe(self) -> None:
        from presentation.dashboard_personal.pages.P2_Portafoglio_eToro import _load_portfolio_snapshot
        result = _load_portfolio_snapshot()
        assert isinstance(result, pd.DataFrame)

    def test_load_portfolio_snapshot_graceful_on_error(self) -> None:
        from presentation.dashboard_personal.pages.P2_Portafoglio_eToro import _load_portfolio_snapshot
        with patch(
            "personal.data_entry.position_form.list_positions",
            side_effect=RuntimeError,
        ):
            result = _load_portfolio_snapshot()
        assert result.empty

    def test_get_api_import_status_no_key(self) -> None:
        from presentation.dashboard_personal.pages.P2_Portafoglio_eToro import _get_api_import_status
        with patch.dict("os.environ", {}, clear=True):
            result = _get_api_import_status()
        assert result == "error"

    def test_get_api_import_status_with_key(self) -> None:
        from presentation.dashboard_personal.pages.P2_Portafoglio_eToro import _get_api_import_status
        with patch.dict("os.environ", {"ETORO_API_KEY": "test-key-123"}):
            result = _get_api_import_status()
        assert result == "ok"

    def test_get_xlsx_import_status_none(self) -> None:
        from presentation.dashboard_personal.pages.P2_Portafoglio_eToro import _get_xlsx_import_status
        assert _get_xlsx_import_status(None) == "unknown"

    def test_get_xlsx_import_status_with_result(self) -> None:
        from presentation.dashboard_personal.pages.P2_Portafoglio_eToro import _get_xlsx_import_status
        mock_result = MagicMock()
        assert _get_xlsx_import_status(mock_result) == "ok"

    def test_status_dot_import_ok(self) -> None:
        from presentation.ui.components import StatusDot
        dot = StatusDot(label="eToro API", status="ok")
        html = dot.to_html()
        assert "🟢" in html
        assert "eToro API" in html

    def test_status_dot_import_error(self) -> None:
        from presentation.ui.components import StatusDot
        dot = StatusDot(label="eToro API", status="error")
        html = dot.to_html()
        assert "🔴" in html

    def test_status_dot_import_unknown(self) -> None:
        from presentation.ui.components import StatusDot
        dot = StatusDot(label="XLSX", status="unknown")
        html = dot.to_html()
        assert "⚪" in html


# ─── Smoke: imports of all P pages work ──────────────────────────────────────

class TestPagesImportClean:
    def test_p1_imports_empty_state(self) -> None:
        import importlib
        mod = importlib.import_module(
            "presentation.dashboard_personal.pages.P1_Overview_Patrimonio"
        )
        assert hasattr(mod, "body_overview_patrimonio")
        assert hasattr(mod, "_load_networth_summary")

    def test_p2_imports_status_dot_and_empty_state(self) -> None:
        import importlib
        mod = importlib.import_module(
            "presentation.dashboard_personal.pages.P2_Portafoglio_eToro"
        )
        assert hasattr(mod, "_load_positions")
        assert hasattr(mod, "_load_portfolio_snapshot")
        assert hasattr(mod, "_get_api_import_status")
        assert hasattr(mod, "_render_registry_tab")

    def test_p3_imports_empty_state(self) -> None:
        import importlib
        mod = importlib.import_module(
            "presentation.dashboard_personal.pages.P3_Cash_Flow"
        )
        assert mod is not None

    def test_p4_imports_empty_state(self) -> None:
        import importlib
        mod = importlib.import_module(
            "presentation.dashboard_personal.pages.P4_Net_Worth"
        )
        assert mod is not None

    def test_p5_imports_empty_state(self) -> None:
        import importlib
        mod = importlib.import_module(
            "presentation.dashboard_personal.pages.P5_Goals"
        )
        assert mod is not None
