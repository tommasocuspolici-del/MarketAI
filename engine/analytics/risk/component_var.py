"""Marginal + Component VaR per posizioni del portafoglio.

Il Component VaR decompone il VaR totale del portafoglio per asset,
permettendo di identificare i contributori principali al rischio.

Component VaR_i = w_i * (∂VaR / ∂w_i) = w_i * Marginal VaR_i
Σ Component VaR_i = Portfolio VaR  (proprietà di additivià)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from shared.logger import get_logger

__version__ = "11.0.0"

__all__ = ["ComponentVaRCalculator", "ComponentVaRResult"]

log = get_logger(__name__)

CONFIDENCE_DEFAULT: float = 0.95
EPSILON: float = 1e-4       # perturbazione per calcolo marginale numerico
MIN_OBS: int = 20           # osservazioni minime per stima affidabile


@dataclass
class ComponentVaRResult:
    """VaR componentiale per un singolo asset nel portafoglio."""

    ticker: str
    weight: float
    marginal_var: float    # ΔVaR per unità di peso aggiunta
    component_var: float   # weight × marginal_var
    pct_risk: float        # component_var / portfolio_var (come frazione)


class ComponentVaRCalculator:
    """Calcola Marginal e Component VaR per ogni posizione.

    Usa VaR parametrico gaussiano (z * sqrt(w'Σw)) con differenza finita
    per il marginal VaR, che garantisce la proprietà di additività esatta.
    """

    def __init__(self, confidence: float = CONFIDENCE_DEFAULT) -> None:
        self._confidence = confidence
        self._z = float(-stats.norm.ppf(1.0 - confidence))  # z-score positivo

    def compute(
        self,
        weights: np.ndarray,
        returns_matrix: pd.DataFrame,
        tickers: list[str],
    ) -> list[ComponentVaRResult]:
        """Calcola Component VaR per ogni posizione del portafoglio.

        Parameters
        ----------
        weights:
            Pesi portafoglio normalizzati (somma ≈ 1), array 1D.
        returns_matrix:
            DataFrame con colonne=tickers, righe=date (rendimenti giornalieri).
        tickers:
            Lista ticker in ordine corrispondente a weights.
        """
        weights = np.asarray(weights, dtype=float)
        n = len(tickers)

        if len(weights) != n:
            raise ValueError(
                f"weights length {len(weights)} != tickers length {n}"
            )
        if returns_matrix.shape[1] != n:
            raise ValueError(
                f"returns_matrix has {returns_matrix.shape[1]} cols != {n} tickers"
            )
        if len(returns_matrix) < MIN_OBS:
            log.warning(
                "component_var.insufficient_data",
                n_obs=len(returns_matrix),
                min_obs=MIN_OBS,
            )

        # Normalizza pesi
        w_sum = weights.sum()
        if abs(w_sum) > 1e-12:
            weights = weights / w_sum

        rets = returns_matrix[tickers].to_numpy(dtype=float)
        cov = np.atleast_2d(np.cov(rets, rowvar=False)) if rets.shape[0] > 1 else np.eye(n)

        # VaR portafoglio
        port_var = self._portfolio_var(weights, cov, self._z)

        results: list[ComponentVaRResult] = []
        for i, ticker in enumerate(tickers):
            mvar = self._marginal_var_numeric(weights, cov, i, self._z)
            comp_var = float(weights[i]) * mvar
            pct = (comp_var / port_var) if port_var > 1e-12 else 0.0

            results.append(
                ComponentVaRResult(
                    ticker=ticker,
                    weight=float(weights[i]),
                    marginal_var=mvar,
                    component_var=comp_var,
                    pct_risk=pct,
                )
            )

        log.info(
            "component_var.computed",
            n_assets=n,
            portfolio_var=round(port_var, 5),
            confidence=self._confidence,
        )
        return results

    def _portfolio_var(
        self,
        weights: np.ndarray,
        cov_matrix: np.ndarray,
        z_score: float,
    ) -> float:
        """VaR parametrico: z * sqrt(w'Σw)."""
        port_variance = float(weights @ cov_matrix @ weights)
        port_variance = max(port_variance, 0.0)
        return z_score * np.sqrt(port_variance)

    def _marginal_var_numeric(
        self,
        weights: np.ndarray,
        cov_matrix: np.ndarray,
        ticker_idx: int,
        z_score: float,
    ) -> float:
        """Marginal VaR analitico: z * (Σw)_i / sqrt(w'Σw).

        Formula analitica (più stabile di differenza finita):
        ∂VaR/∂w_i = z * (Σw)_i / sqrt(w'Σw)
        """
        port_vol = self._portfolio_var(weights, cov_matrix, z_score)
        if port_vol < 1e-12:
            return 0.0

        port_variance = (port_vol / z_score) ** 2
        port_std = np.sqrt(max(port_variance, 0.0))
        if port_std < 1e-12:
            return 0.0

        # Covarianza del singolo asset con il portafoglio
        cov_with_port = float(cov_matrix[ticker_idx] @ weights)
        return z_score * cov_with_port / port_std
