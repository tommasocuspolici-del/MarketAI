"""VAR/VECM Engine — modello multivariato per macro (feature flag: var_vecm_engine)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from shared.feature_flags import is_enabled
from shared.logger import get_logger

if TYPE_CHECKING:
    pass

log = get_logger(__name__)

FEATURE_FLAG = "var_vecm_engine"
DEFAULT_LAGS: int = 4
DEFAULT_HORIZON: int = 12  # months

# Costanti per ADF test
_ADF_SIGNIFICANCE: float = 0.05


@dataclass
class VARForecast:
    variable: str
    horizon_months: int
    point_forecast: float
    forecast_se: float
    is_cointegrated: bool


class VAREngine:
    """VAR/VECM per serie macro interconnesse.

    Usa statsmodels VAR. Richiede feature flag 'var_vecm_engine'.
    Fallback: naive forecast se statsmodels non disponibile o flag disabilitato.
    """

    DEFAULT_VARIABLES: list[str] = [
        "FEDFUNDS", "CPIAUCSL", "GDPC1", "BAMLH0A0HYM2", "UNRATE"
    ]

    def __init__(self, max_lags: int = DEFAULT_LAGS) -> None:
        self._max_lags = max_lags
        self._fitted_model: Any | None = None
        self._fitted_result: Any | None = None
        self._columns: list[str] = []
        self._is_cointegrated: bool = False
        self._lag_order: int = 0

    # ------------------------------------------------------------------ #
    # Fitting                                                              #
    # ------------------------------------------------------------------ #

    def fit(self, data: pd.DataFrame) -> VAREngine:
        """Addestra VAR o VECM se cointegrazione rilevata (ADF test).

        Se il feature flag 'var_vecm_engine' è disabilitato, restituisce self
        senza addestrare (naive forecast sarà usato in forecast()).
        """
        if not is_enabled(FEATURE_FLAG):
            log.warning("var_engine.feature_disabled", flag=FEATURE_FLAG)
            self._columns = list(data.columns)
            return self

        try:
            from statsmodels.tsa.stattools import adfuller
            from statsmodels.tsa.vector_ar.var_model import VAR
        except ImportError:
            log.warning("var_engine.statsmodels_not_available")
            self._columns = list(data.columns)
            return self

        self._columns = list(data.columns)
        clean_data = data.dropna()

        if len(clean_data) < self._max_lags + 10:
            log.warning(
                "var_engine.insufficient_data",
                n=len(clean_data),
                required=self._max_lags + 10,
            )
            return self

        # Test di stazionarietà per decidere VAR vs VECM
        self._is_cointegrated = self._check_cointegration(clean_data, adfuller)

        try:
            model = VAR(clean_data)
            # Selezione automatica lag order (AIC), limitata a max_lags
            lag_result = model.select_order(maxlags=self._max_lags)
            selected_lags = min(
                lag_result.aic if lag_result.aic else self._max_lags,
                self._max_lags,
            )
            selected_lags = max(1, int(selected_lags))
            self._lag_order = selected_lags

            result = model.fit(maxlags=selected_lags)
            self._fitted_model = model
            self._fitted_result = result

            log.info(
                "var_engine.fitted",
                variables=self._columns,
                lags=selected_lags,
                is_cointegrated=self._is_cointegrated,
            )
        except Exception as exc:
            log.error("var_engine.fit_failed", error=str(exc))

        return self

    # ------------------------------------------------------------------ #
    # Forecasting                                                          #
    # ------------------------------------------------------------------ #

    def forecast(self, steps: int = DEFAULT_HORIZON) -> list[VARForecast]:
        """Genera previsioni per `steps` periodi in avanti.

        Fallback naive: usa l'ultimo valore osservato come previsione.
        """
        if not self.is_fitted():
            log.warning("var_engine.not_fitted_using_naive")
            return []

        try:
            from statsmodels.tsa.vector_ar.var_model import VARResultsWrapper
        except ImportError:
            return []

        if self._fitted_result is None:
            return []

        try:
            # statsmodels VAR forecast: richiede ultimo osservazione (lag finestra)
            last_obs = self._fitted_result.endog[-self._lag_order:]
            fc_array = self._fitted_result.forecast(y=last_obs, steps=steps)
            # fc_array shape: (steps, n_vars)
            mse_array = self._compute_forecast_se(steps)

            results: list[VARForecast] = []
            for step_idx in range(steps):
                for var_idx, var_name in enumerate(self._columns):
                    results.append(
                        VARForecast(
                            variable=var_name,
                            horizon_months=step_idx + 1,
                            point_forecast=float(fc_array[step_idx, var_idx]),
                            forecast_se=float(mse_array[step_idx, var_idx]),
                            is_cointegrated=self._is_cointegrated,
                        )
                    )
            log.info("var_engine.forecast_done", steps=steps, n_results=len(results))
            return results

        except Exception as exc:
            log.error("var_engine.forecast_failed", error=str(exc))
            return []

    def is_fitted(self) -> bool:
        """Restituisce True se il modello è stato addestrato con successo."""
        return self._fitted_result is not None

    def get_lag_order(self) -> int:
        """Restituisce il lag order selezionato."""
        return self._lag_order

    def impulse_response(self, periods: int = 10) -> pd.DataFrame:
        """Calcola le Impulse Response Functions (IRF).

        Returns:
            DataFrame con shape (periods * n_vars, n_vars).
        """
        if not self.is_fitted() or self._fitted_result is None:
            log.warning("var_engine.irf_not_fitted")
            return pd.DataFrame()

        try:
            irf = self._fitted_result.irf(periods=periods)
            # irf.irfs shape: (periods+1, n_vars, n_vars)
            irfs_flat = irf.irfs.reshape(-1, len(self._columns))
            df = pd.DataFrame(irfs_flat, columns=self._columns)
            df.index.name = "period"
            return df
        except Exception as exc:
            log.error("var_engine.irf_failed", error=str(exc))
            return pd.DataFrame()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _check_cointegration(self, data: pd.DataFrame, adfuller: Any) -> bool:
        """Verifica la cointegrazione tramite ADF test su ogni serie."""
        n_nonstationary = 0
        for col in data.columns:
            try:
                result = adfuller(data[col].dropna())
                p_value = float(result[1])
                if p_value > _ADF_SIGNIFICANCE:
                    n_nonstationary += 1
            except Exception:
                pass
        # Se la maggioranza delle serie è non-stazionaria → probabile cointegrazione
        is_coint = n_nonstationary > len(data.columns) / 2
        log.debug(
            "var_engine.cointegration_check",
            n_nonstationary=n_nonstationary,
            n_total=len(data.columns),
            is_cointegrated=is_coint,
        )
        return is_coint

    def _compute_forecast_se(self, steps: int) -> np.ndarray:
        """Calcola deviazione standard previsioni (propagazione errore VAR)."""
        if self._fitted_result is None:
            return np.zeros((steps, len(self._columns)))
        try:
            # mse_cum_resid: (steps, n_vars, n_vars) — usiamo la radice della diagonale
            mse = self._fitted_result.forecast_cov(steps=steps)
            se = np.sqrt(np.array([np.diag(mse[s]) for s in range(steps)]))
            return se
        except Exception:
            return np.zeros((steps, len(self._columns)))
