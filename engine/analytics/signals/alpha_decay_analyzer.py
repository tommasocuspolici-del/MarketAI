"""Alpha Decay Analyzer — calcola half-life del decadimento IC."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared.logger import get_logger

log = get_logger(__name__)

DECAY_R2_THRESHOLD: float = 0.50   # R² minimo per considerare il fit affidabile
LN2: float = float(np.log(2))


@dataclass
class DecayResult:
    signal_id: str
    half_life_days: int        # -1 if no decay detected
    decay_rate: float          # lambda in IC(t) = IC_0 * exp(-lambda*t)
    r_squared: float           # goodness of fit
    is_decaying: bool          # True if IC decays significantly


class AlphaDecayAnalyzer:
    """Calcola il half-life del decadimento dell'Information Coefficient.

    Fit un modello esponenziale: IC(h) = a * exp(-lambda * h)
    Half-life = ln(2) / lambda
    """

    MIN_HORIZONS: int = 3   # Minimo 3 orizzonti per fit

    def compute(
        self,
        signal_id: str,
        ic_by_horizon: dict[int, float],  # horizon_days → IC mean
    ) -> DecayResult:
        """Calcola il decay esponenziale dell'IC su più orizzonti.

        Args:
            signal_id: Identificatore del segnale.
            ic_by_horizon: Dizionario {horizon_days: IC_mean}.

        Returns:
            DecayResult con half_life, decay_rate, r_squared e is_decaying.
        """
        if len(ic_by_horizon) < self.MIN_HORIZONS:
            log.warning(
                "alpha_decay.insufficient_horizons",
                signal_id=signal_id,
                n_horizons=len(ic_by_horizon),
                min_required=self.MIN_HORIZONS,
            )
            return DecayResult(
                signal_id=signal_id,
                half_life_days=-1,
                decay_rate=0.0,
                r_squared=0.0,
                is_decaying=False,
            )

        horizons = np.array(sorted(ic_by_horizon.keys()), dtype=float)
        ic_values = np.array([ic_by_horizon[int(h)] for h in horizons], dtype=float)

        # Filtra valori non positivi per il fit log-lineare
        positive_mask = ic_values > 0
        if positive_mask.sum() < self.MIN_HORIZONS:
            # Proviamo con i valori assoluti
            ic_abs = np.abs(ic_values)
            positive_mask = ic_abs > 1e-9
            if positive_mask.sum() < self.MIN_HORIZONS:
                log.info(
                    "alpha_decay.no_positive_ic",
                    signal_id=signal_id,
                )
                return DecayResult(
                    signal_id=signal_id,
                    half_life_days=-1,
                    decay_rate=0.0,
                    r_squared=0.0,
                    is_decaying=False,
                )
            horizons_fit = horizons[positive_mask]
            ic_fit = ic_abs[positive_mask]
        else:
            horizons_fit = horizons[positive_mask]
            ic_fit = ic_values[positive_mask]

        try:
            # Linearizzazione: log(IC) = log(a) - lambda * h
            log_ic = np.log(ic_fit)
            # Fit lineare: y = intercept + slope * x
            slope, intercept = np.polyfit(horizons_fit, log_ic, 1)

            # lambda = -slope (positivo se IC decade)
            decay_rate = float(-slope)

            # Calcolo R²
            log_ic_pred = intercept + slope * horizons_fit
            ss_res = float(np.sum((log_ic - log_ic_pred) ** 2))
            ss_tot = float(np.sum((log_ic - np.mean(log_ic)) ** 2))
            r_squared = float(1.0 - ss_res / ss_tot) if ss_tot > 1e-12 else 0.0

            # Half-life = ln(2) / lambda (positivo solo se IC decade)
            if decay_rate > 1e-9:
                half_life_days = int(round(LN2 / decay_rate))
            else:
                half_life_days = -1

            # Il segnale è in decay se: slope negativo, R² accettabile, half-life positivo
            is_decaying = (
                decay_rate > 1e-9
                and r_squared >= DECAY_R2_THRESHOLD
                and half_life_days > 0
            )

            log.info(
                "alpha_decay.computed",
                signal_id=signal_id,
                half_life_days=half_life_days,
                decay_rate=round(decay_rate, 6),
                r_squared=round(r_squared, 4),
                is_decaying=is_decaying,
            )

            return DecayResult(
                signal_id=signal_id,
                half_life_days=half_life_days,
                decay_rate=decay_rate,
                r_squared=r_squared,
                is_decaying=is_decaying,
            )

        except (np.linalg.LinAlgError, ValueError, FloatingPointError) as exc:
            log.warning("alpha_decay.fit_failed", signal_id=signal_id, error=str(exc))
            return DecayResult(
                signal_id=signal_id,
                half_life_days=-1,
                decay_rate=0.0,
                r_squared=0.0,
                is_decaying=False,
            )
