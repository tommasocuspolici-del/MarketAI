"""Ensemble Combiner — stacking dinamico con pesi Kalman."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from shared.exceptions import AnalysisError, ConfigurationError
from shared.logger import get_logger

log = get_logger(__name__)

_SOFTMAX_CLIP: float = 50.0   # evita overflow in exp


@dataclass
class EnsembleResult:
    point_forecast: float
    model_weights: dict[str, float]    # model_id → weight
    model_forecasts: dict[str, float]  # model_id → individual forecast
    ensemble_method: str               # equal|ic_weighted|kalman|ridge_stacking


class EnsembleCombiner:
    """Combina previsioni da N modelli con pesi adattativi."""

    # ------------------------------------------------------------------ #
    # Equal weight                                                         #
    # ------------------------------------------------------------------ #

    def combine_equal_weight(self, forecasts: dict[str, float]) -> EnsembleResult:
        """Media semplice non pesata."""
        if not forecasts:
            raise ConfigurationError("forecasts dict must not be empty")
        n = len(forecasts)
        weights = {mid: 1.0 / n for mid in forecasts}
        point = float(np.mean(list(forecasts.values())))
        log.debug("ensemble.equal_weight", n_models=n, point_forecast=round(point, 4))
        return EnsembleResult(
            point_forecast=point,
            model_weights=weights,
            model_forecasts=dict(forecasts),
            ensemble_method="equal",
        )

    # ------------------------------------------------------------------ #
    # IC-weighted                                                          #
    # ------------------------------------------------------------------ #

    def combine_ic_weighted(
        self,
        forecasts: dict[str, float],
        ic_scores: dict[str, float],
    ) -> EnsembleResult:
        """Media pesata per Information Coefficient (IC) con softmax."""
        if not forecasts:
            raise ConfigurationError("forecasts dict must not be empty")

        ids = list(forecasts.keys())
        ics = np.array([ic_scores.get(mid, 0.0) for mid in ids], dtype=float)

        # Softmax stabile (clip evita overflow)
        ics_clipped = np.clip(ics, -_SOFTMAX_CLIP, _SOFTMAX_CLIP)
        exps = np.exp(ics_clipped - ics_clipped.max())
        w = exps / exps.sum()

        values = np.array([forecasts[mid] for mid in ids], dtype=float)
        point = float(np.dot(w, values))
        weights = {mid: float(wi) for mid, wi in zip(ids, w)}

        log.debug("ensemble.ic_weighted", n_models=len(ids), point_forecast=round(point, 4))
        return EnsembleResult(
            point_forecast=point,
            model_weights=weights,
            model_forecasts=dict(forecasts),
            ensemble_method="ic_weighted",
        )

    # ------------------------------------------------------------------ #
    # Ridge stacking                                                       #
    # ------------------------------------------------------------------ #

    def combine_ridge_stacking(
        self,
        forecasts_history: pd.DataFrame,
        actuals_history: pd.Series,
        new_forecasts: dict[str, float],
        alpha: float = 1.0,
    ) -> EnsembleResult:
        """Ridge regression per combinare previsioni passate vs reali.

        Args:
            forecasts_history: cols = model_ids, righe = osservazioni storiche.
            actuals_history:   valori reali corrispondenti.
            new_forecasts:     previsioni attuali da combinare.
            alpha:             parametro di regolarizzazione Ridge.
        """
        ids = list(new_forecasts.keys())

        if forecasts_history.empty or len(actuals_history) < 2:
            log.warning("ensemble.ridge_stacking.insufficient_history", n=len(actuals_history))
            return self.combine_equal_weight(new_forecasts)

        # Allinea colonne
        X = forecasts_history[ids].values.astype(float)
        y = actuals_history.values.astype(float)

        ridge = Ridge(alpha=alpha, fit_intercept=True)
        ridge.fit(X, y)

        coefs = ridge.coef_
        # Normalizza pesi positivi con clip (Ridge può dare pesi negativi)
        coefs_pos = np.clip(coefs, 0.0, None)
        total = coefs_pos.sum()
        if total <= 0.0:
            # Fallback a equal weight
            return self.combine_equal_weight(new_forecasts)
        w = coefs_pos / total

        new_X = np.array([new_forecasts[mid] for mid in ids], dtype=float)
        point = float(np.dot(w, new_X)) + float(ridge.intercept_) * (1.0 - w.sum())
        weights = {mid: float(wi) for mid, wi in zip(ids, w)}

        log.debug("ensemble.ridge_stacking", n_models=len(ids), point_forecast=round(point, 4))
        return EnsembleResult(
            point_forecast=point,
            model_weights=weights,
            model_forecasts=dict(new_forecasts),
            ensemble_method="ridge_stacking",
        )

    # ------------------------------------------------------------------ #
    # Kalman weight update                                                 #
    # ------------------------------------------------------------------ #

    def update_kalman_weights(
        self,
        weights: np.ndarray,
        forecast_errors: np.ndarray,
        process_noise: float = 0.001,
        observation_noise: float = 0.01,
    ) -> np.ndarray:
        """Aggiorna i pesi ensemble con un passo di Kalman semplificato.

        Modello: w_t = w_{t-1} + v_t (process noise)
                 e_t = H w_t + n_t   (observation = errors, noise)
        Aggiornamento proporzionale all'errore quadratico inverso.

        Returns:
            Pesi normalizzati aggiornati (somma = 1).
        """
        weights = np.asarray(weights, dtype=float)
        forecast_errors = np.asarray(forecast_errors, dtype=float)

        if weights.shape != forecast_errors.shape:
            raise AnalysisError("weights and forecast_errors must have the same shape")

        # Predizione: i pesi non cambiano (random walk)
        P_pred = np.eye(len(weights)) * process_noise

        # Kalman gain semplificato (scalare per ogni modello)
        R = np.eye(len(weights)) * observation_noise
        K = P_pred @ np.linalg.inv(P_pred + R)

        # Innovation: quanto ogni modello sbaglia rispetto alla media
        innovation = -forecast_errors  # inversamente proporzionale all'errore

        # Aggiornamento
        w_updated = weights + K @ (innovation - weights)

        # Clip negativi e normalizza
        w_updated = np.clip(w_updated, 0.0, None)
        total = w_updated.sum()
        if total <= 0.0:
            return np.ones(len(weights)) / len(weights)

        normalized = w_updated / total
        log.debug("ensemble.kalman_update", weights=normalized.round(4).tolist())
        return normalized
