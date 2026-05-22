"""Conformal Prediction adattiva per serie temporali (Convenzione 34)."""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np

from shared.logger import get_logger

log = get_logger(__name__)

MIN_CALIBRATION: int = 30
DEFAULT_ALPHA: float = 0.10
DEFAULT_WINDOW: int = 252


@dataclass
class ConformalInterval:
    point_forecast: float
    lower: float
    upper: float
    coverage_level: float
    n_calibration: int
    is_valid: bool


class AdaptiveConformalPredictor:
    """Split conformal con finestre mobili per serie temporali.

    Usa il quantile corretto `ceil((1-alpha)(n+1)/n)` sui residui di calibrazione
    per costruire intervalli con copertura marginale garantita.
    """

    def __init__(
        self,
        alpha: float = DEFAULT_ALPHA,
        calibration_window: int = DEFAULT_WINDOW,
    ) -> None:
        self._alpha = alpha
        self._calibration_window = calibration_window
        self._residuals: list[float] = []

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def update(self, actual: float, forecast: float) -> None:
        """Aggiorna la finestra di calibrazione con il residuo |actual - forecast|."""
        residual = abs(actual - forecast)
        self._residuals.append(residual)
        # Mantieni finestra mobile
        if len(self._residuals) > self._calibration_window:
            self._residuals.pop(0)
        log.debug(
            "conformal.update",
            residual=round(residual, 6),
            n_calibration=len(self._residuals),
        )

    def predict_interval(self, point_forecast: float) -> ConformalInterval:
        """Calcola l'intervallo conforme attorno a `point_forecast`.

        Il quantile corretto è: q = ceil((1-alpha)(n+1)/n) / n
        Ovvero il quantile empirico ceil-index dei residui ordinati.
        """
        n = len(self._residuals)
        is_valid = n >= MIN_CALIBRATION

        if not is_valid:
            log.warning(
                "conformal.insufficient_calibration",
                n=n,
                required=MIN_CALIBRATION,
            )
            # Ritorna intervallo degenerato (uguale al punto)
            return ConformalInterval(
                point_forecast=point_forecast,
                lower=point_forecast,
                upper=point_forecast,
                coverage_level=1.0 - self._alpha,
                n_calibration=n,
                is_valid=False,
            )

        # Quantile corretto per garanzia di copertura marginale
        # k = ceil((1-alpha) * (n+1)) ma clippato a n
        k = min(math.ceil((1.0 - self._alpha) * (n + 1)), n)
        sorted_residuals = sorted(self._residuals)
        q_hat = sorted_residuals[k - 1]  # indice 0-based

        lower = point_forecast - q_hat
        upper = point_forecast + q_hat

        log.debug(
            "conformal.interval",
            point_forecast=round(point_forecast, 4),
            q_hat=round(q_hat, 6),
            k=k,
            n=n,
        )

        return ConformalInterval(
            point_forecast=point_forecast,
            lower=lower,
            upper=upper,
            coverage_level=1.0 - self._alpha,
            n_calibration=n,
            is_valid=True,
        )

    def reset(self) -> None:
        """Azzera la finestra di calibrazione."""
        self._residuals = []
        log.debug("conformal.reset")

    def n_calibration_samples(self) -> int:
        """Restituisce il numero corrente di campioni di calibrazione."""
        return len(self._residuals)
