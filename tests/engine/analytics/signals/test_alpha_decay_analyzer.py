"""Tests for AlphaDecayAnalyzer — exponential IC decay half-life computation."""
from __future__ import annotations

import math

import numpy as np
import pytest

from engine.analytics.signals.alpha_decay_analyzer import (
    DECAY_R2_THRESHOLD,
    AlphaDecayAnalyzer,
    DecayResult,
)


@pytest.fixture
def analyzer() -> AlphaDecayAnalyzer:
    return AlphaDecayAnalyzer()


# ── Test perfect exponential decay ────────────────────────────────────────────

class TestPerfectExponentialDecay:
    def test_returns_decay_result(self, analyzer: AlphaDecayAnalyzer) -> None:
        ic_by_horizon = {1: 0.20, 5: 0.15, 21: 0.10, 63: 0.06, 126: 0.03}
        result = analyzer.compute("test_sig", ic_by_horizon)
        assert isinstance(result, DecayResult)

    def test_positive_decay_rate_for_decaying_ic(self, analyzer: AlphaDecayAnalyzer) -> None:
        """IC decrescente → decay_rate positivo."""
        ic_by_horizon = {1: 0.20, 10: 0.12, 30: 0.07, 60: 0.04, 120: 0.02}
        result = analyzer.compute("decaying", ic_by_horizon)
        assert result.decay_rate > 0

    def test_half_life_approximately_correct(self, analyzer: AlphaDecayAnalyzer) -> None:
        """Dato IC(t) = 0.2 * exp(-0.02 * t), half_life ≈ ln(2)/0.02 ≈ 35 giorni."""
        lambda_true = 0.02
        horizons = [1, 5, 10, 20, 30, 50, 70]
        ic_by_horizon = {h: 0.20 * math.exp(-lambda_true * h) for h in horizons}
        result = analyzer.compute("synthetic", ic_by_horizon)

        expected_hl = int(round(math.log(2) / lambda_true))  # ≈ 35
        # Tolleranza del 50%: il fit numerico può variare
        assert result.is_decaying
        assert abs(result.half_life_days - expected_hl) <= expected_hl * 0.5

    def test_r_squared_high_for_perfect_decay(self, analyzer: AlphaDecayAnalyzer) -> None:
        """R² deve essere alto (≥ 0.90) con dati perfettamente esponenziali."""
        lambda_true = 0.01
        horizons = [5, 10, 20, 40, 80, 120]
        ic_by_horizon = {h: 0.15 * math.exp(-lambda_true * h) for h in horizons}
        result = analyzer.compute("perfect", ic_by_horizon)
        assert result.r_squared >= 0.90


# ── Test no decay ─────────────────────────────────────────────────────────────

class TestNoDecay:
    def test_flat_ic_gives_no_decay(self, analyzer: AlphaDecayAnalyzer) -> None:
        """IC costante → nessun decay rilevabile."""
        ic_by_horizon = {1: 0.10, 21: 0.10, 63: 0.10, 126: 0.10}
        result = analyzer.compute("flat_sig", ic_by_horizon)
        assert not result.is_decaying

    def test_increasing_ic_gives_no_decay(self, analyzer: AlphaDecayAnalyzer) -> None:
        """IC crescente → decay_rate negativo o nullo → is_decaying=False."""
        ic_by_horizon = {1: 0.05, 21: 0.08, 63: 0.12, 126: 0.18}
        result = analyzer.compute("growing_sig", ic_by_horizon)
        assert not result.is_decaying

    def test_no_decay_half_life_is_minus_one(self, analyzer: AlphaDecayAnalyzer) -> None:
        """Senza decay, half_life_days deve essere -1."""
        ic_by_horizon = {1: 0.10, 21: 0.10, 63: 0.10, 126: 0.10}
        result = analyzer.compute("flat", ic_by_horizon)
        assert result.half_life_days == -1


# ── Test insufficient horizons ────────────────────────────────────────────────

class TestInsufficientHorizons:
    def test_zero_horizons_returns_no_decay(self, analyzer: AlphaDecayAnalyzer) -> None:
        result = analyzer.compute("empty", {})
        assert not result.is_decaying
        assert result.half_life_days == -1

    def test_one_horizon_returns_no_decay(self, analyzer: AlphaDecayAnalyzer) -> None:
        result = analyzer.compute("single", {21: 0.10})
        assert not result.is_decaying
        assert result.half_life_days == -1

    def test_two_horizons_returns_no_decay(self, analyzer: AlphaDecayAnalyzer) -> None:
        result = analyzer.compute("two", {21: 0.10, 63: 0.07})
        # MIN_HORIZONS = 3, quindi 2 è insufficiente
        assert not result.is_decaying

    def test_insufficient_horizons_returns_decay_result_type(
        self, analyzer: AlphaDecayAnalyzer
    ) -> None:
        result = analyzer.compute("too_few", {21: 0.10})
        assert isinstance(result, DecayResult)
        assert result.signal_id == "too_few"

    def test_all_negative_ic_returns_no_decay(self, analyzer: AlphaDecayAnalyzer) -> None:
        """IC tutti negativi senza sufficiente struttura → is_decaying=False."""
        ic_by_horizon = {1: -0.01, 5: -0.01, 10: -0.01, 20: -0.01}
        result = analyzer.compute("negative_flat", ic_by_horizon)
        assert not result.is_decaying


# ── Test DecayResult fields ───────────────────────────────────────────────────

class TestDecayResultFields:
    def test_signal_id_preserved(self, analyzer: AlphaDecayAnalyzer) -> None:
        ic_by_horizon = {1: 0.20, 10: 0.10, 30: 0.05, 60: 0.025, 90: 0.01}
        result = analyzer.compute("my_signal", ic_by_horizon)
        assert result.signal_id == "my_signal"

    def test_decay_rate_nonnegative_when_decaying(self, analyzer: AlphaDecayAnalyzer) -> None:
        ic_by_horizon = {1: 0.20, 10: 0.12, 30: 0.07, 60: 0.04, 120: 0.02}
        result = analyzer.compute("check_rate", ic_by_horizon)
        if result.is_decaying:
            assert result.decay_rate >= 0.0

    def test_r_squared_in_unit_interval(self, analyzer: AlphaDecayAnalyzer) -> None:
        ic_by_horizon = {1: 0.20, 10: 0.12, 30: 0.07, 60: 0.04, 120: 0.02}
        result = analyzer.compute("r2_check", ic_by_horizon)
        assert 0.0 <= result.r_squared <= 1.0
