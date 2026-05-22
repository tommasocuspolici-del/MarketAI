"""CVaR Condizionale al Regime di Mercato.

CVaR standard assume media storica. CVaR condizionale stima il rischio
estremo separatamente per ogni regime macro, usando t-Student con gradi
di libertà stimati via MLE per ogni regime.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize_scalar

from shared.logger import get_logger

__version__ = "11.0.0"

__all__ = ["CVaRRegimeCalculator", "CVaRRegimeResult", "RegimeCVaR"]

log = get_logger(__name__)

VAR_CONFIDENCE_95: float = 0.95
VAR_CONFIDENCE_99: float = 0.99
MIN_REGIME_SAMPLES: int = 20
DOF_LOWER_BOUND: float = 2.01      # t-Student: dof > 2 garantisce varianza finita
DOF_UPPER_BOUND: float = 100.0     # Sopra 100 ≈ normale


@dataclass
class RegimeCVaR:
    """CVaR stimata per un singolo regime di mercato."""

    regime: str
    cvar_95: float
    cvar_99: float
    var_95: float
    var_99: float
    n_samples: int
    t_dof: float           # gradi di libertà t-Student MLE
    is_reliable: bool      # True if n_samples >= MIN_REGIME_SAMPLES


@dataclass
class CVaRRegimeResult:
    """Risultato completo dell'analisi CVaR per regime."""

    cvar_unconditional_95: float
    cvar_unconditional_99: float
    cvar_by_regime: dict[str, RegimeCVaR]
    cvar_blended_95: float    # pesato per probabilità regime corrente
    cvar_blended_99: float
    regime_weights: dict[str, float] = field(default_factory=dict)  # regime → probability


class CVaRRegimeCalculator:
    """Calcola CVaR condizionale per ogni regime macro.

    Usa distribuzione t-Student con gradi di libertà stimati via MLE
    per catturare le code grasse nei rendimenti di ciascun regime.
    """

    def __init__(
        self,
        confidence_95: float = VAR_CONFIDENCE_95,
        confidence_99: float = VAR_CONFIDENCE_99,
    ) -> None:
        self._conf_95 = confidence_95
        self._conf_99 = confidence_99

    def compute(
        self,
        returns: pd.Series,
        regime_labels: pd.Series,
        current_regime_probs: dict[str, float],
    ) -> CVaRRegimeResult:
        """Calcola CVaR condizionale per ogni regime macro.

        Parameters
        ----------
        returns:
            Rendimenti storici del portafoglio (float, stesso index di regime_labels).
        regime_labels:
            Etichetta regime per ogni data (stesso index di returns).
        current_regime_probs:
            Probabilità corrente per ogni regime (somma deve essere ~1).
        """
        aligned = returns.align(regime_labels, join="inner")
        ret_arr: np.ndarray = aligned[0].to_numpy(dtype=float)
        lbl_arr: pd.Series = aligned[1]

        # CVaR incondizionale sull'intera serie
        cvar_unc_95 = self._cvar_historical(ret_arr, self._conf_95)
        cvar_unc_99 = self._cvar_historical(ret_arr, self._conf_99)

        # CVaR per regime
        cvar_by_regime: dict[str, RegimeCVaR] = {}
        for regime in lbl_arr.unique():
            mask = lbl_arr == regime
            sub = ret_arr[mask.to_numpy()]
            n = len(sub)
            if n < 2:
                log.warning("cvar_regime.skip_regime", regime=regime, n=n)
                continue

            dof = self._fit_t_student_mle(sub)
            cvar_95 = self._cvar_from_t(sub, self._conf_95, dof)
            cvar_99 = self._cvar_from_t(sub, self._conf_99, dof)
            var_95 = self._var_historical(sub, self._conf_95)
            var_99 = self._var_historical(sub, self._conf_99)

            cvar_by_regime[str(regime)] = RegimeCVaR(
                regime=str(regime),
                cvar_95=cvar_95,
                cvar_99=cvar_99,
                var_95=var_95,
                var_99=var_99,
                n_samples=n,
                t_dof=dof,
                is_reliable=(n >= MIN_REGIME_SAMPLES),
            )

        # CVaR blended pesato per probabilità correnti
        blended_95 = 0.0
        blended_99 = 0.0
        total_weight = 0.0
        for regime_name, prob in current_regime_probs.items():
            if regime_name in cvar_by_regime:
                blended_95 += prob * cvar_by_regime[regime_name].cvar_95
                blended_99 += prob * cvar_by_regime[regime_name].cvar_99
                total_weight += prob

        # Normalizza se i pesi non sommano a 1 (parziale copertura)
        if total_weight > 0:
            blended_95 /= total_weight
            blended_99 /= total_weight
        else:
            blended_95 = cvar_unc_95
            blended_99 = cvar_unc_99

        log.info(
            "cvar_regime.computed",
            n_regimes=len(cvar_by_regime),
            cvar_unc_95=round(cvar_unc_95, 4),
            cvar_blended_95=round(blended_95, 4),
        )

        return CVaRRegimeResult(
            cvar_unconditional_95=cvar_unc_95,
            cvar_unconditional_99=cvar_unc_99,
            cvar_by_regime=cvar_by_regime,
            cvar_blended_95=blended_95,
            cvar_blended_99=blended_99,
            regime_weights=dict(current_regime_probs),
        )

    def _fit_t_student_mle(self, returns: np.ndarray) -> float:
        """Stima gradi di libertà t-Student via MLE.

        Minimizza la log-verosimiglianza negativa della t-Student
        standardizzata sui rendimenti demeaned.
        """
        if len(returns) < 2:
            return DOF_UPPER_BOUND

        demeaned = returns - np.mean(returns)
        std = np.std(demeaned)
        if std < 1e-12:
            return DOF_UPPER_BOUND

        normalized = demeaned / std

        def neg_log_likelihood(dof: float) -> float:
            if dof <= 2.0:
                return 1e12
            try:
                ll = np.sum(stats.t.logpdf(normalized, df=dof))
                return -ll
            except Exception:
                return 1e12

        result = minimize_scalar(
            neg_log_likelihood,
            bounds=(DOF_LOWER_BOUND, DOF_UPPER_BOUND),
            method="bounded",
        )
        return float(np.clip(result.x, DOF_LOWER_BOUND, DOF_UPPER_BOUND))

    def _cvar_from_t(
        self,
        returns: np.ndarray,
        confidence: float,
        dof: float,
    ) -> float:
        """CVaR dalla distribuzione t-Student.

        CVaR_t = -μ + σ * t_pdf(q_α) / (1-α) * (dof + q_α²) / (dof - 1)
        con q_α = quantile α della t(dof).
        """
        if len(returns) < 2:
            return 0.0

        mu = float(np.mean(returns))
        sigma = float(np.std(returns))
        if sigma < 1e-12:
            return abs(mu)

        alpha = 1.0 - confidence
        q = float(stats.t.ppf(alpha, df=dof))  # quantile negativo (perdita)
        pdf_q = float(stats.t.pdf(q, df=dof))

        # Formula analitica CVaR per t-Student
        cvar = -(mu + sigma * (pdf_q / alpha) * (dof + q**2) / (dof - 1))
        return float(max(cvar, 0.0))  # CVaR è sempre positivo (perdita)

    def _cvar_historical(
        self,
        returns: np.ndarray,
        confidence: float,
    ) -> float:
        """CVaR historical simulation: media dei ritorni peggiori di VaR."""
        if len(returns) < 2:
            return 0.0
        var = self._var_historical(returns, confidence)
        tail = returns[returns <= -var]
        if len(tail) == 0:
            return var
        return float(-np.mean(tail))

    def _var_historical(
        self,
        returns: np.ndarray,
        confidence: float,
    ) -> float:
        """VaR historical: quantile (1-confidence) dei rendimenti."""
        if len(returns) == 0:
            return 0.0
        q = float(np.quantile(returns, 1.0 - confidence))
        return float(-min(q, 0.0))
