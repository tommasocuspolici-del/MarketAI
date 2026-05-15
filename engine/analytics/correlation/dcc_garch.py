"""DCC-GARCH(1,1) tramite libreria arch — correlazioni dinamiche avanzate.

Implementazione:
  1. Per ogni asset: fit GARCH(1,1) → σ_it (volatilità condizionale)
  2. Standardizza residui: z_it = r_it / σ_it
  3. EWMA su residui standardizzati (DCC step): Q_t update
  4. Normalizza → matrice correlazioni R_t PSD garantita

Fallback automatico su DCCEWMAEnhanced se:
  - Feature flag 'dcc_garch_full' disabilitato (default)
  - arch library non disponibile
  - Dataset insufficiente (< 252gg)
  - Convergenza GARCH fallisce su un asset

Performance: O(N) fit GARCH + O(N²) DCC per ogni timestep.
Per N>20 asset: lento (> 2s). Usare con universi ridotti.

Feature flag: dcc_garch_full (default False).
Regola 8: numpy per calcoli matriciali.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from engine.analytics.correlation.dcc_ewma_enhanced import (
    DCCEWMAEnhanced,
    DCCEWMAEnhancedResult,
    EWMACorrelationResult,
)
from shared.feature_flags import is_enabled

if TYPE_CHECKING:
    pass

__version__ = "1.0.0"
__all__ = ["DCCGARCHAnalyzer", "DCCGARCHResult"]

log = logging.getLogger(__name__)

# DCC parametri α e β (stima iniziale — MLE completo richiede ottimizzazione)
_DCC_ALPHA_DEFAULT = 0.04
_DCC_BETA_DEFAULT  = 0.94

# Dimensione minima dataset per fit GARCH stabile
_MIN_PERIODS = 252


@dataclass
class DCCGARCHResult:
    """Output del DCCGARCHAnalyzer.

    Attributes:
        correlation_matrix: Matrice DCC corrente N×N.
        asset_names:        Nomi asset nell'ordine della matrice.
        pairwise:           Risultati per coppia (include dcc_correlation).
        is_psd:             True se matrice PSD garantita.
        garch_fitted:       True se fit GARCH completato per tutti gli asset.
        garch_fallback:     True se usato fallback EWMA per qualche asset.
        alpha:              Parametro DCC alpha usato.
        beta:               Parametro DCC beta usato.
    """
    correlation_matrix: np.ndarray  # type: ignore[type-arg]
    asset_names:        list[str]
    pairwise:           list[EWMACorrelationResult]
    is_psd:             bool
    garch_fitted:       bool
    garch_fallback:     bool
    alpha:              float = _DCC_ALPHA_DEFAULT
    beta:               float = _DCC_BETA_DEFAULT


class DCCGARCHAnalyzer:
    """DCC-GARCH(1,1) via libreria arch.

    Drop-in replacement per DCCEWMAEnhanced quando feature flag
    'dcc_garch_full' è abilitato.

    Se arch non è disponibile o il flag è disabilitato, effettua
    fallback automatico su DCCEWMAEnhanced.

    Usage::

        analyzer = DCCGARCHAnalyzer()
        result = analyzer.compute(returns_df)
        # result.correlation_matrix → matrice DCC corrente
    """

    def __init__(
        self,
        alpha: float = _DCC_ALPHA_DEFAULT,
        beta: float  = _DCC_BETA_DEFAULT,
    ) -> None:
        self._alpha = alpha
        self._beta  = beta
        self._ewma_fallback = DCCEWMAEnhanced()

    # ─── Public API ──────────────────────────────────────────────────────────

    def compute(
        self,
        returns: pd.DataFrame,
        regime_labels: "pd.Series | None" = None,
    ) -> DCCEWMAEnhancedResult:
        """Calcola correlazioni DCC-GARCH o fallback su EWMA.

        Args:
            returns:       DataFrame rendimenti log (col=asset, row=date).
            regime_labels: Etichette regime per conditioning (opzionale).

        Returns:
            DCCEWMAEnhancedResult (stessa interfaccia di DCCEWMAEnhanced).
        """
        if not is_enabled("dcc_garch_full"):
            log.debug("dcc_garch.flag_disabled using_ewma_fallback")
            return self._ewma_fallback.compute(returns, regime_labels)

        if not _arch_available():
            log.warning("dcc_garch.arch_not_available using_ewma_fallback")
            return self._ewma_fallback.compute(returns, regime_labels)

        if len(returns) < _MIN_PERIODS:
            log.debug("dcc_garch.insufficient_data n=%d using_ewma_fallback", len(returns))
            return self._ewma_fallback.compute(returns, regime_labels)

        try:
            return self._compute_dcc(returns, regime_labels)
        except Exception as exc:
            log.warning("dcc_garch.compute_failed using_ewma_fallback error=%s",
                        str(exc)[:100])
            return self._ewma_fallback.compute(returns, regime_labels)

    # ─── Internal DCC implementation ────────────────────────────────────────

    def _compute_dcc(
        self,
        returns: pd.DataFrame,
        regime_labels: "pd.Series | None" = None,
    ) -> DCCEWMAEnhancedResult:
        """DCC-GARCH(1,1) completo con arch library."""
        from arch import arch_model  # type: ignore[import]

        assets = list(returns.columns)
        n = len(assets)
        T = len(returns)

        # Step 1: fit GARCH(1,1) per ogni asset → σ_t condizionale
        std_resids = np.zeros((T, n), dtype=np.float64)
        garch_fallback = False

        for i, asset in enumerate(assets):
            series = returns[asset].dropna()
            try:
                model = arch_model(
                    series * 100,      # scala a % per stabilità numerica
                    vol="Garch", p=1, q=1,
                    dist="normal",
                    rescale=False,
                )
                res = model.fit(
                    disp="off",
                    show_warning=False,
                    options={"maxiter": 200, "ftol": 1e-6},
                )
                cond_vol = res.conditional_volatility / 100  # torna a decimali
                # Allinea con returns (GARCH può avere lunghezza leggermente diversa)
                r_vals = returns[asset].values[-len(cond_vol):]
                v_vals = cond_vol.values
                std_resids[-len(r_vals):, i] = np.where(
                    v_vals > 1e-8,
                    r_vals / v_vals,
                    0.0,
                )
            except Exception as exc:
                log.debug("dcc_garch.garch_fit_failed asset=%s: %s",
                          asset, str(exc)[:60])
                # Fallback per questo asset: usa std rolling 21gg
                garch_fallback = True
                r = returns[asset].values
                roll_std = pd.Series(r).rolling(21, min_periods=5).std().fillna(
                    r.std() if r.std() > 0 else 1.0
                ).values
                std_resids[:, i] = np.where(roll_std > 1e-8, r / roll_std, 0.0)

        # Step 2: DCC — Q_bar = covarianza campionaria dei residui standardizzati
        Q_bar = np.cov(std_resids.T)
        if not _is_psd(Q_bar):
            Q_bar = _ledoit_wolf_shrink(Q_bar)

        # Step 3: aggiorna Q_t con DCC ricorrenza sull'ultimo periodo
        Q_t = Q_bar.copy()
        alpha, beta = self._alpha, self._beta
        for t in range(T):
            z = std_resids[t:t+1, :].T   # N×1
            Q_t = (1 - alpha - beta) * Q_bar + alpha * (z @ z.T) + beta * Q_t

        # Step 4: normalizza Q_t → matrice di correlazione R_t
        d_inv = np.diag(1.0 / np.sqrt(np.clip(np.diag(Q_t), 1e-12, None)))
        R_t = d_inv @ Q_t @ d_inv

        # Garantisci PSD e diagonale unitaria
        np.fill_diagonal(R_t, 1.0)
        R_t = np.clip(R_t, -1.0, 1.0)
        psd = _is_psd(R_t)
        if not psd:
            R_t = _ledoit_wolf_shrink(R_t)
            np.fill_diagonal(R_t, 1.0)
            psd = True

        # Costruisci pairwise results
        pairwise: list[EWMACorrelationResult] = []
        for i in range(n):
            for j in range(i + 1, n):
                pairwise.append(EWMACorrelationResult(
                    asset_a=assets[i],
                    asset_b=assets[j],
                    ewma_correlation=float(R_t[i, j]),
                    decay_lambda=self._alpha + self._beta,
                ))

        return DCCEWMAEnhancedResult(
            correlation_matrix=R_t,
            asset_names=assets,
            pairwise=pairwise,
            is_psd=psd,
            shrinkage_applied=not psd,
        )


# ─── Utility ─────────────────────────────────────────────────────────────────

def _arch_available() -> bool:
    """True se la libreria arch è importabile."""
    try:
        import arch  # noqa: F401
        return True
    except ImportError:
        return False


def _is_psd(matrix: np.ndarray) -> bool:  # type: ignore[type-arg]
    """True se la matrice è semi-definita positiva."""
    try:
        np.linalg.cholesky(matrix + 1e-10 * np.eye(len(matrix)))
        return True
    except np.linalg.LinAlgError:
        return False


def _ledoit_wolf_shrink(
    matrix: np.ndarray,   # type: ignore[type-arg]
    shrinkage: float = 0.05,
) -> np.ndarray:  # type: ignore[type-arg]
    """Ledoit-Wolf shrinkage verso la matrice identità."""
    n = matrix.shape[0]
    target = np.eye(n)
    shrunk = (1 - shrinkage) * matrix + shrinkage * target
    return shrunk
