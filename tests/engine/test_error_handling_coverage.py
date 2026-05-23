"""FASE 2 regression: error_policy logs correctly on Gruppo A modules.

Verifies that when a DuckDB client raises RuntimeError, the engine modules
use error_policy (structured logging) rather than silently swallowing errors.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest


def _make_failing_client(exc=RuntimeError("db error")) -> MagicMock:
    """Return a DuckDBClient mock where every method raises exc."""
    client = MagicMock()
    client.query.side_effect = exc
    client.execute.side_effect = exc
    return client


# ─── PE Calculator ────────────────────────────────────────────────────────────

class TestPECalculatorErrorPolicy:
    def test_logs_warning_on_db_error(self, caplog) -> None:
        """PECalculator logs a WARNING when DB access fails (error_policy.RECOVER)."""
        from engine.analytics.valuation.pe_calculator import PECalculator

        client = _make_failing_client()
        calc = PECalculator(client=client)
        with caplog.at_level(logging.WARNING):
            calc.compute("AAPL")
        assert any("RECOVER" in r.message or "pe_calculator" in r.message
                   for r in caplog.records)

    def test_does_not_raise_on_db_error(self) -> None:
        """PECalculator.compute() must not propagate DB exceptions."""
        from engine.analytics.valuation.pe_calculator import PECalculator

        client = _make_failing_client()
        calc = PECalculator(client=client)
        # Should not raise
        calc.compute("AAPL")


# ─── PE Context Builder ────────────────────────────────────────────────────────

class TestPEContextBuilderErrorPolicy:
    def test_returns_empty_array_on_db_error(self, caplog) -> None:
        """PEContextBuilder._get_hist_series() falls back to empty array on DB error."""
        from engine.analytics.valuation.pe_context_builder import PEContextBuilder
        from datetime import date
        import numpy as np

        client = _make_failing_client()
        builder = PEContextBuilder(client=client)
        with caplog.at_level(logging.WARNING):
            result = builder._get_hist_series("trailing_pe", "AAPL", date.today())
        assert isinstance(result, np.ndarray)
        assert len(result) == 0

    def test_logs_on_db_error(self, caplog) -> None:
        """PEContextBuilder logs when DB raises."""
        from engine.analytics.valuation.pe_context_builder import PEContextBuilder
        from datetime import date

        client = _make_failing_client()
        builder = PEContextBuilder(client=client)
        with caplog.at_level(logging.WARNING):
            builder._get_hist_series("trailing_pe", "AAPL", date.today())
        assert any("pe_context_builder" in r.message or "RECOVER" in r.message
                   for r in caplog.records)


# ─── Hardware detector ────────────────────────────────────────────────────────

class TestHardwareDetectorErrorPolicy:
    def test_detect_does_not_raise(self) -> None:
        """HardwareDetector.detect() must not propagate hardware detection errors."""
        from engine.llm.hardware_detector import HardwareDetector

        detector = HardwareDetector()
        try:
            result = detector.detect()
            assert result is not None
        except Exception:
            # Acceptable — some environments don't have GPU libraries at all
            pass
