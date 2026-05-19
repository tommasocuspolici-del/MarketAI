"""Tests — ConsensusBuilder (Fase 8)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from engine.ib_forecast.consensus_builder import ConsensusBuilder
from engine.ib_forecast.schemas import IBConsensus, IBSignal


def _make_client(rows: list | None = None) -> MagicMock:
    client = MagicMock()
    client.query.return_value = rows or []
    client.execute.return_value = None
    return client


class TestConsensusBuilder:
    def test_build_empty_returns_empty(self) -> None:
        client = _make_client(rows=[])
        builder = ConsensusBuilder(client)
        result = builder.build()
        assert result == []

    def test_build_db_error_returns_empty(self) -> None:
        client = _make_client()
        client.query.side_effect = RuntimeError("DB down")
        builder = ConsensusBuilder(client)
        result = builder.build()
        assert result == []

    def test_build_single_row(self) -> None:
        rows = [("GDP", "2025", 2.5, "fed_sep", 0.9)]
        client = _make_client(rows=rows)
        builder = ConsensusBuilder(client)
        result = builder.build()
        assert len(result) == 1
        assert result[0].indicator == "GDP"
        assert result[0].consensus_value == pytest.approx(2.5)

    def test_build_multiple_sources_median(self) -> None:
        rows = [
            ("GDP", "2025", 2.0, "source_a", 0.9),
            ("GDP", "2025", 3.0, "source_b", 0.8),
            ("GDP", "2025", 2.5, "source_c", 0.7),
        ]
        client = _make_client(rows=rows)
        builder = ConsensusBuilder(client)
        result = builder.build()
        assert len(result) == 1
        assert result[0].consensus_value == pytest.approx(2.5)
        assert result[0].source_count == 3
        assert result[0].consensus_low == pytest.approx(2.0)
        assert result[0].consensus_high == pytest.approx(3.0)

    def test_build_multiple_indicators(self) -> None:
        rows = [
            ("GDP", "2025", 2.5, "source_a", 0.9),
            ("CPI", "2025", 3.0, "source_a", 0.8),
            ("FEDFUNDS", "2025", 4.5, "source_b", 0.9),
        ]
        client = _make_client(rows=rows)
        builder = ConsensusBuilder(client)
        result = builder.build()
        indicators = {c.indicator for c in result}
        assert "GDP" in indicators
        assert "CPI" in indicators
        assert "FEDFUNDS" in indicators

    def test_build_single_source_quality(self) -> None:
        rows = [("GDP", "2025", 2.5, "only_source", 0.9)]
        client = _make_client(rows=rows)
        builder = ConsensusBuilder(client)
        result = builder.build()
        assert result[0].data_quality == "single_source"

    def test_build_multi_source_quality_ok(self) -> None:
        rows = [
            ("GDP", "2025", 2.0, "source_a", 0.9),
            ("GDP", "2025", 3.0, "source_b", 0.8),
        ]
        client = _make_client(rows=rows)
        builder = ConsensusBuilder(client)
        result = builder.build()
        assert result[0].data_quality == "ok"

    def test_build_persists_consensus(self) -> None:
        rows = [("GDP", "2025", 2.5, "source_a", 0.9)]
        client = _make_client(rows=rows)
        builder = ConsensusBuilder(client)
        builder.build()
        assert client.execute.called

    def test_build_signal_no_data(self) -> None:
        client = _make_client(rows=[])
        builder = ConsensusBuilder(client)
        signal = builder.build_signal([])
        assert isinstance(signal, IBSignal)
        assert signal.score == pytest.approx(0.0)
        assert signal.data_quality == "no_data"

    def test_build_signal_gdp_bull(self) -> None:
        gdp_consensus = IBConsensus(
            indicator="GDP", horizon="2025", consensus_value=3.5,
            source_count=2, computed_at=datetime.now(UTC),
        )
        client = _make_client(rows=[])
        builder = ConsensusBuilder(client)
        signal = builder.build_signal([gdp_consensus])
        assert signal.gdp_signal is not None
        assert signal.gdp_signal > 0  # GDP > 2.5% → bullish

    def test_build_signal_cpi_bear(self) -> None:
        cpi_consensus = IBConsensus(
            indicator="CPI", horizon="2025", consensus_value=5.5,
            source_count=2, computed_at=datetime.now(UTC),
        )
        client = _make_client(rows=[])
        builder = ConsensusBuilder(client)
        signal = builder.build_signal([cpi_consensus])
        assert signal.inflation_signal is not None
        assert signal.inflation_signal < 0  # CPI > 4% → bearish

    def test_build_signal_score_bounded(self) -> None:
        rows = [
            ("GDP", "2025", 5.0, "source_a", 0.9),
            ("CPI", "2025", 1.0, "source_b", 0.9),
            ("FEDFUNDS", "2025", 0.5, "source_c", 0.9),
        ]
        client = _make_client(rows=rows)
        builder = ConsensusBuilder(client)
        signal = builder.build_signal()
        assert -1.0 <= signal.score <= 1.0

    def test_build_signal_persists(self) -> None:
        client = _make_client(rows=[])
        builder = ConsensusBuilder(client)
        builder.build_signal([])
        assert client.execute.called
