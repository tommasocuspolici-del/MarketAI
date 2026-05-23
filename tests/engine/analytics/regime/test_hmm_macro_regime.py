"""Tests for HMMRegimeModel — 4-state macro regime classification."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from shared.exceptions import MarketAIError

from engine.analytics.regime.hmm_macro_regime import (
    CONFIDENCE_THRESHOLD,
    REGIME_FEATURE_COLUMNS,
    HMMRegimeModel,
    RegimeOutput,
    RegimeState,
    _STATE_MAP,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def model() -> HMMRegimeModel:
    return HMMRegimeModel()


def _make_features(n: int = 50, seed: int = 42) -> pd.DataFrame:
    """Crea un DataFrame di feature sintetiche con le colonne corrette."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="ME")
    data = rng.standard_normal((n, len(REGIME_FEATURE_COLUMNS)))
    return pd.DataFrame(data, index=idx, columns=REGIME_FEATURE_COLUMNS)


# ── Test instantiation ────────────────────────────────────────────────────────

class TestHMMRegimeModelInstantiation:
    def test_model_instantiates(self, model: HMMRegimeModel) -> None:
        assert model is not None

    def test_not_fitted_initially(self, model: HMMRegimeModel) -> None:
        assert not model.is_fitted()

    def test_n_states_is_four(self, model: HMMRegimeModel) -> None:
        assert model.N_STATES == 4


# ── Test predict_current without fitting ─────────────────────────────────────

class TestPredictCurrentUnfitted:
    def test_predict_current_returns_regime_output(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=5)
        result = model.predict_current(features)
        assert isinstance(result, RegimeOutput)

    def test_predict_current_probs_sum_to_one(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=5)
        result = model.predict_current(features)
        total = (
            result.prob_expansion
            + result.prob_slowdown
            + result.prob_contraction
            + result.prob_recovery
        )
        assert abs(total - 1.0) < 1e-6

    def test_predict_current_probs_nonnegative(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=5)
        result = model.predict_current(features)
        assert result.prob_expansion >= 0.0
        assert result.prob_slowdown >= 0.0
        assert result.prob_contraction >= 0.0
        assert result.prob_recovery >= 0.0

    def test_predict_current_confidence_is_max_prob(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=5)
        result = model.predict_current(features)
        expected_max = max(
            result.prob_expansion,
            result.prob_slowdown,
            result.prob_contraction,
            result.prob_recovery,
        )
        assert abs(result.confidence - expected_max) < 1e-9

    def test_predict_current_regime_is_valid_enum(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=5)
        result = model.predict_current(features)
        assert isinstance(result.current_regime, RegimeState)
        assert result.current_regime in list(RegimeState)

    def test_predict_current_empty_input_returns_default(self, model: HMMRegimeModel) -> None:
        empty_features = pd.DataFrame(columns=REGIME_FEATURE_COLUMNS)
        result = model.predict_current(empty_features)
        assert isinstance(result, RegimeOutput)
        # Default è SLOWDOWN con prob=0.25 per ogni stato
        assert result.current_regime == RegimeState.SLOWDOWN


# ── Test predict on multiple rows ─────────────────────────────────────────────

class TestPredictMultipleRows:
    def test_predict_returns_list(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=10)
        outputs = model.predict(features)
        assert isinstance(outputs, list)
        assert len(outputs) == 10

    def test_predict_all_probs_sum_to_one(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=20)
        outputs = model.predict(features)
        for out in outputs:
            total = (
                out.prob_expansion
                + out.prob_slowdown
                + out.prob_contraction
                + out.prob_recovery
            )
            assert abs(total - 1.0) < 1e-6

    def test_predict_all_regimes_valid(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=10)
        outputs = model.predict(features)
        valid_regimes = set(RegimeState)
        for out in outputs:
            assert out.current_regime in valid_regimes


# ── Test label_regime ─────────────────────────────────────────────────────────

class TestLabelRegime:
    @pytest.mark.parametrize("state_idx,expected_regime", [
        (0, RegimeState.EXPANSION),
        (1, RegimeState.SLOWDOWN),
        (2, RegimeState.CONTRACTION),
        (3, RegimeState.RECOVERY),
    ])
    def test_label_regime_correct_mapping(
        self,
        model: HMMRegimeModel,
        state_idx: int,
        expected_regime: RegimeState,
    ) -> None:
        probs = np.array([0.1, 0.1, 0.1, 0.1])
        probs[state_idx] = 0.7
        result = model.label_regime(state_idx, probs)
        assert result == expected_regime

    def test_label_regime_wraps_modulo(self, model: HMMRegimeModel) -> None:
        """Indici out-of-range vengono wrappati con modulo 4."""
        probs = np.array([0.25, 0.25, 0.25, 0.25])
        # state_idx=4 → 4%4=0 → EXPANSION
        result = model.label_regime(4, probs)
        assert result == RegimeState.EXPANSION


# ── Test HMM with fitting (if hmmlearn available) ─────────────────────────────

class TestHMMFitting:
    def test_fit_marks_model_as_fitted(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=60)
        model.fit(features)
        assert model.is_fitted()

    def test_fit_raises_on_insufficient_data(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=10)  # MIN_SAMPLES = 36
        with pytest.raises((ValueError, MarketAIError)):
            model.fit(features)

    def test_predict_after_fit_returns_correct_length(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=60)
        model.fit(features)
        outputs = model.predict(features.tail(5))
        assert len(outputs) == 5

    def test_predict_after_fit_probs_sum_to_one(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=60)
        model.fit(features)
        outputs = model.predict(features.tail(10))
        for out in outputs:
            total = (
                out.prob_expansion
                + out.prob_slowdown
                + out.prob_contraction
                + out.prob_recovery
            )
            assert abs(total - 1.0) < 1e-6


# ── Test graceful fallback ────────────────────────────────────────────────────

class TestGracefulFallback:
    def test_rule_based_fallback_works_without_hmmlearn(self, model: HMMRegimeModel) -> None:
        """Anche senza fitting, il modello rule-based deve funzionare."""
        # Non chiama fit() → usa rule-based classifier
        features = _make_features(n=10)
        result = model.predict_current(features)
        assert isinstance(result, RegimeOutput)
        total = (
            result.prob_expansion
            + result.prob_slowdown
            + result.prob_contraction
            + result.prob_recovery
        )
        assert abs(total - 1.0) < 1e-6

    def test_model_version_is_set(self, model: HMMRegimeModel) -> None:
        features = _make_features(n=5)
        result = model.predict_current(features)
        assert result.model_version in ("rule_based_v1.0", "hmm_v2.0")
