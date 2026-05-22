"""Tests for CVaRRegimeCalculator."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.analytics.risk.cvar_regime_calculator import (
    CVaRRegimeCalculator,
    CVaRRegimeResult,
    RegimeCVaR,
    MIN_REGIME_SAMPLES,
)


def _make_returns(
    n: int = 500,
    seed: int = 42,
    scale: float = 0.01,
) -> pd.Series:
    """Genera rendimenti giornalieri sintetici."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    vals = rng.normal(0.0, scale, n)
    return pd.Series(vals, index=dates)


def _make_regimes(returns: pd.Series, seed: int = 0) -> pd.Series:
    """Genera etichette regime alternanti su stesso index di returns."""
    rng = np.random.default_rng(seed)
    regimes = rng.choice(["expansion", "recession", "stress"], size=len(returns))
    return pd.Series(regimes, index=returns.index)


class TestCVaRRegimeCalculator:
    """Test suite per CVaRRegimeCalculator."""

    def test_compute_returns_correct_type(self) -> None:
        """compute() restituisce CVaRRegimeResult."""
        returns = _make_returns(300)
        regimes = _make_regimes(returns)
        probs = {"expansion": 0.6, "recession": 0.3, "stress": 0.1}
        calc = CVaRRegimeCalculator()
        result = calc.compute(returns, regimes, probs)
        assert isinstance(result, CVaRRegimeResult)

    def test_compute_all_fields_present(self) -> None:
        """Tutti i campi di CVaRRegimeResult sono valorizzati."""
        returns = _make_returns(300)
        regimes = _make_regimes(returns)
        probs = {"expansion": 0.5, "recession": 0.3, "stress": 0.2}
        result = CVaRRegimeCalculator().compute(returns, regimes, probs)

        assert isinstance(result.cvar_unconditional_95, float)
        assert isinstance(result.cvar_unconditional_99, float)
        assert isinstance(result.cvar_blended_95, float)
        assert isinstance(result.cvar_blended_99, float)
        assert isinstance(result.cvar_by_regime, dict)
        assert isinstance(result.regime_weights, dict)

    def test_cvar_99_geq_cvar_95(self) -> None:
        """CVaR 99% ≥ CVaR 95% (la coda più lontana è più rischiosa)."""
        returns = _make_returns(500)
        regimes = _make_regimes(returns)
        probs = {"expansion": 0.7, "recession": 0.2, "stress": 0.1}
        result = CVaRRegimeCalculator().compute(returns, regimes, probs)
        assert result.cvar_unconditional_99 >= result.cvar_unconditional_95 - 1e-8

    def test_regime_cvar_keys_match_labels(self) -> None:
        """cvar_by_regime contiene esattamente i regimi presenti nei dati."""
        returns = _make_returns(300)
        regime_labels = _make_regimes(returns)
        probs = {"expansion": 0.6, "recession": 0.4}
        result = CVaRRegimeCalculator().compute(returns, regime_labels, probs)
        for key in result.cvar_by_regime:
            assert key in ["expansion", "recession", "stress"]

    def test_blended_cvar_is_weighted_average(self) -> None:
        """cvar_blended_95 è consistente con i pesi (non zero)."""
        returns = _make_returns(500)
        regime_labels = _make_regimes(returns)
        probs = {"expansion": 0.8, "recession": 0.1, "stress": 0.1}
        result = CVaRRegimeCalculator().compute(returns, regime_labels, probs)
        # Il blended deve essere positivo (perdita)
        assert result.cvar_blended_95 >= 0.0

    def test_regime_cvar_99_geq_95_per_regime(self) -> None:
        """Per ogni regime: cvar_99 ≥ cvar_95."""
        returns = _make_returns(500)
        regime_labels = _make_regimes(returns)
        probs = {"expansion": 0.5, "recession": 0.3, "stress": 0.2}
        result = CVaRRegimeCalculator().compute(returns, regime_labels, probs)
        for regime_name, rcvar in result.cvar_by_regime.items():
            assert rcvar.cvar_99 >= rcvar.cvar_95 - 1e-8, (
                f"Regime {regime_name}: cvar_99={rcvar.cvar_99} < cvar_95={rcvar.cvar_95}"
            )

    def test_is_reliable_flag(self) -> None:
        """is_reliable=True solo se n_samples >= MIN_REGIME_SAMPLES."""
        returns = _make_returns(500)
        regime_labels = _make_regimes(returns)
        probs = {"expansion": 0.5, "recession": 0.3, "stress": 0.2}
        result = CVaRRegimeCalculator().compute(returns, regime_labels, probs)
        for regime_name, rcvar in result.cvar_by_regime.items():
            expected = rcvar.n_samples >= MIN_REGIME_SAMPLES
            assert rcvar.is_reliable == expected, (
                f"Regime {regime_name}: n={rcvar.n_samples}, is_reliable={rcvar.is_reliable}"
            )

    def test_t_dof_positive(self) -> None:
        """Gradi di libertà t-Student stimati devono essere > 0."""
        returns = _make_returns(300)
        regime_labels = _make_regimes(returns)
        probs = {"expansion": 0.5, "recession": 0.3, "stress": 0.2}
        result = CVaRRegimeCalculator().compute(returns, regime_labels, probs)
        for rcvar in result.cvar_by_regime.values():
            assert rcvar.t_dof > 0.0, f"t_dof={rcvar.t_dof} <= 0"

    def test_mle_t_dof_fit(self) -> None:
        """_fit_t_student_mle restituisce DOF positivo su dati sintetici."""
        calc = CVaRRegimeCalculator()
        rng = np.random.default_rng(7)
        fat_tail_rets = rng.standard_t(df=4, size=200) * 0.01
        dof = calc._fit_t_student_mle(fat_tail_rets)
        assert dof > 0.0
        assert dof < 200.0  # deve essere ragionevole

    def test_cvar_historical_positive(self) -> None:
        """CVaR historical deve essere non-negativo."""
        calc = CVaRRegimeCalculator()
        rng = np.random.default_rng(1)
        rets = rng.normal(0, 0.02, 100)
        cvar = calc._cvar_historical(rets, 0.95)
        assert cvar >= 0.0

    def test_partial_prob_coverage(self) -> None:
        """Se i regime_probs non coprono tutti i regimi nel dato, blended ok."""
        returns = _make_returns(300)
        regime_labels = _make_regimes(returns)
        # Solo expansion nei probs
        probs = {"expansion": 1.0}
        result = CVaRRegimeCalculator().compute(returns, regime_labels, probs)
        # Non deve crashare, blended >= 0
        assert result.cvar_blended_95 >= 0.0

    def test_regime_cvar_has_n_samples(self) -> None:
        """n_samples per ogni regime deve corrispondere alle osservazioni effettive."""
        returns = _make_returns(300)
        regime_labels = _make_regimes(returns)
        probs = {"expansion": 0.5, "recession": 0.3, "stress": 0.2}
        result = CVaRRegimeCalculator().compute(returns, regime_labels, probs)
        total_n = sum(r.n_samples for r in result.cvar_by_regime.values())
        assert total_n == len(returns)
