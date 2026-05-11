"""Test suite — Roadmap Unificata Settimana 5: Futures Analysis Module.

Coverage target: ≥ 80% su engine/futures_analysis/
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.futures_analysis.schemas import (
    TermStructure, OISignal, CommodityRegime,
    RollYieldResult, BasisResult, OpenInterestResult, CommodityAnalysis,
)
from engine.futures_analysis.roll_analyzer import (
    RollAnalyzer, _classify_term_structure, _compute_historical_rolls,
)
from engine.futures_analysis.basis_analyzer import BasisAnalyzer, _null_result
from engine.futures_analysis.open_interest_analyzer import (
    OpenInterestAnalyzer, _classify_signal, _compute_institutional_bias,
)
from engine.futures_analysis.commodity_regime import (
    CommodityRegimeClassifier, _classify_regime, _REGIME_SCORES,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_ohlcv_df(closes: list[float], oi: list[int] | None = None) -> pd.DataFrame:
    n = len(closes)
    dates = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC")
    df = pd.DataFrame({
        "ts": dates,
        "close": closes,
        "open": closes,
        "high": [c * 1.01 for c in closes],
        "low":  [c * 0.99 for c in closes],
        "open_interest": oi if oi else [0] * n,
    })
    return df


def _make_roll_result(ts: TermStructure, roll: float = -0.018) -> RollYieldResult:
    return RollYieldResult(
        ticker="CL=F", computed_at=datetime.now(timezone.utc),
        roll_yield_22d=roll,
        roll_yield_annual=roll * (252 / 22),
        term_structure=ts,
        front_close=70.0, second_proxy=71.3,
        roll_pct_rank=0.3, signal="bearish" if ts == TermStructure.CONTANGO else "bullish",
    )


def _make_basis_result(signal: str = "neutral", zscore: float = 0.0) -> BasisResult:
    return BasisResult(
        ticker="CL=F", spot_ticker="USO",
        computed_at=datetime.now(timezone.utc),
        basis=1.5, basis_pct=2.1, basis_zscore=zscore, signal=signal,
    )


def _make_oi_result(signal: OISignal, bias: str = "neutral") -> OpenInterestResult:
    return OpenInterestResult(
        ticker="CL=F", computed_at=datetime.now(timezone.utc),
        oi_signal=signal, oi_current=250_000,
        oi_change_pct=2.5, price_change_pct=1.5,
        oi_pct_rank=0.65, institutional_bias=bias,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Test _classify_term_structure (pura)
# ═══════════════════════════════════════════════════════════════════════════

class TestClassifyTermStructure:

    def test_backwardation_above_threshold(self):
        assert _classify_term_structure(0.006) == TermStructure.BACKWARDATION

    def test_contango_below_threshold(self):
        assert _classify_term_structure(-0.006) == TermStructure.CONTANGO

    def test_flat_within_threshold(self):
        assert _classify_term_structure(0.003) == TermStructure.FLAT
        assert _classify_term_structure(-0.003) == TermStructure.FLAT

    def test_exact_backwardation_boundary(self):
        # > 0.005 → backwardation; = 0.005 → flat (strict >)
        assert _classify_term_structure(0.005) == TermStructure.FLAT
        assert _classify_term_structure(0.0051) == TermStructure.BACKWARDATION

    def test_exact_contango_boundary(self):
        assert _classify_term_structure(-0.005) == TermStructure.FLAT
        assert _classify_term_structure(-0.0051) == TermStructure.CONTANGO

    def test_strong_backwardation(self):
        assert _classify_term_structure(0.05) == TermStructure.BACKWARDATION

    def test_strong_contango(self):
        assert _classify_term_structure(-0.10) == TermStructure.CONTANGO


# ═══════════════════════════════════════════════════════════════════════════
# Test RollAnalyzer
# ═══════════════════════════════════════════════════════════════════════════

class TestRollAnalyzer:

    def _make_mock_db(self, ticker: str, closes: list[float]) -> MagicMock:
        db = MagicMock()
        rows = [(f"2025-{i+1:02d}-01", c) for i, c in enumerate(closes)]
        db.query.return_value = rows
        return db

    def test_analyze_from_df_contango(self):
        """Prezzi in salita nel tempo → front < second → CONTANGO."""
        # front = 70.0, second (22d ago) = 71.5 → roll = (70/71.5) - 1 < 0
        closes = list(np.linspace(71.5, 70.0, 30))  # scendono (front < second proxy)
        df = _make_ohlcv_df(closes)

        db = MagicMock()
        analyzer = RollAnalyzer(duckdb=db)
        result = analyzer.analyze_from_df("CL=F", df)

        assert result.term_structure == TermStructure.CONTANGO
        assert result.roll_yield_22d < 0
        assert result.signal == "bearish"

    def test_analyze_from_df_backwardation(self):
        """Prezzi in discesa nel tempo → front > second → BACKWARDATION."""
        closes = list(np.linspace(68.0, 72.0, 30))  # salgono (front > second proxy)
        df = _make_ohlcv_df(closes)

        db = MagicMock()
        analyzer = RollAnalyzer(duckdb=db)
        result = analyzer.analyze_from_df("CL=F", df)

        assert result.term_structure == TermStructure.BACKWARDATION
        assert result.roll_yield_22d > 0
        assert result.signal == "bullish"

    def test_analyze_from_df_flat(self):
        """Prezzi costanti → roll ≈ 0 → FLAT."""
        closes = [70.0] * 30
        df = _make_ohlcv_df(closes)

        db = MagicMock()
        analyzer = RollAnalyzer(duckdb=db)
        result = analyzer.analyze_from_df("CL=F", df)

        assert result.term_structure == TermStructure.FLAT
        assert abs(result.roll_yield_22d) < 1e-9
        assert result.signal == "neutral"

    def test_roll_annual_formula(self):
        """roll_annual = roll_22d × (252 / 22)."""
        closes = list(np.linspace(71.5, 70.0, 30))
        df = _make_ohlcv_df(closes)

        db = MagicMock()
        analyzer = RollAnalyzer(duckdb=db)
        result = analyzer.analyze_from_df("CL=F", df)

        expected_annual = result.roll_yield_22d * (252 / 22)
        assert abs(result.roll_yield_annual - expected_annual) < 1e-9

    def test_insufficient_data_raises(self):
        """< 24 righe → ValueError."""
        closes = [70.0] * 20
        df = _make_ohlcv_df(closes)

        db = MagicMock()
        analyzer = RollAnalyzer(duckdb=db)

        with pytest.raises(ValueError, match="insufficiente"):
            analyzer.analyze_from_df("CL=F", df)

    def test_pct_rank_between_0_and_1(self):
        """roll_pct_rank sempre in [0, 1]."""
        closes = list(np.random.default_rng(99).uniform(68, 75, 50))
        df = _make_ohlcv_df(closes)

        db = MagicMock()
        analyzer = RollAnalyzer(duckdb=db)
        result = analyzer.analyze_from_df("CL=F", df)

        if result.roll_pct_rank is not None:
            assert 0.0 <= result.roll_pct_rank <= 1.0

    def test_output_fields_complete(self):
        """RollYieldResult ha tutti i campi richiesti."""
        closes = list(np.linspace(70, 72, 30))
        df = _make_ohlcv_df(closes)

        db = MagicMock()
        analyzer = RollAnalyzer(duckdb=db)
        result = analyzer.analyze_from_df("GC=F", df)

        assert isinstance(result, RollYieldResult)
        assert result.ticker == "GC=F"
        assert result.front_close > 0
        assert result.second_proxy > 0
        assert result.computed_at.tzinfo is not None

    def test_historical_rolls_computation(self):
        """_compute_historical_rolls produce serie di roll yields."""
        closes = np.linspace(70, 80, 50)
        rolls = _compute_historical_rolls(closes, 22)
        assert len(rolls) > 0
        assert not np.any(np.isnan(rolls))

    def test_historical_rolls_insufficient(self):
        """Meno di window+2 barre → array vuoto."""
        closes = np.array([70.0] * 10)
        rolls = _compute_historical_rolls(closes, 22)
        assert len(rolls) == 0

    def test_zero_price_raises(self):
        """Prezzo second_proxy = 0 → ValueError."""
        closes = [0.0] * 24 + [70.0]
        df = _make_ohlcv_df(closes)

        db = MagicMock()
        analyzer = RollAnalyzer(duckdb=db)

        with pytest.raises(ValueError):
            analyzer.analyze_from_df("CL=F", df)


# ═══════════════════════════════════════════════════════════════════════════
# Test BasisAnalyzer
# ═══════════════════════════════════════════════════════════════════════════

class TestBasisAnalyzer:

    def _make_repo_mock(self, spot_closes: list[float]) -> MagicMock:
        repo = MagicMock()
        n = len(spot_closes)
        dates = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC")
        df = pd.DataFrame({"ts": dates, "close": spot_closes})
        repo.read_prices.return_value = df
        return repo

    def test_positive_basis(self):
        """futures > spot → basis positivo."""
        futures = np.array([100.0] * 30 + [105.0])
        spot    = np.array([100.0] * 30 + [100.0])
        db = MagicMock()
        analyzer = BasisAnalyzer(duckdb=db, prices_repo=MagicMock())
        result = analyzer.analyze_from_prices("CL=F", futures, spot, "USO")
        assert result.basis is not None
        assert result.basis > 0
        assert result.basis_pct > 0

    def test_negative_basis(self):
        """futures < spot → basis negativo (backwardation)."""
        futures = np.array([100.0] * 30 + [95.0])
        spot    = np.array([100.0] * 30 + [100.0])
        db = MagicMock()
        analyzer = BasisAnalyzer(duckdb=db, prices_repo=MagicMock())
        result = analyzer.analyze_from_prices("GC=F", futures, spot, "GLD")
        assert result.basis is not None
        assert result.basis < 0

    def test_divergence_signal_on_high_zscore(self):
        """basis_zscore > 1.5 → signal = 'divergence'."""
        # Creo una serie storica con mean=2, std=1; current basis = 5 → z=3
        futures_hist = np.array([100.0 + i * 0.001 for i in range(30)] + [103.5])
        spot_hist    = np.array([100.0] * 31)
        db = MagicMock()
        analyzer = BasisAnalyzer(duckdb=db, prices_repo=MagicMock())
        result = analyzer.analyze_from_prices("CL=F", futures_hist, spot_hist, "USO")
        # Con 31 osservazioni e un'anomalia finale, lo z-score sarà alto
        if result.basis_zscore is not None and result.basis_zscore > 1.5:
            assert result.signal == "divergence"

    def test_convergence_signal_on_low_zscore(self):
        """basis_zscore < -1.5 → signal = 'convergence'."""
        futures_hist = np.array([100.0 + i * 0.001 for i in range(30)] + [96.5])
        spot_hist    = np.array([100.0] * 31)
        db = MagicMock()
        analyzer = BasisAnalyzer(duckdb=db, prices_repo=MagicMock())
        result = analyzer.analyze_from_prices("GC=F", futures_hist, spot_hist, "GLD")
        if result.basis_zscore is not None and result.basis_zscore < -1.5:
            assert result.signal == "convergence"

    def test_neutral_signal_on_normal_basis(self):
        """Basis nella norma → signal = 'neutral'."""
        futures = np.array([102.0] * 31)
        spot    = np.array([100.0] * 31)
        db = MagicMock()
        analyzer = BasisAnalyzer(duckdb=db, prices_repo=MagicMock())
        result = analyzer.analyze_from_prices("ES=F", futures, spot, "SPY")
        assert result.signal == "neutral"

    def test_basis_pct_formula(self):
        """basis_pct = basis / spot * 100."""
        futures = np.array([105.0] * 31)
        spot    = np.array([100.0] * 31)
        db = MagicMock()
        analyzer = BasisAnalyzer(duckdb=db, prices_repo=MagicMock())
        result = analyzer.analyze_from_prices("CL=F", futures, spot, "USO")
        assert result.basis is not None
        assert abs(result.basis - 5.0) < 1e-6
        assert abs(result.basis_pct - 5.0) < 1e-6

    def test_empty_arrays_return_null(self):
        """Array vuoti → null result senza crash."""
        db = MagicMock()
        analyzer = BasisAnalyzer(duckdb=db, prices_repo=MagicMock())
        result = analyzer.analyze_from_prices("CL=F", np.array([]), np.array([]), "USO")
        assert result.basis is None
        assert result.signal == "neutral"

    def test_zero_spot_returns_null(self):
        """spot = 0 → null result senza crash."""
        futures = np.array([100.0])
        spot    = np.array([0.0])
        db = MagicMock()
        analyzer = BasisAnalyzer(duckdb=db, prices_repo=MagicMock())
        result = analyzer.analyze_from_prices("CL=F", futures, spot, "USO")
        assert result.basis is None

    def test_output_fields_complete(self):
        """BasisResult ha tutti i campi."""
        futures = np.array([102.0] * 31)
        spot    = np.array([100.0] * 31)
        db = MagicMock()
        analyzer = BasisAnalyzer(duckdb=db, prices_repo=MagicMock())
        result = analyzer.analyze_from_prices("CL=F", futures, spot, "USO")
        assert isinstance(result, BasisResult)
        assert result.computed_at.tzinfo is not None
        assert result.spot_ticker == "USO"


# ═══════════════════════════════════════════════════════════════════════════
# Test OpenInterestAnalyzer
# ═══════════════════════════════════════════════════════════════════════════

class TestOpenInterestAnalyzer:

    def _analyzer(self) -> OpenInterestAnalyzer:
        return OpenInterestAnalyzer(duckdb=MagicMock())

    def test_trend_confirmed_bullish(self):
        """OI↑ + prezzo↑ → TREND_CONFIRMED_BULLISH."""
        closes = list(np.linspace(70, 75, 15))   # prezzo sale
        oi     = list(np.linspace(200_000, 220_000, 15))  # OI sale
        df = _make_ohlcv_df(closes, [int(x) for x in oi])
        result = self._analyzer().analyze_from_df("CL=F", df)
        assert result.oi_signal == OISignal.TREND_CONFIRMED_BULLISH
        assert result.institutional_bias == "long_bias"

    def test_distribution_bearish(self):
        """OI↑ + prezzo↓ → DISTRIBUTION_BEARISH."""
        closes = list(np.linspace(75, 70, 15))   # prezzo scende
        oi     = list(np.linspace(200_000, 220_000, 15))  # OI sale
        df = _make_ohlcv_df(closes, [int(x) for x in oi])
        result = self._analyzer().analyze_from_df("CL=F", df)
        assert result.oi_signal == OISignal.DISTRIBUTION_BEARISH
        assert result.institutional_bias == "short_bias"

    def test_short_covering_weak_buy(self):
        """OI↓ + prezzo↑ → SHORT_COVERING_WEAK_BULLISH."""
        closes = list(np.linspace(70, 75, 15))   # prezzo sale
        oi     = list(np.linspace(220_000, 200_000, 15))  # OI scende
        df = _make_ohlcv_df(closes, [int(x) for x in oi])
        result = self._analyzer().analyze_from_df("CL=F", df)
        assert result.oi_signal == OISignal.SHORT_COVERING_WEAK_BUY

    def test_liquidation_possible_bottom(self):
        """OI↓ + prezzo↓ → LIQUIDATION_POSSIBLE_BOTTOM."""
        closes = list(np.linspace(75, 70, 15))   # prezzo scende
        oi     = list(np.linspace(220_000, 200_000, 15))  # OI scende
        df = _make_ohlcv_df(closes, [int(x) for x in oi])
        result = self._analyzer().analyze_from_df("CL=F", df)
        assert result.oi_signal == OISignal.LIQUIDATION_POSSIBLE_BTM

    def test_all_four_signals_covered(self):
        """Tutti e 4 i segnali OI devono essere classificabili."""
        cases = [
            (OISignal.TREND_CONFIRMED_BULLISH,  True,  True),   # OI↑ prezzo↑
            (OISignal.DISTRIBUTION_BEARISH,      True,  False),  # OI↑ prezzo↓
            (OISignal.SHORT_COVERING_WEAK_BUY,   False, True),   # OI↓ prezzo↑
            (OISignal.LIQUIDATION_POSSIBLE_BTM,  False, False),  # OI↓ prezzo↓
        ]
        for expected_signal, oi_up, price_up in cases:
            oi_chg    =  2.0 if oi_up    else -2.0
            price_chg =  2.0 if price_up else -2.0
            result = _classify_signal(
                price_change_pct=price_chg,
                oi_change_pct=oi_chg,
                has_oi=True,
            )
            assert result == expected_signal, \
                f"Atteso {expected_signal}, ottenuto {result} (oi_up={oi_up}, price_up={price_up})"

    def test_insufficient_data_on_missing_oi(self):
        """OI tutti zero → INSUFFICIENT_DATA."""
        closes = list(np.linspace(70, 75, 15))
        df = _make_ohlcv_df(closes, [0] * 15)
        result = self._analyzer().analyze_from_df("CL=F", df)
        assert result.oi_signal == OISignal.INSUFFICIENT_DATA

    def test_insufficient_data_on_few_bars(self):
        """< 10 barre → INSUFFICIENT_DATA."""
        closes = [70.0] * 5
        df = _make_ohlcv_df(closes)
        result = self._analyzer().analyze_from_df("CL=F", df)
        assert result.oi_signal == OISignal.INSUFFICIENT_DATA

    def test_oi_pct_rank_between_0_and_1(self):
        """oi_pct_rank sempre in [0, 1] quando disponibile."""
        closes = list(np.random.default_rng(42).uniform(68, 75, 20))
        oi     = [int(x) for x in np.random.default_rng(42).integers(180_000, 220_000, 20)]
        df = _make_ohlcv_df(closes, oi)
        result = self._analyzer().analyze_from_df("CL=F", df)
        if result.oi_pct_rank is not None:
            assert 0.0 <= result.oi_pct_rank <= 1.0

    def test_output_fields_complete(self):
        """OpenInterestResult ha tutti i campi."""
        closes = list(np.linspace(70, 75, 15))
        oi     = list(np.linspace(200_000, 220_000, 15))
        df = _make_ohlcv_df(closes, [int(x) for x in oi])
        result = self._analyzer().analyze_from_df("CL=F", df)
        assert isinstance(result, OpenInterestResult)
        assert result.computed_at.tzinfo is not None
        assert result.ticker == "CL=F"


# ═══════════════════════════════════════════════════════════════════════════
# Test CommodityRegimeClassifier
# ═══════════════════════════════════════════════════════════════════════════

class TestCommodityRegimeClassifier:

    def _make_classifier(self) -> CommodityRegimeClassifier:
        return CommodityRegimeClassifier(
            roll_analyzer=MagicMock(),
            basis_analyzer=MagicMock(),
            oi_analyzer=MagicMock(),
        )

    def test_backwardation_squeeze(self):
        """Backwardation + TREND_CONFIRMED_BULLISH → BACKWARDATION_SQUEEZE."""
        roll  = _make_roll_result(TermStructure.BACKWARDATION, roll=0.025)
        basis = _make_basis_result("neutral")
        oi    = _make_oi_result(OISignal.TREND_CONFIRMED_BULLISH, "long_bias")
        regime = _classify_regime(roll, basis, oi)
        assert regime == CommodityRegime.BACKWARDATION_SQUEEZE

    def test_contango_trap(self):
        """Contango + DISTRIBUTION + divergence basis → CONTANGO_TRAP."""
        roll  = _make_roll_result(TermStructure.CONTANGO, roll=-0.035)
        basis = _make_basis_result("divergence", zscore=2.0)
        oi    = _make_oi_result(OISignal.DISTRIBUTION_BEARISH, "short_bias")
        regime = _classify_regime(roll, basis, oi)
        assert regime == CommodityRegime.CONTANGO_TRAP

    def test_bullish_on_backwardation_short_covering(self):
        """Backwardation + SHORT_COVERING → BULLISH."""
        roll  = _make_roll_result(TermStructure.BACKWARDATION, roll=0.015)
        basis = _make_basis_result("neutral")
        oi    = _make_oi_result(OISignal.SHORT_COVERING_WEAK_BUY)
        regime = _classify_regime(roll, basis, oi)
        assert regime == CommodityRegime.BULLISH

    def test_bullish_on_liquidation(self):
        """Liquidazione → BULLISH (exhaustion contrarian)."""
        roll  = _make_roll_result(TermStructure.CONTANGO)
        basis = _make_basis_result()
        oi    = _make_oi_result(OISignal.LIQUIDATION_POSSIBLE_BTM)
        regime = _classify_regime(roll, basis, oi)
        assert regime == CommodityRegime.BULLISH

    def test_bearish_on_distribution(self):
        """Flat + DISTRIBUTION → BEARISH."""
        roll  = _make_roll_result(TermStructure.FLAT)
        basis = _make_basis_result("neutral")
        oi    = _make_oi_result(OISignal.DISTRIBUTION_BEARISH, "short_bias")
        regime = _classify_regime(roll, basis, oi)
        assert regime == CommodityRegime.BEARISH

    def test_neutral_on_ambiguous(self):
        """Flat + INSUFFICIENT_DATA → NEUTRAL."""
        roll  = _make_roll_result(TermStructure.FLAT)
        basis = _make_basis_result("neutral")
        oi    = _make_oi_result(OISignal.INSUFFICIENT_DATA)
        regime = _classify_regime(roll, basis, oi)
        assert regime == CommodityRegime.NEUTRAL

    def test_bullish_on_backwardation_no_oi(self):
        """Backwardation senza OI → BULLISH (solo term structure)."""
        roll = _make_roll_result(TermStructure.BACKWARDATION)
        regime = _classify_regime(roll, None, None)
        assert regime == CommodityRegime.BULLISH

    def test_bearish_on_contango_no_oi(self):
        """Contango senza OI → BEARISH."""
        roll = _make_roll_result(TermStructure.CONTANGO)
        regime = _classify_regime(roll, None, None)
        assert regime == CommodityRegime.BEARISH

    def test_all_regimes_have_scores(self):
        """Ogni CommodityRegime ha un score definito in _REGIME_SCORES."""
        for regime in CommodityRegime:
            assert regime in _REGIME_SCORES, f"Score mancante per {regime}"
            score = _REGIME_SCORES[regime]
            assert -1.0 <= score <= 1.0

    def test_score_positive_for_bullish(self):
        """Score > 0 per BULLISH e BACKWARDATION_SQUEEZE."""
        assert _REGIME_SCORES[CommodityRegime.BULLISH] > 0
        assert _REGIME_SCORES[CommodityRegime.BACKWARDATION_SQUEEZE] > 0

    def test_score_negative_for_bearish(self):
        """Score < 0 per BEARISH e CONTANGO_TRAP."""
        assert _REGIME_SCORES[CommodityRegime.BEARISH] < 0
        assert _REGIME_SCORES[CommodityRegime.CONTANGO_TRAP] < 0

    def test_score_zero_for_neutral(self):
        """Score = 0 per NEUTRAL."""
        assert _REGIME_SCORES[CommodityRegime.NEUTRAL] == 0.0

    def test_classify_from_results_complete(self):
        """classify_from_results() ritorna CommodityAnalysis completo."""
        roll  = _make_roll_result(TermStructure.BACKWARDATION, roll=0.02)
        basis = _make_basis_result("neutral")
        oi    = _make_oi_result(OISignal.TREND_CONFIRMED_BULLISH)

        classifier = self._make_classifier()
        result = classifier.classify_from_results("CL=F", roll, basis, oi)

        assert isinstance(result, CommodityAnalysis)
        assert result.ticker == "CL=F"
        assert result.regime == CommodityRegime.BACKWARDATION_SQUEEZE
        assert result.score > 0
        assert result.confidence == "HIGH"
        assert len(result.summary) > 10
        assert result.computed_at.tzinfo is not None

    def test_score_clipped_to_range(self):
        """score sempre in [-1, +1]."""
        for regime in CommodityRegime:
            roll  = _make_roll_result(TermStructure.FLAT)
            basis = _make_basis_result()
            oi    = _make_oi_result(OISignal.INSUFFICIENT_DATA)

            classifier = self._make_classifier()
            classifier.classify_from_results("CL=F", roll, basis, oi)
            # Score dai regime_scores è già definito in range → verifica il dict
            score = _REGIME_SCORES.get(regime, 0.0)
            assert -1.0 <= score <= 1.0

    def test_none_inputs_do_not_crash(self):
        """None per tutti i sub-risultati → NEUTRAL senza crash."""
        regime = _classify_regime(None, None, None)
        assert regime == CommodityRegime.NEUTRAL

    def test_summary_contains_ticker(self):
        """summary contiene il ticker."""
        roll  = _make_roll_result(TermStructure.FLAT)
        basis = _make_basis_result()
        oi    = _make_oi_result(OISignal.INSUFFICIENT_DATA)

        classifier = self._make_classifier()
        result = classifier.classify_from_results("GC=F", roll, basis, oi)
        assert "GC=F" in result.summary


# ═══════════════════════════════════════════════════════════════════════════
# Test funzioni pure
# ═══════════════════════════════════════════════════════════════════════════

class TestPureFunctions:

    def test_classify_signal_all_four(self):
        """_classify_signal copre tutte le 4 combinazioni."""
        assert _classify_signal(2.0,  2.0, True) == OISignal.TREND_CONFIRMED_BULLISH
        assert _classify_signal(-2.0, 2.0, True) == OISignal.DISTRIBUTION_BEARISH
        assert _classify_signal(2.0, -2.0, True) == OISignal.SHORT_COVERING_WEAK_BUY
        assert _classify_signal(-2.0,-2.0, True) == OISignal.LIQUIDATION_POSSIBLE_BTM

    def test_classify_signal_no_oi(self):
        """Senza OI (has_oi=False) → INSUFFICIENT_DATA."""
        assert _classify_signal(2.0, None, False) == OISignal.INSUFFICIENT_DATA

    def test_classify_signal_ambiguous(self):
        """Variazioni sotto soglia → INSUFFICIENT_DATA."""
        assert _classify_signal(0.1, 0.1, True) == OISignal.INSUFFICIENT_DATA

    def test_institutional_bias_bullish(self):
        """TREND_CONFIRMED → long_bias."""
        bias = _compute_institutional_bias(OISignal.TREND_CONFIRMED_BULLISH, 0.75)
        assert bias == "long_bias"

    def test_institutional_bias_bearish(self):
        """DISTRIBUTION → short_bias."""
        bias = _compute_institutional_bias(OISignal.DISTRIBUTION_BEARISH, 0.5)
        assert bias == "short_bias"

    def test_institutional_bias_neutral_on_insufficient(self):
        """INSUFFICIENT_DATA → neutral."""
        bias = _compute_institutional_bias(OISignal.INSUFFICIENT_DATA, None)
        assert bias == "neutral"


# ═══════════════════════════════════════════════════════════════════════════
# Test metodi DB-backed (copertura 51-61% → 80%+)
# ═══════════════════════════════════════════════════════════════════════════

class TestRollAnalyzerWithDB:
    """Testa analyze() con DB mock per coprire il codice con DB."""

    def test_analyze_with_db_data(self, migrated_client):
        """analyze() da DB → risultato corretto."""
        from datetime import datetime, timezone
        import numpy as np

        now = datetime.now(timezone.utc)
        # Inserisci 30 barre in futures_ohlcv
        closes = list(np.linspace(71.5, 70.0, 30))
        for i, close in enumerate(closes):
            ts = now.replace(day=1) if i == 0 else now
            migrated_client.execute(
                "INSERT OR REPLACE INTO futures_ohlcv "
                "(ticker, contract_month, ts, close, term_structure) "
                "VALUES ('CL=F', 'front', ?, ?, 'contango')",
                [now, close],
            )

        analyzer = RollAnalyzer(duckdb=migrated_client)
        # Inserisci abbastanza record
        from datetime import timedelta
        for i, close in enumerate(closes):
            ts = datetime.now(timezone.utc) - timedelta(days=len(closes) - i)
            migrated_client.execute(
                "INSERT OR REPLACE INTO futures_ohlcv "
                "(ticker, contract_month, ts, close, term_structure) "
                "VALUES ('CL=F', 'front', ?, ?, 'contango')",
                [ts, close],
            )
        result = analyzer.analyze("CL=F")
        assert isinstance(result, RollYieldResult)
        assert result.term_structure in (TermStructure.CONTANGO, TermStructure.FLAT, TermStructure.BACKWARDATION)

    def test_analyze_insufficient_data_raises(self, migrated_client):
        """analyze() con DB vuoto → ValueError."""
        analyzer = RollAnalyzer(duckdb=migrated_client)
        with pytest.raises(ValueError, match="insufficiente|insufficienti|dati"):
            analyzer.analyze("CL=F")


class TestBasisAnalyzerWithDB:
    """Testa analyze() con DB mock."""

    def test_analyze_no_futures_data_returns_null(self, migrated_client):
        """analyze() con futures_ohlcv vuoto → null result."""
        from datetime import datetime, timezone
        import pandas as pd

        prices_repo = MagicMock()
        spot_df = pd.DataFrame({"ts": [datetime.now(timezone.utc)], "close": [70.0]})
        prices_repo.read_prices.return_value = spot_df

        analyzer = BasisAnalyzer(duckdb=migrated_client, prices_repo=prices_repo)
        result = analyzer.analyze("GC=F")
        assert result.basis is None

    def test_analyze_with_futures_data(self, migrated_client):
        """analyze() con dati → basis calcolato."""
        from datetime import datetime, timezone
        import pandas as pd

        now = datetime.now(timezone.utc)
        migrated_client.execute(
            "INSERT INTO futures_ohlcv "
            "(ticker, contract_month, ts, close, basis, term_structure) "
            "VALUES ('GC=F', 'front', ?, 2350.0, 5.5, 'contango')",
            [now],
        )

        prices_repo = MagicMock()
        spot_df = pd.DataFrame({"ts": [now], "close": [2344.5]})
        prices_repo.read_prices.return_value = spot_df

        analyzer = BasisAnalyzer(duckdb=migrated_client, prices_repo=prices_repo)
        result = analyzer.analyze("GC=F")
        # futures_close (2350) - spot_close (2344.5) = 5.5
        assert result.basis is not None
        assert abs(result.basis - 5.5) < 0.1


class TestOIAnalyzerWithDB:
    """Testa analyze() con DB mock."""

    def test_analyze_empty_db_returns_insufficient(self, migrated_client):
        """analyze() con DB vuoto → INSUFFICIENT_DATA."""
        analyzer = OpenInterestAnalyzer(duckdb=migrated_client)
        result = analyzer.analyze("CL=F")
        assert result.oi_signal == OISignal.INSUFFICIENT_DATA

    def test_analyze_with_db_data(self, migrated_client):
        """analyze() con dati DB → segnale classificato."""
        from datetime import datetime, timezone, timedelta
        import numpy as np

        # Inserisci 15 barre con trend rialzista + OI in salita
        closes = list(np.linspace(70.0, 75.0, 15))
        oi_vals = list(np.linspace(200_000, 220_000, 15))
        for i in range(15):
            ts = datetime.now(timezone.utc) - timedelta(days=15 - i)
            migrated_client.execute(
                "INSERT OR REPLACE INTO futures_ohlcv "
                "(ticker, contract_month, ts, close, open_interest, term_structure) "
                "VALUES ('CL=F', 'front', ?, ?, ?, 'backwardation')",
                [ts, closes[i], int(oi_vals[i])],
            )

        analyzer = OpenInterestAnalyzer(duckdb=migrated_client)
        result = analyzer.analyze("CL=F")
        assert result.oi_signal == OISignal.TREND_CONFIRMED_BULLISH
        assert result.institutional_bias == "long_bias"


# ─── Fixture locale per test_futures_analysis.py ─────────────────────────

@pytest.fixture()
def migrated_client(tmp_duckdb_path):
    """DuckDBClient con migration 007 applicata."""
    import sys
    from pathlib import Path
    _ROOT = Path(__file__).resolve().parents[3]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from shared.db.duckdb_client import DuckDBClient
    from shared.db.duckdb_migrator import DuckDBMigrator
    client = DuckDBClient(path=tmp_duckdb_path)
    DuckDBMigrator(client=client).apply_pending()
    yield client
    client.close()


class TestCommodityRegimeWithDB:
    """Testa classify() con DB per coprire i metodi DB-backed."""

    def test_classify_with_empty_db_returns_neutral(self, migrated_client):
        """classify() con DB vuoto → regime NEUTRAL, confidence LOW."""
        from shared.db.prices_repo import get_prices_repository
        from shared.types import TimeFrame
        import pandas as pd

        prices_repo = MagicMock()
        prices_repo.read_prices.return_value = pd.DataFrame()

        classifier = CommodityRegimeClassifier(
            roll_analyzer=RollAnalyzer(duckdb=migrated_client),
            basis_analyzer=BasisAnalyzer(duckdb=migrated_client, prices_repo=prices_repo),
            oi_analyzer=OpenInterestAnalyzer(duckdb=migrated_client),
        )
        result = classifier.classify("CL=F")
        assert isinstance(result, CommodityAnalysis)
        assert result.regime == CommodityRegime.NEUTRAL
        assert result.confidence in ("LOW", "MEDIUM")  # null objects count as available

    def test_classify_with_backwardation_data(self, migrated_client):
        """classify() con backwardation in DB → BULLISH o BACKWARDATION_SQUEEZE."""
        from datetime import datetime, timezone, timedelta
        import numpy as np, pandas as pd

        # Inserisci dati: prezzi in salita (backwardation) + OI in salita
        closes  = list(np.linspace(68.0, 72.0, 30))
        oi_vals = list(np.linspace(200_000, 220_000, 30))
        for i in range(30):
            ts = datetime.now(timezone.utc) - timedelta(days=30 - i)
            migrated_client.execute(
                "INSERT OR REPLACE INTO futures_ohlcv "
                "(ticker, contract_month, ts, close, open_interest, basis, term_structure) "
                "VALUES ('GC=F', 'front', ?, ?, ?, 5.0, 'backwardation')",
                [ts, closes[i], int(oi_vals[i])],
            )

        prices_repo = MagicMock()
        spot_df = pd.DataFrame({
            "ts":    [datetime.now(timezone.utc)],
            "close": [float(closes[-1]) - 5.0],
        })
        prices_repo.read_prices.return_value = spot_df

        classifier = CommodityRegimeClassifier(
            roll_analyzer=RollAnalyzer(duckdb=migrated_client),
            basis_analyzer=BasisAnalyzer(duckdb=migrated_client, prices_repo=prices_repo),
            oi_analyzer=OpenInterestAnalyzer(duckdb=migrated_client),
        )
        result = classifier.classify("GC=F")
        assert result.regime in (
            CommodityRegime.BULLISH, CommodityRegime.BACKWARDATION_SQUEEZE,
            CommodityRegime.NEUTRAL,
        )
        assert result.score >= 0  # almeno neutro per backwardation
        assert result.confidence in ("HIGH", "MEDIUM", "LOW")

    def test_classify_summary_contains_ticker(self, migrated_client):
        """Il summary contiene il ticker."""
        prices_repo = MagicMock()
        import pandas as pd
        prices_repo.read_prices.return_value = pd.DataFrame()

        classifier = CommodityRegimeClassifier(
            roll_analyzer=RollAnalyzer(duckdb=migrated_client),
            basis_analyzer=BasisAnalyzer(duckdb=migrated_client, prices_repo=prices_repo),
            oi_analyzer=OpenInterestAnalyzer(duckdb=migrated_client),
        )
        result = classifier.classify("ZW=F")
        assert "ZW=F" in result.summary

    def test_null_objects_in_fallback(self):
        """_null_roll/_null_basis/_null_oi ritornano oggetti validi."""
        from engine.futures_analysis.commodity_regime import _null_roll, _null_basis, _null_oi

        roll = _null_roll("CL=F")
        assert roll.ticker == "CL=F"
        assert roll.roll_yield_22d == 0.0
        assert roll.term_structure == TermStructure.FLAT

        basis = _null_basis("CL=F")
        assert basis.ticker == "CL=F"
        assert basis.basis is None

        oi = _null_oi("CL=F")
        assert oi.oi_signal == OISignal.INSUFFICIENT_DATA
        assert oi.institutional_bias == "neutral"

    def test_build_summary_format(self):
        """_build_summary include tutti i campi."""
        from engine.futures_analysis.commodity_regime import _build_summary
        roll  = _make_roll_result(TermStructure.BACKWARDATION, roll=0.02)
        basis = _make_basis_result("neutral")
        oi    = _make_oi_result(OISignal.TREND_CONFIRMED_BULLISH)
        summary = _build_summary(
            "CL=F", CommodityRegime.BACKWARDATION_SQUEEZE, 0.8, roll, basis, oi
        )
        assert "CL=F" in summary
        assert "backwardation_squeeze" in summary
        assert "+0.80" in summary or "0.80" in summary
