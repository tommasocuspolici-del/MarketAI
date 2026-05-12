"""Labour Market Forecast Engine (Blocco B.4).

Ensemble ARIMA + Ridge per previsioni 1M/3M/6M su:
  · UNRATE (tasso disoccupazione)
  · NFP headline
  · Quits Rate (leading per wage growth +3-6M)

Feature per Ridge:
  · claims_4wk_ma  (t-1, t-2, t-3)
  · jolts_quits_rate (t-1)
  · jolts_openings_rate (t-1)
  · macro_composite_score (t-1)   — da DuckDB se disponibile

Regola 8: numpy per tutti i calcoli.
Regola anti-pattern: LLM NON usato per calcoli — solo per narrativa.
Benchmark target: forecast() 3 orizzonti < 5s.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import structlog
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from engine.analytics.labour_market.schemas import (
    ForecastBundle,
    Horizon,
    LabourForecastResult,
)

if TYPE_CHECKING:
    pass

__version__ = "1.0.0"
__all__ = ["LabourForecastEngine"]
log = structlog.get_logger(__name__)

HORIZON_STEPS: dict[str, int] = {"1M": 1, "3M": 3, "6M": 6}
_ARIMA_WEIGHT_DEFAULT = 0.5
_RIDGE_ALPHA          = 1.0


class LabourForecastEngine:
    """Ensemble forecaster ARIMA + Ridge per mercato del lavoro.

    Usage::
        engine = LabourForecastEngine()
        engine.fit(target=unrate_series, features=features_df)
        results = engine.forecast(["1M", "3M", "6M"], future_features, "UNRATE")
    """

    def __init__(self, arima_weight: float = _ARIMA_WEIGHT_DEFAULT) -> None:
        self._arima_weight = float(np.clip(arima_weight, 0.0, 1.0))
        self._ridge_weight = 1.0 - self._arima_weight
        self._scaler       = StandardScaler()
        self._ridge        = Ridge(alpha=_RIDGE_ALPHA)
        self._arima        = None   # Inizializzato in fit()
        self._fitted       = False

    def fit(self, target: pd.Series, features: pd.DataFrame) -> None:
        """Addestra Ridge su feature macro + ARIMA auto-selezione ordine.

        Args:
            target:   Serie target (es. UNRATE mensile, float).
            features: DataFrame con feature macro allineate per indice.

        Raises:
            ValueError: se dati insufficienti (< 24 osservazioni).
        """
        import pmdarima as pm  # lazy import per velocizzare startup

        aligned   = features.loc[features.index.isin(target.index)].dropna()
        y_train   = target.loc[aligned.index].dropna()
        aligned   = aligned.loc[y_train.index]

        if len(y_train) < 24:
            raise ValueError(
                f"LabourForecastEngine: dati insufficienti ({len(y_train)} < 24 obs)"
            )

        X_scaled = self._scaler.fit_transform(aligned.to_numpy(dtype=np.float64))
        self._ridge.fit(X_scaled, y_train.to_numpy(dtype=np.float64))

        # ARIMA con feature esogene — stepwise per velocità
        try:
            self._arima = pm.auto_arima(
                y_train.to_numpy(dtype=np.float64),
                exogenous         = X_scaled,
                seasonal          = False,
                stepwise          = True,
                suppress_warnings = True,
                error_action      = "ignore",
                max_p=4, max_q=4, max_d=2,
                information_criterion="aic",
            )
        except Exception:  # noqa: BLE001 — fallback: arima(1,1,0)
            log.warning("labour_forecast.arima_auto_failed_using_fallback")
            self._arima = pm.ARIMA(order=(1, 1, 0))
            self._arima.fit(y_train.to_numpy(dtype=np.float64))

        self._fitted    = True
        self._n_train   = len(y_train)
        self._X_sample  = X_scaled  # per var residua bootstrap

        order = getattr(self._arima, "order", None)
        log.info(
            "labour_forecast.fitted",
            n_samples=len(y_train),
            arima_order=order,
            features=list(aligned.columns),
        )

    def forecast(
        self,
        horizons:        list[Horizon],
        future_features: pd.DataFrame,
        target_metric:   str,
    ) -> LabourForecastResult:
        """Previsioni ensemble per ogni orizzonte.

        Args:
            horizons:        Lista orizzonti (es. ["1M","3M","6M"]).
            future_features: Feature per i periodi futuri (stesso schema di fit).
            target_metric:   Nome metrica (UNRATE / NFP / QUITS_RATE).

        Returns:
            LabourForecastResult con tutti i ForecastBundle.
        """
        if not self._fitted or self._arima is None:
            raise RuntimeError("LabourForecastEngine non ancora addestrato: chiama fit() prima")

        max_steps = max(HORIZON_STEPS[h] for h in horizons)
        # Prepara feature future (padding se necessario)
        X_fut_raw = future_features.iloc[:max_steps].to_numpy(dtype=np.float64)
        if len(X_fut_raw) < max_steps:
            # Pad con l'ultimo valore disponibile
            pad = np.tile(X_fut_raw[-1:], (max_steps - len(X_fut_raw), 1))
            X_fut_raw = np.vstack([X_fut_raw, pad])

        X_fut = self._scaler.transform(X_fut_raw)

        # ARIMA forecast con CI 90%
        try:
            arima_fc, conf_int = self._arima.predict(
                n_periods       = max_steps,
                exogenous       = X_fut,
                return_conf_int = True,
                alpha           = 0.10,
            )
        except Exception:  # noqa: BLE001
            # Fallback: ARIMA senza esogene
            try:
                arima_fc, conf_int = self._arima.predict(
                    n_periods=max_steps,
                    return_conf_int=True,
                    alpha=0.10,
                )
            except Exception:  # noqa: BLE001
                last_in_sample = float(self._arima.arima_res_.fittedvalues[-1])
                arima_fc = np.full(max_steps, last_in_sample)
                std_est  = float(np.std(self._arima.resid()))
                conf_int = np.column_stack([
                    arima_fc - 1.645 * std_est,
                    arima_fc + 1.645 * std_est,
                ])

        # Ridge forecast
        ridge_pred = self._ridge.predict(X_fut)

        # Bootstrap residua per CI Ridge (≥30 campioni)
        resid_std = float(np.std(
            self._ridge.predict(self._X_sample) -
            self._ridge.predict(self._X_sample)   # same data = 0 if overfitted
        )) if self._n_train >= 30 else abs(float(np.mean(ridge_pred)) * 0.05)
        if resid_std < 1e-6:
            # Usa std residui ARIMA come proxy
            try:
                resid_std = float(np.std(self._arima.resid()))
            except Exception:  # noqa: BLE001
                resid_std = abs(float(np.mean(ridge_pred)) * 0.05)

        bundles: list[ForecastBundle] = []
        for h in horizons:
            steps = HORIZON_STEPS[h]
            ap = float(np.mean(arima_fc[:steps]))
            al = float(np.mean(conf_int[:steps, 0]))
            au = float(np.mean(conf_int[:steps, 1]))
            rp = float(np.mean(ridge_pred[:steps]))

            point = self._arima_weight * ap + self._ridge_weight * rp
            lower = self._arima_weight * al + self._ridge_weight * (rp - 1.645 * resid_std)
            upper = self._arima_weight * au + self._ridge_weight * (rp + 1.645 * resid_std)

            bundles.append(ForecastBundle(
                horizon         = h,
                target_metric   = target_metric,
                point_forecast  = round(point, 4),
                lower_10        = round(lower, 4),
                upper_90        = round(upper, 4),
                model_used      = f"ensemble_a{self._arima_weight:.1f}_r{self._ridge_weight:.1f}",
                arima_forecast  = round(ap, 4),
                ridge_forecast  = round(rp, 4),
                ensemble_weight = self._arima_weight,
            ))
            log.info("labour_forecast.generated", horizon=h, metric=target_metric, point=round(point, 4))

        order = getattr(self._arima, "order", None)
        return LabourForecastResult(
            target_metric = target_metric,
            bundles       = tuple(bundles),
            n_train_obs   = self._n_train,
            arima_order   = tuple(order) if order is not None else None,  # type: ignore[arg-type]
        )

    @property
    def is_fitted(self) -> bool:
        """True se il modello è stato addestrato."""
        return self._fitted
