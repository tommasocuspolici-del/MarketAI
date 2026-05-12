"""Tests for ClaimsCycleDetector — ciclo espansione→contrazione su fixture 2020."""
from __future__ import annotations
import pandas as pd
import numpy as np
import pytest
from engine.analytics.labour_market.claims_cycle_detector import ClaimsCycleDetector


def _make_claims_df(values: list[float]) -> pd.DataFrame:
    ts = pd.date_range("2019-01-01", periods=len(values), freq="W-SAT")
    return pd.DataFrame({"ts": ts, "value": values})


class TestClaimsRegimes:

    def test_contraction_high_yoy(self):
        """YoY > 15% → contraction."""
        # Baseline 230k poi spike a 6M a COVID peak (~7 milioni)
        baseline  = [230_000] * 52
        covid     = [6_900_000] * 10
        recovery  = [500_000] * 20
        all_vals  = baseline + covid + recovery
        df = _make_claims_df(all_vals)
        detector = ClaimsCycleDetector(duckdb=None)
        signal = detector._compute_signal(df)
        assert signal.cycle_regime == "contraction"

    def test_expansion_low_stable(self):
        """Claims stazionari bassi → expansion."""
        vals = [220_000 + i * 100 for i in range(60)]  # Lieve calo
        df   = _make_claims_df(vals)
        detector = ClaimsCycleDetector(duckdb=None)
        signal = detector._compute_signal(df)
        assert signal.cycle_regime in ("expansion", "trough")

    def test_peak_moderate_rise(self):
        """Claims in salita moderata → peak."""
        base = [220_000] * 30
        rise = [220_000 + i * 3_000 for i in range(10)]
        df   = _make_claims_df(base + rise)
        detector = ClaimsCycleDetector(duckdb=None)
        signal = detector._compute_signal(df)
        assert signal.cycle_regime in ("peak", "contraction")


class TestClaimsSignal:

    def test_signal_strength_in_range(self):
        """signal_strength deve essere in [-1, 1]."""
        vals = [250_000] * 60
        df   = _make_claims_df(vals)
        detector = ClaimsCycleDetector(duckdb=None)
        signal = detector._compute_signal(df)
        assert -1.0 <= signal.signal_strength <= 1.0

    def test_4wk_ma_computed(self):
        """4wk MA calcolata correttamente."""
        vals = [100_000, 110_000, 120_000, 130_000, 140_000]
        df   = _make_claims_df(vals)
        detector = ClaimsCycleDetector(duckdb=None)
        signal = detector._compute_signal(df)
        # MA delle ultime 4 = (110+120+130+140)/4 = 125k
        assert abs(signal.claims_4wk_ma - 125_000) < 500
