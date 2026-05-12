"""Tests for JOLTSAnalyzer — tutti e 4 i regimi + Beveridge gap sign check."""
from __future__ import annotations
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from engine.analytics.labour_market.jolts_analyzer import JOLTSAnalyzer


def _make_fred_df(vals: list[float], col: str = "value") -> pd.DataFrame:
    ts = pd.date_range("2023-01-01", periods=len(vals), freq="MS")
    return pd.DataFrame({"ts": ts, col: vals, "value": vals})


def _make_analyzer_with_mocks(quits_rate: list[float], openings_rate: list[float],
                                unemployment: list[float], quits_mom_delta: float = 0.0):
    analyzer = JOLTSAnalyzer(duckdb=None)
    q_long = list(quits_rate) + [quits_rate[-1] + quits_mom_delta] * 3
    frames = {
        "quits_rate": _make_fred_df(q_long),
        "openings_rate": _make_fred_df(openings_rate),
        "unemployment": _make_fred_df(unemployment),
        "hires": _make_fred_df([5000] * len(quits_rate)),
        "quits": _make_fred_df([4000] * len(quits_rate)),
        "job_openings": _make_fred_df([10000] * len(quits_rate)),
        "layoffs": _make_fred_df([1500] * len(quits_rate)),
        "hires_rate": _make_fred_df([3.5] * len(quits_rate)),
    }
    return analyzer, frames


class TestJOLTSRegimes:

    def test_tight_regime(self):
        """quits_rate >= 2.5 e openings_rate >= 5.0 → regime tight."""
        analyzer, frames = _make_analyzer_with_mocks(
            quits_rate=[2.7]*8, openings_rate=[5.5]*8, unemployment=[3.5]*8
        )
        signal = analyzer._compute_signal(frames)
        assert signal.regime == "tight"

    def test_balanced_regime(self):
        """quits_rate 2.0-2.5 e openings_rate 3.5-5.0 → balanced."""
        analyzer, frames = _make_analyzer_with_mocks(
            quits_rate=[2.1]*8, openings_rate=[4.0]*8, unemployment=[4.5]*8
        )
        signal = analyzer._compute_signal(frames)
        assert signal.regime == "balanced"

    def test_deteriorating_regime(self):
        """quits_momentum < -0.3 → deteriorating."""
        # Costruisce il frame direttamente senza il padding di _make_analyzer_with_mocks
        # che causerebbe arr[-1]-arr[-4]=0.  Valori: [2.0,1.9,1.8,1.4,1.3] → momentum=-0.5
        import pandas as pd
        analyzer = JOLTSAnalyzer(duckdb=None)
        qr_vals = [2.5, 2.3, 2.0, 1.8, 1.5, 1.4, 1.3, 1.2, 0.9, 0.8, 0.7, 0.6]
        ts = pd.date_range("2023-01-01", periods=len(qr_vals), freq="MS")
        frames = {
            "quits_rate":   pd.DataFrame({"ts": ts, "value": qr_vals}),
            "openings_rate":pd.DataFrame({"ts": ts, "value": [3.0]*len(qr_vals)}),
            "unemployment": pd.DataFrame({"ts": ts, "value": [5.0]*len(qr_vals)}),
            "hires": pd.DataFrame({"ts": ts, "value": [5000]*len(qr_vals)}),
            "quits": pd.DataFrame({"ts": ts, "value": [4000]*len(qr_vals)}),
            "job_openings": pd.DataFrame({"ts": ts, "value": [10000]*len(qr_vals)}),
            "layoffs": pd.DataFrame({"ts": ts, "value": [1500]*len(qr_vals)}),
            "hires_rate":   pd.DataFrame({"ts": ts, "value": [3.5]*len(qr_vals)}),
        }
        signal = analyzer._compute_signal(frames)
        # qr_vals[-1]-qr_vals[-4] = 0.6-1.2 = -0.6 < -0.3 → deteriorating
        assert signal.regime == "deteriorating"

    def test_slack_regime(self):
        """quits basso, openings basso, momentum stabile → slack."""
        analyzer, frames = _make_analyzer_with_mocks(
            quits_rate=[1.5]*8, openings_rate=[2.5]*8, unemployment=[6.0]*8
        )
        signal = analyzer._compute_signal(frames)
        assert signal.regime == "slack"


class TestBeveridgeGap:

    def test_positive_gap_hot_market(self):
        """openings_rate > unemployment → gap positivo = mercato surriscaldato."""
        analyzer, frames = _make_analyzer_with_mocks(
            quits_rate=[2.5]*6, openings_rate=[6.0]*6, unemployment=[3.5]*6
        )
        signal = analyzer._compute_signal(frames)
        assert signal.beveridge_gap > 0

    def test_negative_gap_slack_market(self):
        """openings_rate < unemployment → gap negativo = mercato lasco."""
        analyzer, frames = _make_analyzer_with_mocks(
            quits_rate=[1.5]*6, openings_rate=[2.0]*6, unemployment=[7.0]*6
        )
        signal = analyzer._compute_signal(frames)
        assert signal.beveridge_gap < 0

    def test_score_in_range(self):
        """labour_score deve essere in [-1, 1]."""
        analyzer, frames = _make_analyzer_with_mocks(
            quits_rate=[2.5]*8, openings_rate=[5.0]*8, unemployment=[4.0]*8
        )
        signal = analyzer._compute_signal(frames)
        assert -1.0 <= signal.labour_score <= 1.0


class TestQuitsMomentum:

    def test_positive_momentum(self):
        """quits in salita → momentum positivo."""
        import pandas as pd
        analyzer = JOLTSAnalyzer(duckdb=None)
        qr_vals = [1.8, 1.9, 2.0, 2.1, 2.2, 2.4, 2.6, 2.8, 3.0, 3.2, 3.3, 3.4]
        ts = pd.date_range("2023-01-01", periods=len(qr_vals), freq="MS")
        frames = {
            "quits_rate":   pd.DataFrame({"ts": ts, "value": qr_vals}),
            "openings_rate":pd.DataFrame({"ts": ts, "value": [4.5]*len(qr_vals)}),
            "unemployment": pd.DataFrame({"ts": ts, "value": [4.0]*len(qr_vals)}),
            "hires": pd.DataFrame({"ts": ts, "value": [5000]*len(qr_vals)}),
            "quits": pd.DataFrame({"ts": ts, "value": [4000]*len(qr_vals)}),
            "job_openings": pd.DataFrame({"ts": ts, "value": [10000]*len(qr_vals)}),
            "layoffs": pd.DataFrame({"ts": ts, "value": [1500]*len(qr_vals)}),
            "hires_rate":   pd.DataFrame({"ts": ts, "value": [3.5]*len(qr_vals)}),
        }
        signal = analyzer._compute_signal(frames)
        # qr_vals[-1]-qr_vals[-4] = 3.4-2.6 = 0.8 > 0
        assert signal.quits_momentum > 0

    def test_empty_frames_returns_score_zero(self):
        """Frame vuoti → score 0 senza eccezioni."""
        analyzer = JOLTSAnalyzer(duckdb=None)
        signal = analyzer._compute_signal({})
        assert signal.labour_score == 0.0
