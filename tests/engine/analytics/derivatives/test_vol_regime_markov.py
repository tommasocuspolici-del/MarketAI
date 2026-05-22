"""Tests for VolRegimeMarkov."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analytics.derivatives.vol_regime_markov import (
    VolRegimeMarkov,
    VolRegime,
    VolRegimeState,
    VIX_CALM_THRESHOLD,
    VIX_NORMAL_THRESHOLD,
    VIX_HIGH_THRESHOLD,
)


def _make_vix_series(n: int = 500, seed: int = 42) -> pd.Series:
    """Genera serie VIX sintetica con diversi regimi."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    # Mix di livelli VIX
    vix_values = np.concatenate([
        rng.uniform(10, 14, n // 4),    # calm
        rng.uniform(15, 24, n // 4),    # normal
        rng.uniform(25, 34, n // 4),    # high
        rng.uniform(35, 60, n // 4),    # extreme
    ])
    rng.shuffle(vix_values)
    return pd.Series(vix_values[:n], index=dates)


class TestVolRegimeMarkovClassify:
    """Test classificazione regime VIX."""

    def test_classify_calm_below_threshold(self) -> None:
        """VIX < 15 → CALM."""
        model = VolRegimeMarkov()
        for vix in [5.0, 10.0, 14.9]:
            assert model.classify(vix) == VolRegime.CALM, f"VIX={vix} dovrebbe essere CALM"

    def test_classify_normal_in_range(self) -> None:
        """15 ≤ VIX < 25 → NORMAL."""
        model = VolRegimeMarkov()
        for vix in [15.0, 18.5, 24.9]:
            assert model.classify(vix) == VolRegime.NORMAL, f"VIX={vix} dovrebbe essere NORMAL"

    def test_classify_high_in_range(self) -> None:
        """25 ≤ VIX < 35 → HIGH."""
        model = VolRegimeMarkov()
        for vix in [25.0, 30.0, 34.9]:
            assert model.classify(vix) == VolRegime.HIGH, f"VIX={vix} dovrebbe essere HIGH"

    def test_classify_extreme_above_threshold(self) -> None:
        """VIX ≥ 35 → EXTREME."""
        model = VolRegimeMarkov()
        for vix in [35.0, 50.0, 80.0]:
            assert model.classify(vix) == VolRegime.EXTREME, f"VIX={vix} dovrebbe essere EXTREME"

    def test_classify_boundary_calm_normal(self) -> None:
        """Valore esatto al confine CALM/NORMAL → NORMAL."""
        model = VolRegimeMarkov()
        assert model.classify(VIX_CALM_THRESHOLD) == VolRegime.NORMAL

    def test_classify_boundary_normal_high(self) -> None:
        """Valore esatto al confine NORMAL/HIGH → HIGH."""
        model = VolRegimeMarkov()
        assert model.classify(VIX_NORMAL_THRESHOLD) == VolRegime.HIGH

    def test_classify_boundary_high_extreme(self) -> None:
        """Valore esatto al confine HIGH/EXTREME → EXTREME."""
        model = VolRegimeMarkov()
        assert model.classify(VIX_HIGH_THRESHOLD) == VolRegime.EXTREME


class TestVolRegimeMarkovPredictState:
    """Test predict_state e transizioni."""

    def test_predict_state_returns_correct_type(self) -> None:
        """predict_state() restituisce VolRegimeState."""
        model = VolRegimeMarkov()
        state = model.predict_state(18.0)
        assert isinstance(state, VolRegimeState)

    def test_predict_state_current_regime_correct(self) -> None:
        """current_regime è coerente con VIX in input."""
        model = VolRegimeMarkov()
        state = model.predict_state(12.0)
        assert state.current_regime == VolRegime.CALM
        state2 = model.predict_state(40.0)
        assert state2.current_regime == VolRegime.EXTREME

    def test_transition_probs_sum_to_one(self) -> None:
        """Probabilità di transizione sommano a ≈ 1.0 per ogni regime."""
        model = VolRegimeMarkov()
        for vix in [10.0, 20.0, 30.0, 45.0]:
            state = model.predict_state(vix)
            total = sum(state.transition_probs.values())
            assert abs(total - 1.0) < 1e-8, (
                f"VIX={vix}: sum probs={total}"
            )

    def test_transition_probs_all_regimes_present(self) -> None:
        """Tutte e 4 le chiavi VolRegime presenti nelle transizioni."""
        model = VolRegimeMarkov()
        state = model.predict_state(20.0)
        for regime in VolRegime:
            assert regime in state.transition_probs, f"{regime} mancante"

    def test_expected_next_vix_positive(self) -> None:
        """expected_next_vix deve essere positivo."""
        model = VolRegimeMarkov()
        for vix in [10.0, 20.0, 30.0, 50.0]:
            state = model.predict_state(vix)
            assert state.expected_next_vix > 0.0

    def test_regime_strategy_valid(self) -> None:
        """regime_strategy deve essere uno dei valori validi."""
        valid_strategies = {"short_vol", "neutral", "long_vol", "protective"}
        model = VolRegimeMarkov()
        for vix in [10.0, 20.0, 30.0, 50.0]:
            state = model.predict_state(vix)
            assert state.regime_strategy in valid_strategies, (
                f"strategy={state.regime_strategy} non valida"
            )


class TestVolRegimeMarkovFit:
    """Test fit della matrice di transizione."""

    def test_fit_returns_self(self) -> None:
        """fit() restituisce l'istanza stessa (fluent API)."""
        model = VolRegimeMarkov()
        vix = _make_vix_series(300)
        result = model.fit(vix)
        assert result is model

    def test_fit_updates_transition_matrix(self) -> None:
        """fit() aggiorna la matrice di transizione (diversa da default)."""
        model = VolRegimeMarkov()
        default_calm = dict(model._transition["calm"])
        # Serie VIX che rimane sempre in regime calm (< 15)
        dates = pd.date_range("2020-01-01", periods=500, freq="B", tz="UTC")
        vix_calm = pd.Series(np.full(500, 12.0), index=dates)
        model.fit(vix_calm)
        # Dopo fit su serie calm, probabilità calm→calm deve essere altissima
        new_calm = model._transition["calm"]
        assert new_calm["calm"] > 0.99

    def test_fit_transition_rows_sum_to_one(self) -> None:
        """Dopo fit(), ogni riga della matrice somma a ≈ 1.0."""
        model = VolRegimeMarkov()
        vix = _make_vix_series(500)
        model.fit(vix)
        for regime, row in model._transition.items():
            total = sum(row.values())
            assert abs(total - 1.0) < 1e-8, (
                f"Regime {regime}: sum={total}"
            )

    def test_fit_insufficient_data_uses_default(self) -> None:
        """fit() con dati insufficienti usa valori di default."""
        model = VolRegimeMarkov()
        default_transition = {k: dict(v) for k, v in model._transition.items()}
        vix_tiny = pd.Series([12.0], index=pd.DatetimeIndex(["2020-01-01"]))
        model.fit(vix_tiny)
        # Con un solo punto, usa default
        assert model._transition == default_transition

    def test_fit_mixed_vix_all_regimes(self) -> None:
        """Con VIX che attraversa tutti i regimi, matrice copre tutti gli stati."""
        model = VolRegimeMarkov()
        vix = _make_vix_series(1000)  # include tutti i regimi
        model.fit(vix)
        # Verifica che tutti i regimi abbiano righe nella matrice
        for regime in ["calm", "normal", "high", "extreme"]:
            assert regime in model._transition


class TestVolRegimeMarkovExpectedVix:
    """Test calcolo VIX atteso."""

    def test_expected_vix_in_reasonable_range(self) -> None:
        """VIX atteso deve essere in range ragionevole [5, 100]."""
        model = VolRegimeMarkov()
        for regime in VolRegime:
            expected = model.expected_vix_next_period(regime)
            assert 5.0 < expected < 100.0, (
                f"Regime {regime}: expected_vix={expected} fuori range"
            )

    def test_calm_expected_vix_lower_than_extreme(self) -> None:
        """Da CALM, VIX atteso < da EXTREME (regime persistence)."""
        model = VolRegimeMarkov()
        vix_from_calm = model.expected_vix_next_period(VolRegime.CALM)
        vix_from_extreme = model.expected_vix_next_period(VolRegime.EXTREME)
        assert vix_from_calm < vix_from_extreme
