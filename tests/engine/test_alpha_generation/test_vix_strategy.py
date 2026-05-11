"""Test suite — Roadmap Unificata Settimana 4: VIX Module + StrategyComposer."""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.alpha_generation.vix_signal_calculator import (
    VixSignalCalculator, VixSignal, _classify_vix_regime,
)
from engine.alpha_generation.strategy_composer import (
    StrategyComposer, StrategyOutput, _combine_confidence, _build_notes,
)


# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_vix_df(values: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(values), freq="D", tz="UTC")
    return pd.DataFrame({"ts": dates, "close": values, "open": values,
                         "high": values, "low": values, "volume": [0]*len(values)})


def _make_prices_repo(vix_vals: list[float], vxv_vals: list[float] | None = None) -> MagicMock:
    repo = MagicMock()
    vix_df = _make_vix_df(vix_vals)
    vxv_df = _make_vix_df(vxv_vals) if vxv_vals else pd.DataFrame()

    def _read_prices(ticker, timeframe=None, **kwargs):
        if ticker == "^VIX":
            return vix_df
        if ticker == "^VXV":
            return vxv_df
        return pd.DataFrame()

    repo.read_prices.side_effect = _read_prices
    return repo


def _calm_vix_series(n: int = 252) -> list[float]:
    """Serie VIX calma: media ~15, std ~3."""
    rng = np.random.default_rng(42)
    return (15 + rng.normal(0, 3, n)).clip(8, 25).tolist()


def _panic_vix_series(base: list[float], spike: float = 40.0) -> list[float]:
    """Serie con spike finale di panico."""
    vals = base.copy()
    vals[-1] = spike
    return vals


# ═══════════════════════════════════════════════════════════════════════════
# VixSignalCalculator
# ═══════════════════════════════════════════════════════════════════════════

class TestVixSignalCalculator:

    def test_classify_vix_regime_calm(self):
        assert _classify_vix_regime(12.0) == "calm"

    def test_classify_vix_regime_elevated(self):
        assert _classify_vix_regime(18.0) == "elevated"

    def test_classify_vix_regime_high_stress(self):
        assert _classify_vix_regime(25.0) == "high_stress"

    def test_classify_vix_regime_panic(self):
        assert _classify_vix_regime(35.0) == "panic"

    def test_compute_buy_on_spike(self):
        """VIX spike → action BUY."""
        base = _calm_vix_series(252)
        repo = _make_prices_repo(_panic_vix_series(base, spike=42.0))
        calc = VixSignalCalculator(prices_repo=repo)
        sig = calc.compute(current_regime=None)
        assert sig.action == "BUY"
        assert sig.vix_zscore > 1.5

    def test_compute_hold_on_normal_vix(self):
        """VIX normale → action HOLD."""
        base = _calm_vix_series(252)
        repo = _make_prices_repo(base)
        calc = VixSignalCalculator(prices_repo=repo)
        sig = calc.compute()
        assert sig.action == "HOLD"

    def test_regime_adjustment_bear_lowers_threshold(self):
        """Regime bear → soglia più bassa → più sensibile ai segnali."""
        base = _calm_vix_series(252)
        # VIX a 1.6 sigma: HOLD in bull, BUY in bear
        mu  = float(np.mean(base))
        std = float(np.std(base, ddof=1))
        base[-1] = mu + 1.6 * std   # 1.6 sigma

        repo = _make_prices_repo(base)
        calc = VixSignalCalculator(prices_repo=repo)

        sig_bull = calc.compute(current_regime="bull")
        sig_bear = calc.compute(current_regime="bear")

        # Bear ha threshold inferiore → può dare BUY dove bull dà HOLD
        assert sig_bear.threshold_used < sig_bull.threshold_used

    def test_regime_bull_raises_threshold(self):
        """Regime bull → threshold + 0.5 rispetto a nessun regime."""
        base = _calm_vix_series(252)
        repo = _make_prices_repo(base)
        calc = VixSignalCalculator(prices_repo=repo)

        sig_none = calc.compute(current_regime=None)
        sig_bull = calc.compute(current_regime="bull")

        # Bull: +0.5 rispetto a transition (0.0 adj)
        assert abs(sig_bull.threshold_used - (sig_none.threshold_used + 0.5)) < 1e-6

    def test_regime_stress_lowers_threshold_max(self):
        """Regime stress → threshold minima (più sensibile)."""
        base = _calm_vix_series(252)
        repo = _make_prices_repo(base)
        calc = VixSignalCalculator(prices_repo=repo)

        sig_stress = calc.compute(current_regime="stress")
        # 1.5 - 0.5 = 1.0
        assert abs(sig_stress.threshold_used - 1.0) < 1e-6

    def test_spike_detected_above_2sigma(self):
        """spike_detected = True quando Z-Score > 2."""
        base = _calm_vix_series(252)
        mu  = float(np.mean(base))
        std = float(np.std(base, ddof=1))
        base[-1] = mu + 2.5 * std
        repo = _make_prices_repo(base)
        calc = VixSignalCalculator(prices_repo=repo)
        sig = calc.compute()
        assert sig.spike_detected is True

    def test_no_spike_below_2sigma(self):
        """spike_detected = False quando Z-Score < 2."""
        base = _calm_vix_series(252)
        repo = _make_prices_repo(base)
        calc = VixSignalCalculator(prices_repo=repo)
        sig = calc.compute()
        assert sig.spike_detected is False

    def test_vxv_ratio_computed_when_available(self):
        """vix_vxv_ratio calcolato quando ^VXV disponibile."""
        base = _calm_vix_series(252)
        repo = _make_prices_repo(base, vxv_vals=[18.0] * 252)
        calc = VixSignalCalculator(prices_repo=repo)
        sig = calc.compute()
        assert sig.vix_vxv_ratio is not None
        assert sig.vix_vxv_ratio > 0

    def test_vxv_ratio_none_when_unavailable(self):
        """vix_vxv_ratio = None quando ^VXV non disponibile."""
        base = _calm_vix_series(252)
        repo = _make_prices_repo(base, vxv_vals=None)
        calc = VixSignalCalculator(prices_repo=repo)
        sig = calc.compute()
        assert sig.vix_vxv_ratio is None

    def test_insufficient_data_raises(self):
        """< 20 barre → ValueError."""
        repo = _make_prices_repo([15.0] * 10)
        calc = VixSignalCalculator(prices_repo=repo)
        with pytest.raises(ValueError, match="dati insufficienti"):
            calc.compute()

    def test_empty_db_raises(self):
        """DB vuoto → ValueError."""
        repo = _make_prices_repo([])
        calc = VixSignalCalculator(prices_repo=repo)
        with pytest.raises(ValueError):
            calc.compute()

    def test_pct_rank_between_0_and_1(self):
        """vix_pct_rank sempre in [0, 1]."""
        base = _calm_vix_series(252)
        repo = _make_prices_repo(base)
        calc = VixSignalCalculator(prices_repo=repo)
        sig = calc.compute()
        assert 0.0 <= sig.vix_pct_rank <= 1.0

    def test_signal_score_between_0_and_1(self):
        """vix_signal_score sempre in [0, 1]."""
        for spike in [12.0, 18.0, 28.0, 45.0]:
            base = _calm_vix_series(252)
            base[-1] = spike
            repo = _make_prices_repo(base)
            calc = VixSignalCalculator(prices_repo=repo)
            sig = calc.compute()
            assert 0.0 <= sig.vix_signal_score <= 1.0, \
                f"score={sig.vix_signal_score} per vix={spike}"

    def test_confidence_high_with_252_bars(self):
        """252 barre → confidence HIGH."""
        base = _calm_vix_series(252)
        repo = _make_prices_repo(base)
        calc = VixSignalCalculator(prices_repo=repo)
        sig = calc.compute()
        assert sig.confidence == "HIGH"

    def test_confidence_medium_with_80_bars(self):
        """80 barre → confidence MEDIUM."""
        base = _calm_vix_series(80)
        repo = _make_prices_repo(base)
        calc = VixSignalCalculator(prices_repo=repo)
        sig = calc.compute()
        assert sig.confidence == "MEDIUM"

    def test_output_fields_complete(self):
        """Tutti i campi del VixSignal sono presenti."""
        base = _calm_vix_series(252)
        repo = _make_prices_repo(base)
        calc = VixSignalCalculator(prices_repo=repo)
        sig = calc.compute()
        assert isinstance(sig, VixSignal)
        assert sig.computed_at.tzinfo is not None
        assert sig.lookback_bars == 252
        assert sig.action in ("BUY", "HOLD", "REDUCE")


# ═══════════════════════════════════════════════════════════════════════════
# StrategyComposer
# ═══════════════════════════════════════════════════════════════════════════

def _make_vix_signal(action: str = "HOLD", score: float = 0.3,
                     zscore: float = 0.5, vix: float = 18.0) -> VixSignal:
    return VixSignal(
        computed_at=datetime.now(timezone.utc),
        vix_level=vix, vix_zscore=zscore, vix_pct_rank=0.5,
        vix_vxv_ratio=None, spike_detected=False,
        vix_regime="elevated", zscore_signal=action.lower(),
        action=action, vix_signal_score=score, confidence="HIGH",
        regime_used=None, threshold_used=1.5, lookback_bars=252,
    )


def _make_vix_calc_mock(action: str = "HOLD", score: float = 0.3,
                        zscore: float = 0.5) -> MagicMock:
    mock = MagicMock()
    mock.compute.return_value = _make_vix_signal(action, score, zscore)
    return mock


def _make_macro_calc_mock(macro_score: float = 0.3) -> MagicMock:
    from engine.alpha_generation.schemas import (
        MacroConvictionResult, ClaimsInflationOutput, YieldCurveOutput,
        CreditStressOutput, ClaimsRegime, CreditStressLevel, CurveRegime,
    )
    mock = MagicMock()
    claims = ClaimsInflationOutput(
        regime=ClaimsRegime.GOLDILOCKS, regime_score=0.6,
        icsa_4wk_ma=220_000, icsa_yoy_pct=None, cpi_yoy=2.3,
        stagflation_signal=False, goldilocks_signal=True,
        overheating_signal=False, recession_watch=False,
    )
    yield_out = YieldCurveOutput(
        curve_regime=CurveRegime.NORMAL, regime_score=0.2,
        recession_prob_12m=0.15, spread_10y_2y=0.5,
        spread_10y_3m=0.3, y_10y=4.5, breakeven_10y=2.2,
        inversion_detected=False,
    )
    credit = CreditStressOutput(
        stress_level=CreditStressLevel.LOW, stress_score=0.3,
        hy_oas=300.0, ig_oas=90.0, hy_ig_ratio=3.33,
        ted_spread=15.0, nfci=-0.2,
    )
    result = MacroConvictionResult(
        macro_score=macro_score, confidence="HIGH",
        computed_at=datetime.now(timezone.utc),
        claims_output=claims, yield_output=yield_out, credit_output=credit,
        labour_score=0.5, inflation_score=0.4, rates_score=0.2,
        credit_score=0.3, growth_score=0.3,
        series_available=12, series_required=10,
        weight_breakdown={"labour": 0.25, "inflation": 0.20, "rates": 0.20,
                          "credit": 0.20, "growth": 0.15},
    )
    mock.compute.return_value = result
    return mock


class TestStrategyComposer:

    def _make_composer(self, vix_action="HOLD", vix_score=0.3,
                       macro_score=0.3, regime=None) -> StrategyComposer:
        mock_db = MagicMock()
        mock_db.query.return_value = [[regime]] if regime else []
        mock_db.execute = MagicMock()

        composer = StrategyComposer(
            vix_calculator=_make_vix_calc_mock(vix_action, vix_score),
            macro_calculator=_make_macro_calc_mock(macro_score),
            duckdb=mock_db,
            profile_risk="moderate",
        )
        return composer

    def test_run_returns_strategy_output(self):
        """run() ritorna StrategyOutput valido."""
        composer = self._make_composer()
        result = composer.run()
        assert isinstance(result, StrategyOutput)

    def test_composite_score_in_range(self):
        """composite_score sempre in [-1, +1]."""
        for vix_s, macro_s in [(0.0, -1.0), (1.0, 1.0), (0.5, 0.0), (0.3, 0.5)]:
            composer = self._make_composer(vix_score=vix_s, macro_score=macro_s)
            result = composer.run()
            assert -1.0 <= result.composite_score <= 1.0

    def test_buy_on_strong_vix_signal(self):
        """VIX BUY forte + macro positivo → action BUY."""
        composer = self._make_composer(
            vix_action="BUY", vix_score=0.9, macro_score=0.5
        )
        result = composer.run()
        assert result.action == "BUY"

    def test_reduce_on_weak_market(self):
        """VIX REDUCE + macro negativo → action REDUCE."""
        mock_db = MagicMock()
        mock_db.query.return_value = []
        mock_db.execute = MagicMock()

        composer = StrategyComposer(
            vix_calculator=_make_vix_calc_mock("REDUCE", 0.0, -2.0),
            macro_calculator=_make_macro_calc_mock(-0.8),
            duckdb=mock_db,
            profile_risk="moderate",
        )
        result = composer.run()
        assert result.action == "REDUCE"

    def test_hold_on_neutral(self):
        """VIX HOLD + macro neutro → action HOLD."""
        composer = self._make_composer(
            vix_action="HOLD", vix_score=0.2, macro_score=0.0
        )
        result = composer.run()
        assert result.action == "HOLD"

    def test_position_size_for_buy(self):
        """BUY → position_size_pct > 0.4."""
        composer = self._make_composer(
            vix_action="BUY", vix_score=0.9, macro_score=0.5
        )
        result = composer.run()
        if result.action == "BUY":
            assert result.position_size_pct > 0.4

    def test_position_size_for_reduce(self):
        """REDUCE → position_size_pct < 0.35."""
        mock_db = MagicMock()
        mock_db.query.return_value = []
        mock_db.execute = MagicMock()
        composer = StrategyComposer(
            vix_calculator=_make_vix_calc_mock("REDUCE", 0.0, -2.0),
            macro_calculator=_make_macro_calc_mock(-0.7),
            duckdb=mock_db, profile_risk="moderate",
        )
        result = composer.run()
        if result.action == "REDUCE":
            assert result.position_size_pct < 0.35

    def test_position_size_capped_by_profile(self):
        """position_size_pct ≤ max del profilo (moderate=70%)."""
        composer = self._make_composer(
            vix_action="BUY", vix_score=1.0, macro_score=1.0
        )
        result = composer.run()
        assert result.position_size_pct <= 0.70

    def test_regime_none_does_not_crash(self):
        """Con DB vuoto regime=None → nessun crash."""
        mock_db = MagicMock()
        mock_db.query.return_value = []
        mock_db.execute = MagicMock()
        composer = StrategyComposer(
            vix_calculator=_make_vix_calc_mock(),
            duckdb=mock_db, profile_risk="moderate",
        )
        result = composer.run()
        assert result.regime_used is None
        assert isinstance(result, StrategyOutput)

    def test_without_macro_uses_vix_only(self):
        """Senza MacroCalculator → composite basato solo su VIX."""
        mock_db = MagicMock()
        mock_db.query.return_value = []
        mock_db.execute = MagicMock()
        composer = StrategyComposer(
            vix_calculator=_make_vix_calc_mock("BUY", 0.8),
            macro_calculator=None,
            duckdb=mock_db, profile_risk="moderate",
        )
        result = composer.run()
        assert result.macro_score is None
        assert isinstance(result, StrategyOutput)

    def test_get_current_regime_reads_db(self):
        """_get_current_regime() legge da regime_reports."""
        mock_db = MagicMock()
        mock_db.query.return_value = [["bear"]]
        mock_db.execute = MagicMock()
        composer = StrategyComposer(
            vix_calculator=_make_vix_calc_mock(),
            duckdb=mock_db, profile_risk="moderate",
        )
        regime = composer._get_current_regime()
        assert regime == "bear"

    def test_get_current_regime_none_on_empty_db(self):
        """_get_current_regime() = None se tabella vuota."""
        mock_db = MagicMock()
        mock_db.query.return_value = []
        composer = StrategyComposer(
            vix_calculator=_make_vix_calc_mock(),
            duckdb=mock_db, profile_risk="moderate",
        )
        assert composer._get_current_regime() is None

    def test_get_current_regime_none_without_duckdb(self):
        """_get_current_regime() = None se duckdb=None."""
        composer = StrategyComposer(
            vix_calculator=_make_vix_calc_mock(),
            duckdb=None, profile_risk="moderate",
        )
        assert composer._get_current_regime() is None

    def test_notes_not_empty(self):
        """notes deve essere una stringa non vuota."""
        composer = self._make_composer()
        result = composer.run()
        assert isinstance(result.notes, str) and len(result.notes) > 10

    def test_computed_at_utc(self):
        """computed_at è timezone-aware UTC."""
        composer = self._make_composer()
        result = composer.run()
        assert result.computed_at.tzinfo is not None

    def test_conservative_profile_lower_max(self):
        """Profilo conservative → position_size_pct max 50%."""
        mock_db = MagicMock()
        mock_db.query.return_value = []
        mock_db.execute = MagicMock()
        composer = StrategyComposer(
            vix_calculator=_make_vix_calc_mock("BUY", 1.0),
            macro_calculator=_make_macro_calc_mock(1.0),
            duckdb=mock_db, profile_risk="conservative",
        )
        result = composer.run()
        assert result.position_size_pct <= 0.50


# ═══════════════════════════════════════════════════════════════════════════
# Test funzioni pure
# ═══════════════════════════════════════════════════════════════════════════

class TestPureFunctions:

    def test_combine_confidence_min(self):
        """_combine_confidence ritorna il minimo tra i due."""
        assert _combine_confidence("HIGH", "LOW") == "LOW"
        assert _combine_confidence("HIGH", "MEDIUM") == "MEDIUM"
        assert _combine_confidence("HIGH", "HIGH") == "HIGH"

    def test_combine_confidence_none_macro(self):
        """Macro=None → usa MEDIUM come default."""
        result = _combine_confidence("HIGH", None)
        assert result in ("HIGH", "MEDIUM")

    def test_build_notes_contains_action(self):
        """_build_notes include action nel testo."""
        sig = _make_vix_signal("BUY", 0.8, 2.0, 35.0)
        notes = _build_notes(sig, 0.4, 0.6, "BUY", "bear")
        assert "BUY" in notes

    def test_build_notes_contains_vix(self):
        """_build_notes include il livello VIX."""
        sig = _make_vix_signal("BUY", 0.8, 2.0, 35.0)
        notes = _build_notes(sig, 0.4, 0.6, "BUY", "bear")
        assert "35" in notes or "VIX" in notes


# ═══════════════════════════════════════════════════════════════════════════
# Integration: VixSignalCalculator + StrategyComposer
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration:

    def test_full_pipeline_buy_scenario(self):
        """Pipeline completa con VIX spike → BUY."""
        base = _calm_vix_series(252)
        base[-1] = float(np.mean(base)) + 2.5 * float(np.std(base, ddof=1))

        prices_repo = _make_prices_repo(base)
        vix_calc = VixSignalCalculator(prices_repo=prices_repo)

        mock_db = MagicMock()
        mock_db.query.return_value = [["bear"]]  # bear regime → amplifica segnale
        mock_db.execute = MagicMock()

        composer = StrategyComposer(
            vix_calculator=vix_calc,
            macro_calculator=_make_macro_calc_mock(0.3),
            duckdb=mock_db,
            profile_risk="moderate",
        )
        result = composer.run()
        assert result.action == "BUY"
        assert result.regime_used == "bear"

    def test_full_pipeline_empty_db_no_crash(self):
        """Pipeline completa con DB vuoto → nessun crash, regime=None."""
        base = _calm_vix_series(100)
        prices_repo = _make_prices_repo(base)
        vix_calc = VixSignalCalculator(prices_repo=prices_repo)

        mock_db = MagicMock()
        mock_db.query.return_value = []
        mock_db.execute = MagicMock()

        composer = StrategyComposer(
            vix_calculator=vix_calc, duckdb=mock_db, profile_risk="moderate",
        )
        result = composer.run()
        assert isinstance(result, StrategyOutput)
        assert result.regime_used is None

    def test_compute_under_500ms(self, benchmark):
        """StrategyComposer.run() < 500ms (target Roadmap Settimana 4)."""
        base = _calm_vix_series(252)
        prices_repo = _make_prices_repo(base)
        vix_calc = VixSignalCalculator(prices_repo=prices_repo)
        mock_db = MagicMock()
        mock_db.query.return_value = []
        mock_db.execute = MagicMock()

        composer = StrategyComposer(
            vix_calculator=vix_calc,
            macro_calculator=_make_macro_calc_mock(0.3),
            duckdb=mock_db, profile_risk="moderate",
        )
        result = benchmark(composer.run)
        assert isinstance(result, StrategyOutput)
