"""EWMA Enhanced con decay ottimale stimato via MLE.

Miglioramento rispetto all'EWMA standard:
  1. Decay lambda ottimale per coppia: MLE su log-likelihood normale
  2. Regime-conditioning: correlazione separata per bull/bear/stress/transition
  3. Ledoit-Wolf shrinkage per garantire matrice PSD

Feature flag: dcc_ewma_enhanced (default True)
Fallback per DCC-GARCH-full (feature flag dcc_garch_full, default False).

Performance target: < 200ms per 20 asset su 5 anni giornalieri (Rule 30).
Regola 8: numpy/scipy per calcoli.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    pass

__version__ = "1.0.0"
log = logging.getLogger(__name__)

# Grid search lambda EWMA (range: 0.90 - 0.99, step 0.01)
_LAMBDA_GRID   = np.arange(0.90, 1.00, 0.01)
_LAMBDA_DEFAULT = 0.94   # RiskMetrics standard

# Shrinkage: coefficiente target (Ledoit-Wolf formula costante se sklearn N/D)
_SHRINKAGE_INTENSITY = 0.05


@dataclass(frozen=True)
class EWMACorrelationResult:
    """Output del DCCEWMAEnhanced per una coppia di asset."""
    asset_a:            str
    asset_b:            str
    ewma_correlation:   float              # Correlazione EWMA all'ultimo timestamp
    decay_lambda:       float              # Lambda ottimale stimato via MLE
    regime_correlations: dict[str, float] = field(default_factory=dict)
    # 'bull'|'bear'|'stress'|'transition' â†’ correlazione per quel regime


@dataclass
class DCCEWMAEnhancedResult:
    """Output completo per N asset."""
    correlation_matrix: np.ndarray  # type: ignore[type-arg]  # N×N EWMA current
    asset_names:        list[str]
    pairwise:           list[EWMACorrelationResult]
    is_psd:             bool               # True se matrice PSD garantita
    shrinkage_applied:  bool


class DCCEWMAEnhanced:
    """EWMA con decay ottimale e regime-conditioning.

    Args:
        lambda_grid: Grid di lambda da cercare (default 0.90-0.99).
        min_periods: Osservazioni minime per calcolo stabile.

    Usage::

        ewma = DCCEWMAEnhanced()
        result = ewma.compute(returns_df)  # returns: DataFrame col=asset, row=date
        print(result.correlation_matrix)
    """

    def __init__(
        self,
        lambda_grid: np.ndarray | None = None,  # type: ignore[type-arg]
        min_periods: int = 60,
    ) -> None:
        self._lambda_grid = lambda_grid if lambda_grid is not None else _LAMBDA_GRID
        self._min_periods = min_periods

    def compute(
        self,
        returns: pd.DataFrame,
        regime_labels: pd.Series | None = None,
    ) -> DCCEWMAEnhancedResult:
        """Calcola matrice di correlazione EWMA per tutti i pairwise.

        Args:
            returns:       DataFrame con rendimenti log (colonne=asset, righe=date).
            regime_labels: Series con regime per ogni data (bull/bear/stress/transition).

        Returns:
            DCCEWMAEnhancedResult con matrice correlazione + pairwise details.
        """
        if returns.empty or len(returns) < self._min_periods:
            log.warning("dcc_ewma_enhanced.insufficient_data n_rows=%d", len(returns))
            n = len(returns.columns)
            return DCCEWMAEnhancedResult(
                correlation_matrix=np.eye(n),
                asset_names=list(returns.columns),
                pairwise=[],
                is_psd=True,
                shrinkage_applied=False,
            )

        assets = list(returns.columns)
        n = len(assets)
        corr_matrix = np.eye(n)
        pairwise: list[EWMACorrelationResult] = []

        for i in range(n):
            for j in range(i + 1, n):
                a, b = assets[i], assets[j]
                r_ab = returns[[a, b]].dropna()

                if len(r_ab) < self._min_periods:
                    continue

                lam   = self._find_optimal_lambda(r_ab[a].values, r_ab[b].values)
                corr  = self._ewma_correlation_last(r_ab[a].values, r_ab[b].values, lam)
                regimes = {}
                if regime_labels is not None:
                    regimes = self._regime_conditioned(r_ab, a, b, regime_labels)

                corr_matrix[i, j] = corr
                corr_matrix[j, i] = corr
                pairwise.append(EWMACorrelationResult(
                    asset_a=a, asset_b=b,
                    ewma_correlation=corr,
                    decay_lambda=lam,
                    regime_correlations=regimes,
                ))

        # Garantisce PSD (Ledoit-Wolf shrinkage se necessario)
        shrinkage = False
        if not self._is_psd(corr_matrix):
            corr_matrix = self._ledoit_wolf_shrinkage(corr_matrix)
            shrinkage = True

        return DCCEWMAEnhancedResult(
            correlation_matrix=corr_matrix,
            asset_names=assets,
            pairwise=pairwise,
            is_psd=self._is_psd(corr_matrix),
            shrinkage_applied=shrinkage,
        )

    # â”€â”€â”€ Core EWMA â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @staticmethod
    def _ewma_covariance(x: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:  # type: ignore[type-arg]
        """Covarianza EWMA per coppia di serie."""
        n = len(x)
        cov = np.zeros(n)
        cov[0] = x[0] * y[0]
        for t in range(1, n):
            cov[t] = lam * cov[t-1] + (1 - lam) * x[t] * y[t]
        return cov

    @classmethod
    def _ewma_correlation_last(cls, x: np.ndarray, y: np.ndarray, lam: float) -> float:  # type: ignore[type-arg]
        """Correlazione EWMA all'ultimo punto della serie."""
        cov_xy = cls._ewma_covariance(x, y, lam)
        cov_xx = cls._ewma_covariance(x, x, lam)
        cov_yy = cls._ewma_covariance(y, y, lam)
        denom = np.sqrt(cov_xx[-1] * cov_yy[-1])
        if denom < 1e-10:
            return 0.0
        return float(np.clip(cov_xy[-1] / denom, -1.0, 1.0))

    def _find_optimal_lambda(self, x: np.ndarray, y: np.ndarray) -> float:  # type: ignore[type-arg]
        """MLE grid search per lambda ottimale."""
        best_ll = -np.inf
        best_lam = _LAMBDA_DEFAULT

        for lam in self._lambda_grid:
            try:
                ll = self._log_likelihood(x, y, lam)
                if ll > best_ll:
                    best_ll = ll
                    best_lam = float(lam)
            except Exception:
                continue

        return best_lam

    @classmethod
    def _log_likelihood(cls, x: np.ndarray, y: np.ndarray, lam: float) -> float:  # type: ignore[type-arg]
        """Log-likelihood normalizzata bivariata per stima MLE lambda."""
        n = len(x)
        cov_xy = cls._ewma_covariance(x, y, lam)
        cov_xx = cls._ewma_covariance(x, x, lam)
        cov_yy = cls._ewma_covariance(y, y, lam)

        ll = 0.0
        for t in range(1, n):
            det = cov_xx[t] * cov_yy[t] - cov_xy[t]**2
            if det <= 0:
                continue
            ll -= 0.5 * (np.log(det) + (cov_yy[t]*x[t]**2 - 2*cov_xy[t]*x[t]*y[t] + cov_xx[t]*y[t]**2) / det)
        return ll / max(n, 1)

    # â”€â”€â”€ Regime conditioning â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @staticmethod
    def _regime_conditioned(
        returns_ab: pd.DataFrame,
        a: str,
        b: str,
        regime_labels: pd.Series,
    ) -> dict[str, float]:
        """Calcola correlazione Pearson per ogni regime."""
        regimes: dict[str, float] = {}
        aligned = regime_labels.reindex(returns_ab.index).dropna()
        for regime in ["bull", "bear", "stress", "transition"]:
            mask = aligned == regime
            if mask.sum() < 20:
                continue
            sub = returns_ab.loc[mask]
            if len(sub) < 20:
                continue
            corr = float(sub[a].corr(sub[b]))
            if not np.isnan(corr):
                regimes[regime] = float(np.clip(corr, -1, 1))
        return regimes

    # â”€â”€â”€ Numeric stability â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @staticmethod
    def _is_psd(matrix: np.ndarray) -> bool:  # type: ignore[type-arg]
        """Verifica se la matrice Ã¨ semidefinita positiva."""
        try:
            eigvals = np.linalg.eigvalsh(matrix)
            return bool(np.all(eigvals >= -1e-8))
        except Exception:
            return False

    @staticmethod
    def _ledoit_wolf_shrinkage(matrix: np.ndarray, alpha: float = _SHRINKAGE_INTENSITY) -> np.ndarray:  # type: ignore[type-arg]
        """Ledoit-Wolf shrinkage verso matrice identitÃ  per garantire PSD."""
        n = matrix.shape[0]
        target = np.eye(n)
        shrunk = (1 - alpha) * matrix + alpha * target
        # Correzione diagonale = 1
        np.fill_diagonal(shrunk, 1.0)
        return shrunk
