"""Tests for M1-M4 data loaders — no Streamlit dependency."""
from __future__ import annotations

import pandas as pd
import pytest

from presentation.dashboard_engine.pages.M1_Macro_Signals import (
    MacroKpiRow,
    _load_macro_data,
    _load_macro_series,
)
from presentation.dashboard_engine.pages.M2_VIX_Signals import (
    _load_vix_current,
    _load_vix_series,
    _vix_to_regime_label,
)
from presentation.dashboard_engine.pages.M4_Yield_Curve import (
    YieldSnapshot as M4YieldSnapshot,
    _load_yield_series,
    _load_yield_snapshot,
)


class TestM1MacroLoaders:
    def test_load_macro_data_returns_list(self) -> None:
        result = _load_macro_data()
        assert isinstance(result, list)

    def test_load_macro_data_rows_typed(self) -> None:
        result = _load_macro_data()
        for r in result:
            assert isinstance(r, MacroKpiRow)

    def test_load_macro_series_returns_dataframe(self) -> None:
        df = _load_macro_series("UNRATE", limit=10)
        assert isinstance(df, pd.DataFrame)

    def test_load_macro_series_empty_on_error(self) -> None:
        from unittest.mock import patch
        with patch("shared.db.duckdb_client.DuckDBClient", side_effect=RuntimeError):
            df = _load_macro_series("UNRATE")
        assert df.empty

    def test_load_macro_series_has_correct_columns_or_empty(self) -> None:
        df = _load_macro_series("UNRATE", limit=5)
        if not df.empty:
            assert "date" in df.columns
            assert "value" in df.columns


class TestM2VixLoaders:
    @pytest.mark.parametrize("vix,expected", [
        (10.0, "Compiacenza estrema"),
        (15.0, "Bassa volatilità"),
        (25.0, "Volatilità moderata"),
        (35.0, "Alta volatilità"),
        (50.0, "Crisi / Panico"),
    ])
    def test_vix_regime_label(self, vix: float, expected: str) -> None:
        assert _vix_to_regime_label(vix) == expected

    def test_vix_regime_label_none(self) -> None:
        assert _vix_to_regime_label(None) == "Sconosciuto"

    def test_load_vix_series_returns_dataframe(self) -> None:
        df = _load_vix_series(limit=10)
        assert isinstance(df, pd.DataFrame)

    def test_load_vix_series_columns_or_empty(self) -> None:
        df = _load_vix_series(limit=5)
        if not df.empty:
            assert "date" in df.columns
            assert "value" in df.columns

    def test_load_vix_current_returns_float_or_none(self) -> None:
        result = _load_vix_current()
        assert result is None or isinstance(result, float)


class TestM4YieldLoaders:
    def test_load_yield_snapshot_returns_snapshot(self) -> None:
        result = _load_yield_snapshot()
        assert isinstance(result, M4YieldSnapshot)

    def test_load_yield_snapshot_spread_consistent(self) -> None:
        snap = _load_yield_snapshot()
        if snap.spread_bp is not None:
            assert snap.is_inverted == (snap.spread_bp < 0)

    def test_load_yield_series_returns_dataframe(self) -> None:
        df = _load_yield_series("DGS10", limit=10)
        assert isinstance(df, pd.DataFrame)

    def test_load_yield_series_empty_on_db_error(self) -> None:
        from unittest.mock import patch
        with patch("shared.db.duckdb_client.DuckDBClient", side_effect=RuntimeError):
            df = _load_yield_series("DGS10")
        assert df.empty

    def test_yield_snapshot_graceful_no_api_key(self) -> None:
        # Should not raise even without FRED_API_KEY
        snap = _load_yield_snapshot()
        assert isinstance(snap, M4YieldSnapshot)
