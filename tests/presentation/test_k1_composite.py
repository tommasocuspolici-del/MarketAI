"""Tests for K1 Composite Signal data loaders — no Streamlit dependency."""
from __future__ import annotations

import pytest

from presentation.dashboard_engine.pages.K1_Composite_Signal import (
    CompositeSnapshot,
    ComponentRow,
    _build_narrative_template,
    _load_composite_history,
    _load_composite_snapshot,
)


class TestLoadCompositeSnapshot:
    def test_returns_composite_snapshot(self) -> None:
        result = _load_composite_snapshot()
        assert isinstance(result, CompositeSnapshot)

    def test_composite_value_in_range(self) -> None:
        snap = _load_composite_snapshot()
        assert -1.0 <= snap.composite_value <= 1.0

    def test_components_are_component_rows(self) -> None:
        snap = _load_composite_snapshot()
        for c in snap.components:
            assert isinstance(c, ComponentRow)

    def test_n_signals_ok_lte_total(self) -> None:
        snap = _load_composite_snapshot()
        assert snap.n_signals_ok <= snap.n_signals_total

    def test_confidence_score_in_range(self) -> None:
        snap = _load_composite_snapshot()
        assert 0.0 <= snap.confidence_score <= 1.0

    def test_no_exception_when_registry_empty(self) -> None:
        from shared.signal_registry import get_signal_registry
        get_signal_registry().clear()
        snap = _load_composite_snapshot()
        assert snap.n_signals_total == 0
        assert snap.composite_value == 0.0

    def test_with_published_signals(self) -> None:
        from shared.signal_registry import get_signal_registry
        from shared.signal_types import Signal

        registry = get_signal_registry()
        for sig_name, val in [
            ("technical_composite", 0.4),
            ("macro_conviction", 0.3),
        ]:
            registry.publish(
                Signal(name=sig_name, value=val, confidence=1.0, source_module="test"),
                ttl_seconds=60,
            )
        snap = _load_composite_snapshot()
        assert snap.n_signals_total >= 2


class TestCompositeSnapshotDirectionLabel:
    @pytest.mark.parametrize("val,expected_substr", [
        (0.8,   "FORTEMENTE RIALZISTA"),
        (0.35,  "MODERATAMENTE RIALZISTA"),
        (0.1,   "LIEVEMENTE RIALZISTA"),
        (0.0,   "NEUTRO"),
        (-0.1,  "LIEVEMENTE RIBASSISTA"),
        (-0.35, "MODERATAMENTE RIBASSISTA"),
        (-0.8,  "FORTEMENTE RIBASSISTA"),
    ])
    def test_direction_thresholds(self, val: float, expected_substr: str) -> None:
        snap = CompositeSnapshot(composite_value=val, regime="transition")
        assert snap.direction_label == expected_substr


class TestBuildNarrativeTemplate:
    def _make_snap(self, composite: float, n_ok: int = 5, n_total: int = 7) -> CompositeSnapshot:
        components = [
            ComponentRow(name=f"s{i}", label=f"Signal{i}",
                         value=0.3 * (i - 3), ic_estimate=0.07, quality_flag="ok")
            for i in range(n_total)
        ]
        return CompositeSnapshot(
            composite_value=composite,
            regime="bull",
            components=components,
            n_signals_ok=n_ok,
            n_signals_total=n_total,
            confidence_score=n_ok / n_total,
            consensus_direction="RIALZISTA",
        )

    def test_returns_non_empty_string(self) -> None:
        snap = self._make_snap(0.34)
        result = _build_narrative_template(snap)
        assert isinstance(result, str)
        assert len(result) > 50

    def test_contains_composite_value(self) -> None:
        snap = self._make_snap(0.34)
        result = _build_narrative_template(snap)
        assert "+0.340" in result

    def test_contains_direction_label(self) -> None:
        snap = self._make_snap(0.34)
        result = _build_narrative_template(snap)
        assert "moderatamente rialzista" in result.lower()

    def test_contains_quality_info(self) -> None:
        snap = self._make_snap(0.0, n_ok=5, n_total=7)
        result = _build_narrative_template(snap)
        assert "5/7" in result

    def test_pure_deterministic(self) -> None:
        snap = self._make_snap(0.5)
        r1 = _build_narrative_template(snap)
        r2 = _build_narrative_template(snap)
        assert r1 == r2


class TestLoadCompositeHistory:
    def test_returns_dataframe(self) -> None:
        import pandas as pd
        result = _load_composite_history()
        assert hasattr(result, "columns")

    def test_empty_or_has_correct_columns(self) -> None:
        import pandas as pd
        result = _load_composite_history()
        if not result.empty:
            assert "date" in result.columns
            assert "value" in result.columns

    def test_db_error_returns_empty(self) -> None:
        from unittest.mock import patch
        with patch("shared.db.duckdb_client.DuckDBClient", side_effect=RuntimeError("DB error")):
            result = _load_composite_history()
        assert result.empty
