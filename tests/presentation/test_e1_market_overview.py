"""Tests for E1 Market Overview data loaders — no Streamlit dependency."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from presentation.dashboard_engine.pages.E1_Market_Overview import (
    KpiData,
    _build_regime_df_from_vix,
    _derive_regime,
    _load_signal_snapshot,
    _load_sp500_history,
    _snapshot_to_kpi_data,
)


class TestDeriveRegime:
    @pytest.mark.parametrize("vix,expected", [
        (10.0,  "bull"),
        (15.0,  "bull"),     # boundary: v > 15 → exactly 15 stays bull
        (15.1,  "transition"),
        (24.9,  "transition"),
        (25.0,  "transition"),  # boundary: v > 25 → exactly 25 stays transition
        (25.1,  "bear"),
        (29.9,  "bear"),
        (30.0,  "bear"),    # boundary: v > 30 → exactly 30 stays bear
        (30.1,  "stress"),
        (50.0,  "stress"),
    ])
    def test_regime_thresholds(self, vix: float, expected: str) -> None:
        assert _derive_regime(vix) == expected

    def test_none_returns_unknown(self) -> None:
        assert _derive_regime(None) == "unknown"

    def test_returns_string(self) -> None:
        assert isinstance(_derive_regime(20.0), str)


class TestSnapshotToKpiData:
    def _make_snapshot(self, kpis_data: list[dict]) -> MagicMock:
        snapshot = MagicMock()
        kpis = []
        for d in kpis_data:
            kpi = MagicMock()
            kpi.term = d.get("term", "TEST")
            kpi.value = d.get("value", 100.0)
            kpi.delta_pct = d.get("delta_pct", None)
            kpi.currency = d.get("currency", "USD")
            kpi.is_stale = d.get("is_stale", False)
            kpis.append(kpi)
        snapshot.kpis = kpis
        return snapshot

    def test_returns_list_of_kpi_data(self) -> None:
        snap = self._make_snapshot([{"term": "VIX", "value": 18.0}])
        result = _snapshot_to_kpi_data(snap)
        assert isinstance(result, list)
        assert all(isinstance(r, KpiData) for r in result)

    def test_length_matches_kpis(self) -> None:
        snap = self._make_snapshot([
            {"term": "S&P 500", "value": 5000.0},
            {"term": "VIX", "value": 18.0},
        ])
        result = _snapshot_to_kpi_data(snap)
        assert len(result) == 2

    def test_none_value_becomes_dash(self) -> None:
        snap = self._make_snapshot([{"term": "VIX", "value": None}])
        result = _snapshot_to_kpi_data(snap)
        assert result[0].value == "—"

    def test_none_value_flag_insufficient_data(self) -> None:
        snap = self._make_snapshot([{"term": "VIX", "value": None}])
        result = _snapshot_to_kpi_data(snap)
        assert result[0].quality_flag == "insufficient_data"

    def test_stale_flag(self) -> None:
        snap = self._make_snapshot([{"term": "VIX", "value": 18.0, "is_stale": True}])
        result = _snapshot_to_kpi_data(snap)
        assert result[0].quality_flag == "stale"

    def test_sp500_gets_icon(self) -> None:
        snap = self._make_snapshot([{"term": "S&P 500", "value": 5000.0}])
        result = _snapshot_to_kpi_data(snap)
        assert result[0].icon != ""

    def test_unit_contains_currency(self) -> None:
        snap = self._make_snapshot([{"term": "Gold", "value": 2350.0, "currency": "USD"}])
        result = _snapshot_to_kpi_data(snap)
        assert "USD" in result[0].unit


class TestLoadSignalSnapshot:
    def test_returns_dict(self) -> None:
        result = _load_signal_snapshot()
        assert isinstance(result, dict)

    def test_values_are_tuples(self) -> None:
        result = _load_signal_snapshot()
        for k, v in result.items():
            assert isinstance(v, tuple)
            assert len(v) == 3

    def test_tuple_types(self) -> None:
        from shared.signal_registry import get_signal_registry
        from shared.signal_types import Signal

        registry = get_signal_registry()
        sig = Signal(name="_e1_test_sig", value=0.3, confidence=1.0, source_module="test")
        registry.publish(sig, ttl_seconds=60)

        result = _load_signal_snapshot()
        assert "_e1_test_sig" in result
        val, ic, flag = result["_e1_test_sig"]
        assert isinstance(val, float)
        assert flag in {"ok", "low_ic", "insufficient_data", "stale"}


class TestLoadSp500History:
    def test_returns_dataframe(self) -> None:
        result = _load_sp500_history()
        assert isinstance(result, pd.DataFrame)

    def test_has_required_columns_or_empty(self) -> None:
        result = _load_sp500_history()
        if not result.empty:
            assert "date" in result.columns
            assert "close" in result.columns

    def test_respects_days_limit(self) -> None:
        result = _load_sp500_history(days=30)
        assert len(result) <= 40  # some slack for weekends

    def test_db_error_returns_empty(self) -> None:
        with patch(
            "shared.db.prices_repo.PricesRepository",
            side_effect=RuntimeError("DB error"),
        ):
            result = _load_sp500_history()
        assert result.empty


class TestBuildRegimeDf:
    def test_none_vix_returns_empty(self) -> None:
        df = _build_regime_df_from_vix(None)
        assert df.empty

    def test_returns_dataframe(self) -> None:
        df = _build_regime_df_from_vix(20.0)
        assert isinstance(df, pd.DataFrame)

    def test_has_date_and_regime_columns(self) -> None:
        df = _build_regime_df_from_vix(20.0)
        assert "date" in df.columns
        assert "regime" in df.columns

    def test_regime_consistent_with_vix(self) -> None:
        df = _build_regime_df_from_vix(35.0)
        assert all(r == "stress" for r in df["regime"])

    def test_has_two_rows(self) -> None:
        df = _build_regime_df_from_vix(18.0)
        assert len(df) == 2
