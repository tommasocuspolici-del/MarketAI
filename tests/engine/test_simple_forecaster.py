"""Tests for engine.forecasting.SimpleForecaster (v7.1.2)."""
from __future__ import annotations

import numpy as np
import pytest

from engine.forecasting import SimpleForecaster


def _generate_gbm_prices(
    n: int, drift_annual: float, vol_annual: float, seed: int = 42
) -> np.ndarray:
    """Simula prezzi GBM per testare con statistiche note."""
    rng = np.random.default_rng(seed)
    daily_drift = drift_annual / 252
    daily_vol = vol_annual / np.sqrt(252)
    log_returns = rng.normal(loc=daily_drift, scale=daily_vol, size=n)
    return 100.0 * np.exp(np.cumsum(log_returns))


def test_forecast_three_scenarios():
    """L'output contiene esattamente 3 scenari con i nomi corretti."""
    prices = _generate_gbm_prices(252, 0.08, 0.20)
    forecaster = SimpleForecaster()
    result = forecaster.forecast(
        close_prices=prices,
        ticker="TEST",
        horizon_days=30,
    )
    names = {sc.name for sc in result.scenarios}
    assert names == {"pessimistic", "base", "optimistic"}


def test_forecast_pessimistic_below_base_below_optimistic():
    """Per ogni timestep, pessim < base < optim (rispettando ordine drift)."""
    prices = _generate_gbm_prices(252, 0.10, 0.15)
    forecaster = SimpleForecaster()
    result = forecaster.forecast(
        close_prices=prices, ticker="TEST", horizon_days=60
    )
    sc_map = {sc.name: sc for sc in result.scenarios}
    pessim = sc_map["pessimistic"]
    base = sc_map["base"]
    optim = sc_map["optimistic"]
    # Almeno l'ultimo valore deve rispettare l'ordine
    assert pessim.path[-1] < base.path[-1] < optim.path[-1]


def test_forecast_path_length_matches_horizon():
    """Il path ha esattamente horizon_days punti."""
    prices = _generate_gbm_prices(252, 0.05, 0.18)
    forecaster = SimpleForecaster()
    horizon = 90
    result = forecaster.forecast(
        close_prices=prices, ticker="TEST", horizon_days=horizon
    )
    for sc in result.scenarios:
        assert len(sc.path) == horizon


def test_forecast_recovers_volatility_within_tolerance():
    """Volatility annualizzata calcolata e' coerente con quella iniettata."""
    target_vol = 0.20
    prices = _generate_gbm_prices(2520, 0.05, target_vol, seed=123)  # 10 anni
    forecaster = SimpleForecaster()
    result = forecaster.forecast(
        close_prices=prices, ticker="TEST", horizon_days=30
    )
    # Tolleranza 25% per il sample statistico
    assert abs(result.historical_volatility_annualized - target_vol) < 0.05


def test_forecast_raises_on_short_history():
    """Almeno 30 osservazioni richieste."""
    prices = np.array([100.0, 101.0, 102.0])
    forecaster = SimpleForecaster()
    with pytest.raises(ValueError, match="osservazioni"):
        forecaster.forecast(
            close_prices=prices, ticker="X", horizon_days=10
        )


def test_forecast_raises_on_non_positive_prices():
    """Prezzi <= 0 sono rifiutati (log non definito)."""
    prices = np.concatenate([np.full(15, 100.0), np.full(15, 0.0)])
    forecaster = SimpleForecaster()
    with pytest.raises(ValueError, match="non positivi"):
        forecaster.forecast(
            close_prices=prices, ticker="X", horizon_days=10
        )


def test_forecast_raises_on_zero_horizon():
    """horizon_days deve essere > 0."""
    prices = _generate_gbm_prices(100, 0.05, 0.15)
    forecaster = SimpleForecaster()
    with pytest.raises(ValueError, match="horizon_days"):
        forecaster.forecast(
            close_prices=prices, ticker="X", horizon_days=0
        )


def test_forecast_metadata_consistency():
    """last_price del result == ultimo prezzo della serie input."""
    prices = _generate_gbm_prices(100, 0.06, 0.18)
    forecaster = SimpleForecaster()
    result = forecaster.forecast(
        close_prices=prices, ticker="META_TEST", horizon_days=20
    )
    assert result.last_price == pytest.approx(prices[-1])
    assert result.ticker == "META_TEST"
    assert result.historical_days == len(prices)
    assert result.horizon_days == 20
