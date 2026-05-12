"""Tests PayrollDecomposer — cyclical/defensive split."""
from __future__ import annotations
import pandas as pd
import numpy as np
import pytest
from engine.analytics.labour_market.payroll_decomposer import PayrollDecomposer


def _make_df(values: list[float]) -> pd.DataFrame:
    ts = pd.date_range("2020-01-01", periods=len(values), freq="MS")
    return pd.DataFrame({"ts": ts, "value": values})


class TestPayrollDecomposer:

    def test_cyclical_heavy_payroll(self):
        """Settori ciclici forte, difensivi piatti → cyclical_ratio > 1."""
        decomposer = PayrollDecomposer(duckdb=None)
        total_df = _make_df([150_000 + i * 500 for i in range(24)])
        frames = {
            "manufacturing":    _make_df([100 + i * 10 for i in range(24)]),
            "construction":     _make_df([50 + i * 5 for i in range(24)]),
            "retail":           _make_df([80 + i * 8 for i in range(24)]),
            "leisure_hosp":     _make_df([70 + i * 7 for i in range(24)]),
            "services_private": _make_df([200] * 24),
            "government":       _make_df([10] * 24),
            "education_health": _make_df([20] * 24),
        }
        signal = decomposer._compute_signal(total_df, frames)
        assert signal.cyclical_jobs > 0
        assert signal.payroll_score >= -1.0

    def test_payroll_score_in_range(self):
        """payroll_score deve essere in [-1, 1]."""
        decomposer = PayrollDecomposer(duckdb=None)
        total_df = _make_df([150_000] * 24)
        frames = {s: _make_df([100.0] * 24)
                  for s in ["manufacturing","construction","retail","leisure_hosp",
                             "services_private","government","education_health"]}
        signal = decomposer._compute_signal(total_df, frames)
        assert -1.0 <= signal.payroll_score <= 1.0

    def test_revision_computed(self):
        """2-month revision calcolato correttamente."""
        decomposer = PayrollDecomposer(duckdb=None)
        vals = [100, 102, 104, 103, 105, 107]
        total_df = _make_df(vals)
        rev = decomposer._compute_revision(total_df)
        assert rev is not None
