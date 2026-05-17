"""SimpleForecaster: previsione 3-scenari minimale per UI (v7.1.2).

Implementa il modello GBM (geometric Brownian motion) con drift e
volatilita' stimati dallo storico. Genera 3 path forward:

  - **base**: drift osservato (mediana storica dei log-returns).
  - **pessimistico**: drift osservato - 1.65 sigma annualizzato.
  - **ottimistico**: drift osservato + 1.65 sigma annualizzato.

Il fattore 1.65 corrisponde al 95% di confidenza one-sided in distribuzione
normale (z = 1.645). E' una semplificazione: la convenzione del progetto
(anti-pattern "Previsione senza 3 scenari") richiede pessimistico/base/
ottimistico, non intervalli di confidenza completi.

Limitazioni dichiarate (mostrate in UI):
  - Modello parametrico GBM, non econometrico (no ARIMA, no Prophet).
  - Assume returns log-normali e indipendenti — palesemente falso per
    asset reali. Adeguato come ESPLORATIVO, non come trading signal.
  - Volatility forecast = volatility realizzata (no GARCH).

Forecast veri (Prophet, ARIMA con backtesting walk-forward) sono in
roadmap nelle settimane 4-7 della Roadmap Unificata 2.0.

Convenzioni v6.0 rispettate: type hints completi, structlog, no magic
numbers, numpy per math.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd

from shared.logger import get_logger

__version__ = "7.1.2"

__all__ = [
    "ForecastScenario",
    "ForecastResult",
    "SimpleForecaster",
]

log = get_logger(__name__)

# Z-score per confidenza ~95% one-sided (1.645). Esposto come costante
# nominata per Regola 7 (no magic numbers).
_Z_95_ONE_SIDED: float = 1.6449

# Trading days per year (approssimazione standard finanza).
_TRADING_DAYS_PER_YEAR: int = 252

# Numero minimo di osservazioni per calcolare drift/volatility affidabili.
_MIN_OBSERVATIONS: int = 30


@dataclass(frozen=True, slots=True)
class ForecastScenario:
    """Singolo scenario di forecast."""

    name: str           # 'pessimistic' | 'base' | 'optimistic'
    path: npt.NDArray[np.float64]   # array di prezzi forecast (lunghezza = horizon_days)
    expected_return_pct: float    # % return totale a fine horizon
    annualized_drift: float        # drift annualizzato usato (log-space)


@dataclass(frozen=True, slots=True)
class ForecastResult:
    """Risultato completo: 3 scenari + metadati."""

    ticker: str
    last_price: float
    horizon_days: int
    historical_days: int
    historical_volatility_annualized: float
    historical_drift_annualized: float
    scenarios: tuple[ForecastScenario, ForecastScenario, ForecastScenario]


class SimpleForecaster:
    """Forecaster GBM con 3 scenari per esplorazione visuale.

    Esempio d'uso::

        forecaster = SimpleForecaster()
        result = forecaster.forecast(
            close_prices=ohlcv_df["close"].values,
            ticker="AAPL",
            horizon_days=60,
        )
        for sc in result.scenarios:
            print(sc.name, sc.expected_return_pct)
    """

    def __init__(
        self,
        z_score: float = _Z_95_ONE_SIDED,
        trading_days: int = _TRADING_DAYS_PER_YEAR,
    ) -> None:
        self._z = float(z_score)
        self._td = int(trading_days)

    def forecast(
        self,
        close_prices: npt.NDArray[np.float64] | pd.Series,
        *,
        ticker: str,
        horizon_days: int,
    ) -> ForecastResult:
        """Calcola forecast 3-scenari su una serie di prezzi storici.

        Args:
            close_prices: Array 1D dei prezzi di chiusura (ordinati cronologicamente).
            ticker: Symbol per logging/labelling.
            horizon_days: Numero di giorni forward da forecastare.

        Returns:
            :class:`ForecastResult` con 3 scenari e metadati.

        Raises:
            ValueError: Se ``close_prices`` ha meno di _MIN_OBSERVATIONS punti
                o se contiene valori non positivi (necessari per log-returns).
        """
        prices = np.asarray(close_prices, dtype=np.float64).flatten()
        prices = prices[~np.isnan(prices)]
        if len(prices) < _MIN_OBSERVATIONS:
            raise ValueError(
                f"Almeno {_MIN_OBSERVATIONS} osservazioni richieste, "
                f"forniti {len(prices)} per {ticker}"
            )
        if (prices <= 0).any():
            raise ValueError(
                f"Prezzi non positivi rilevati per {ticker}: il forecaster GBM "
                "richiede prezzi strettamente > 0 per calcolare log-returns."
            )
        if horizon_days <= 0:
            raise ValueError(f"horizon_days deve essere > 0, ricevuto {horizon_days}")

        # Log-returns giornalieri
        log_returns = np.diff(np.log(prices))
        # Drift e volatility daily
        mu_daily = float(np.mean(log_returns))
        sigma_daily = float(np.std(log_returns, ddof=1))

        # Annualizzati per esposizione metadata
        mu_annual = mu_daily * self._td
        sigma_annual = sigma_daily * np.sqrt(self._td)

        last_price = float(prices[-1])

        # Per i 3 scenari useremo drift annual aggiustato di +/- z*sigma_annual,
        # poi riconvertito a daily.
        drift_pessim_daily = (mu_annual - self._z * sigma_annual) / self._td
        drift_base_daily = mu_daily
        drift_optim_daily = (mu_annual + self._z * sigma_annual) / self._td

        scenarios: list[ForecastScenario] = []
        for name, drift_d, drift_a in (
            ("pessimistic", drift_pessim_daily, mu_annual - self._z * sigma_annual),
            ("base", drift_base_daily, mu_annual),
            ("optimistic", drift_optim_daily, mu_annual + self._z * sigma_annual),
        ):
            # Path deterministico (no random shock): media del processo GBM.
            # P_t = P_0 * exp(drift * t)  (drift gia' include il -0.5*sigma^2 implicito
            # se usassimo log-returns direttamente; qui usiamo drift naive perche'
            # vogliamo dare l'aspettativa visiva, non simulare percorsi stocastici).
            t_array = np.arange(1, horizon_days + 1, dtype=np.float64)
            path = last_price * np.exp(drift_d * t_array)
            expected_return = (path[-1] - last_price) / last_price * 100.0
            scenarios.append(
                ForecastScenario(
                    name=name,
                    path=path,
                    expected_return_pct=float(expected_return),
                    annualized_drift=float(drift_a),
                )
            )

        log.info(
            "simple_forecaster.computed",
            ticker=ticker,
            historical_days=len(prices),
            horizon_days=horizon_days,
            mu_annual=round(mu_annual, 4),
            sigma_annual=round(sigma_annual, 4),
        )

        return ForecastResult(
            ticker=ticker,
            last_price=last_price,
            horizon_days=horizon_days,
            historical_days=len(prices),
            historical_volatility_annualized=float(sigma_annual),
            historical_drift_annualized=float(mu_annual),
            scenarios=(scenarios[0], scenarios[1], scenarios[2]),
        )
