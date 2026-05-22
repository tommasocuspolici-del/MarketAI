"""SVI (Stochastic Volatility Inspired) Vol Surface Fit.

Parametrizza il variance smile con 5 parametri per scadenza:
  w(k) = a + b*(ρ*(k-m) + sqrt((k-m)² + σ²))
dove k = log-moneyness, w = total implied variance.

Feature flag: vol_surface_svi (default: true)

Calibrazione via scipy.optimize con SLSQP. Se scipy non disponibile,
fallback con RMSE elevato e parametri a zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from shared.feature_flags import is_enabled
from shared.logger import get_logger

if TYPE_CHECKING:
    import pandas as pd

__version__ = "11.0.0"

__all__ = ["SVIModel", "SVIParameters", "SVISurface"]

log = get_logger(__name__)

FEATURE_FLAG = "vol_surface_svi"

# Vincoli SVI per arbitrage-free:
# a >= 0 (total variance ≥ 0)
# b > 0 (convexity)
# |ρ| < 1 (correlation)
# σ > 0 (smoothness)
SVI_A_MIN: float = -0.5
SVI_A_MAX: float = 2.0
SVI_B_MIN: float = 1e-6
SVI_B_MAX: float = 2.0
SVI_RHO_MIN: float = -0.999
SVI_RHO_MAX: float = 0.999
SVI_M_MIN: float = -2.0
SVI_M_MAX: float = 2.0
SVI_SIGMA_MIN: float = 1e-6
SVI_SIGMA_MAX: float = 2.0

FALLBACK_RMSE: float = 999.0


@dataclass
class SVIParameters:
    """5 parametri del modello SVI per una data scadenza."""

    a: float      # level: total variance ATM
    b: float      # angle: vol of vol
    rho: float    # correlation: skew
    m: float      # translation: ATM shift
    sigma: float  # smoothness: smile curvature
    expiry_days: int
    fit_rmse: float   # RMSE del fit su IV (annualizzata)


@dataclass
class SVISurface:
    """Superficie SVI calcolata su più scadenze."""

    ticker: str
    parameters: list[SVIParameters]   # una per scadenza
    spot_price: float
    surface_rmse: float               # RMSE medio su tutte le scadenze


class SVIModel:
    """Calibrazione e valutazione del modello SVI.

    Usa scipy.optimize con SLSQP (Sequential Least Squares Programming)
    per calibrare i 5 parametri SVI su dati (k, w) per ogni scadenza.
    """

    MAX_ITERATIONS: int = 1000
    TOLERANCE: float = 1e-8

    def fit(
        self,
        log_moneyness: np.ndarray,
        total_variance: np.ndarray,
        expiry_days: int,
    ) -> SVIParameters:
        """Calibra SVI su dati (k, w) per una scadenza.

        Parameters
        ----------
        log_moneyness:
            k = log(K/F) — log-moneyness degli strike.
        total_variance:
            w = IV² × T — varianza totale implicita.
        expiry_days:
            Giorni alla scadenza.
        """
        try:
            from scipy.optimize import minimize
        except ImportError:
            log.warning("vol_surface_svi.scipy_not_available")
            return SVIParameters(
                a=0.0, b=0.0, rho=0.0, m=0.0, sigma=0.01,
                expiry_days=expiry_days, fit_rmse=FALLBACK_RMSE,
            )

        k = np.asarray(log_moneyness, dtype=float)
        w = np.asarray(total_variance, dtype=float)

        if len(k) < 3:
            log.warning("vol_surface_svi.insufficient_points", n=len(k))
            # Stima base: a = media w
            a0 = float(np.mean(w)) if len(w) > 0 else 0.04
            return SVIParameters(
                a=a0, b=1e-4, rho=0.0, m=0.0, sigma=0.1,
                expiry_days=expiry_days, fit_rmse=FALLBACK_RMSE,
            )

        def objective(params: np.ndarray) -> float:
            a, b, rho, m, sigma = params
            w_fit = self.w_svi(
                SVIParameters(a=a, b=b, rho=rho, m=m, sigma=sigma,
                              expiry_days=expiry_days, fit_rmse=0.0),
                k,
            )
            residuals = w_fit - w
            return float(np.sum(residuals**2))

        # Initial guess
        w_mean = float(np.mean(w))
        x0 = np.array([max(w_mean * 0.5, 1e-4), 0.1, -0.3, 0.0, 0.2])

        bounds = [
            (SVI_A_MIN, SVI_A_MAX),
            (SVI_B_MIN, SVI_B_MAX),
            (SVI_RHO_MIN, SVI_RHO_MAX),
            (SVI_M_MIN, SVI_M_MAX),
            (SVI_SIGMA_MIN, SVI_SIGMA_MAX),
        ]

        try:
            result = minimize(
                objective,
                x0,
                method="SLSQP",
                bounds=bounds,
                options={
                    "maxiter": self.MAX_ITERATIONS,
                    "ftol": self.TOLERANCE,
                },
            )
            a, b, rho, m, sigma = result.x
            w_fit = self.w_svi(
                SVIParameters(a=a, b=b, rho=rho, m=m, sigma=sigma,
                              expiry_days=expiry_days, fit_rmse=0.0),
                k,
            )
            # RMSE in IV space: sqrt(w/T) - sqrt(w_fit/T)
            T = expiry_days / 252.0
            if T > 1e-6:
                iv_actual = np.sqrt(np.maximum(w, 0.0) / T)
                iv_fitted = np.sqrt(np.maximum(w_fit, 0.0) / T)
                rmse = float(np.sqrt(np.mean((iv_actual - iv_fitted)**2)))
            else:
                rmse = float(np.sqrt(result.fun / max(len(k), 1)))

            log.debug(
                "vol_surface_svi.fit_complete",
                expiry_days=expiry_days,
                rmse=round(rmse, 5),
                success=result.success,
            )

            return SVIParameters(
                a=float(a), b=float(b), rho=float(rho),
                m=float(m), sigma=float(sigma),
                expiry_days=expiry_days, fit_rmse=rmse,
            )

        except Exception as exc:
            log.warning("vol_surface_svi.fit_failed", error=str(exc))
            return SVIParameters(
                a=float(w_mean), b=1e-4, rho=0.0, m=0.0, sigma=0.1,
                expiry_days=expiry_days, fit_rmse=FALLBACK_RMSE,
            )

    def fit_surface(
        self,
        ticker: str,
        option_chain: "pd.DataFrame",
        spot_price: float,
    ) -> SVISurface:
        """Calibra SVI per ogni scadenza disponibile.

        Parameters
        ----------
        ticker:
            Simbolo dell'asset.
        option_chain:
            DataFrame con colonne: strike, iv, expiry_days.
        spot_price:
            Prezzo spot corrente dell'asset.
        """
        if spot_price <= 0:
            log.warning("vol_surface_svi.invalid_spot", ticker=ticker, spot=spot_price)
            return SVISurface(ticker=ticker, parameters=[], spot_price=spot_price, surface_rmse=FALLBACK_RMSE)

        required_cols = {"strike", "iv", "expiry_days"}
        if not required_cols.issubset(set(option_chain.columns)):
            missing = required_cols - set(option_chain.columns)
            log.warning("vol_surface_svi.missing_columns", missing=missing)
            return SVISurface(ticker=ticker, parameters=[], spot_price=spot_price, surface_rmse=FALLBACK_RMSE)

        all_params: list[SVIParameters] = []
        for expiry in sorted(option_chain["expiry_days"].unique()):
            sub = option_chain[option_chain["expiry_days"] == expiry].dropna(subset=["strike", "iv"])
            if len(sub) < 3:
                continue

            T = expiry / 252.0
            if T < 1e-6:
                continue

            # Log-moneyness k = log(K / F) ≈ log(K / spot) per semplicità
            k = np.log(sub["strike"].to_numpy(dtype=float) / spot_price)
            iv = sub["iv"].to_numpy(dtype=float)
            w = iv**2 * T   # total variance

            params = self.fit(k, w, int(expiry))
            all_params.append(params)

        surface_rmse = (
            float(np.mean([p.fit_rmse for p in all_params]))
            if all_params else FALLBACK_RMSE
        )

        log.info(
            "vol_surface_svi.surface_fitted",
            ticker=ticker,
            n_expiries=len(all_params),
            surface_rmse=round(surface_rmse, 5),
        )

        return SVISurface(
            ticker=ticker,
            parameters=all_params,
            spot_price=spot_price,
            surface_rmse=surface_rmse,
        )

    def iv_from_svi(
        self,
        params: SVIParameters,
        log_moneyness: np.ndarray,
    ) -> np.ndarray:
        """Calcola IV da parametri SVI: IV = sqrt(w(k) / T).

        Parameters
        ----------
        params:
            Parametri SVI calibrati per una scadenza.
        log_moneyness:
            Array di log-moneyness k = log(K/F).
        """
        T = params.expiry_days / 252.0
        if T < 1e-10:
            return np.zeros_like(log_moneyness, dtype=float)

        w = self.w_svi(params, log_moneyness)
        w_positive = np.maximum(w, 0.0)
        return np.sqrt(w_positive / T)

    def w_svi(
        self,
        params: SVIParameters,
        k: np.ndarray,
    ) -> np.ndarray:
        """Variance totale w(k) dal modello SVI.

        w(k) = a + b*(ρ*(k-m) + sqrt((k-m)² + σ²))
        """
        k = np.asarray(k, dtype=float)
        a, b, rho, m, sigma = params.a, params.b, params.rho, params.m, params.sigma
        return a + b * (rho * (k - m) + np.sqrt((k - m)**2 + sigma**2))
