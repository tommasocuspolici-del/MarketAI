"""Test fixtures: builder di oggetti mock riutilizzabili (v7.2 fix B2).

PRIMA di v7.2 alcune funzioni di test (``build_mock_ohlcv``,
``_build_mock_snapshots``, ``build_mock_backtest``) erano definite dentro
moduli di presentazione (E2_Equities, P4_Net_Worth, E12_Backtesting).
Quando le pagine sono state riscritte con dati reali, le funzioni sono
state correttamente rimosse dai moduli di produzione, ma 3 test in
``tests/presentation/test_pages.py`` continuavano a importarle dalle
pagine -> ImportError.

Le funzioni vivono ora in ``tests/fixtures/`` (questo file): test e codice
di produzione sono finalmente isolati.

Anti-pattern correlato (Regola 32):
    NON importare mai funzioni "build_mock_*" da ``presentation/`` o ``engine/``.
    Le fixtures sono SOLO in ``tests/fixtures/``.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd

__all__ = [
    "build_mock_backtest_result",
    "build_mock_ohlcv",
    "build_mock_snapshots",
]


def build_mock_ohlcv(n_bars: int = 50) -> pd.DataFrame:
    """DataFrame OHLCV sintetico per test chart candlestick.

    Schema: index DatetimeIndex tz-aware UTC + colonne open/high/low/close/volume.
    Seed fisso (42) -> output deterministico, riproducibile in CI.
    """
    rng = np.random.default_rng(42)
    end = datetime.now(tz=timezone.utc)
    dates = pd.date_range(end=end, periods=n_bars, freq="1D", tz="UTC")

    close = 100.0 + np.cumsum(rng.standard_normal(n_bars) * 0.5)
    return pd.DataFrame(
        {
            "open": close * (1 - np.abs(rng.standard_normal(n_bars) * 0.003)),
            "high": close * (1 + np.abs(rng.standard_normal(n_bars) * 0.005)),
            "low": close * (1 - np.abs(rng.standard_normal(n_bars) * 0.005)),
            "close": close,
            "volume": rng.integers(1_000_000, 10_000_000, n_bars).astype(np.float64),
        },
        index=dates,
    )


def build_mock_snapshots(n: int = 6) -> list[dict[str, Any]]:
    """Lista di snapshot net worth sintetici per test chart P4.

    Ogni snapshot contiene: snapshot_date (ISO), total_assets, total_liabilities,
    net_worth. Crescita lineare progressiva — sufficiente per testare il chart.
    """
    base = datetime(2025, 1, 1)
    return [
        {
            "snapshot_date": (base + timedelta(days=30 * i)).isoformat(),
            "total_assets": 50_000.0 + i * 2_000,
            "total_liabilities": max(0.0, 10_000.0 - i * 200),
            "net_worth": 40_000.0 + i * 2_200,
        }
        for i in range(n)
    ]


def build_mock_backtest_result() -> Any:
    """BacktestResult sintetico per testare i componenti backtest_report.

    Costruisce un'istanza reale di ``BacktestResult`` (non un dict) con
    equity curve generata GBM e PerformanceReport calcolato. Cosi' possiamo
    testare ``build_equity_curve_figure``, ``build_drawdown_figure``,
    ``build_metrics_table`` con un oggetto del tipo atteso.
    """
    # Import locali per evitare import-time cycles nei test che non usano backtest
    from engine.backtesting.engine import BacktestResult
    from engine.backtesting.performance import PerformanceReport

    rng = np.random.default_rng(42)
    n_bars = 252  # 1 anno trading
    daily_returns = rng.normal(loc=0.0006, scale=0.012, size=n_bars)
    equity_values = 10_000.0 * np.cumprod(1.0 + daily_returns)
    dates = pd.date_range("2025-01-01", periods=n_bars, freq="B", tz="UTC")

    equity_curve = pd.Series(equity_values, index=dates, name="equity")
    positions = pd.Series(np.ones(n_bars, dtype=np.int8), index=dates, name="position")
    returns = pd.Series(daily_returns, index=dates, name="returns")

    performance = PerformanceReport(
        total_return=0.12,
        annualized_return=0.094,
        annualized_vol=0.19,
        sharpe_ratio=0.49,
        sortino_ratio=0.71,
        max_drawdown=-0.142,
        calmar_ratio=0.66,
        win_rate=0.54,
        profit_factor=1.32,
        n_periods=n_bars,
    )

    return BacktestResult(
        strategy_name="MockStrategy",
        ticker="MOCK",
        equity_curve=equity_curve,
        positions=positions,
        returns=returns,
        performance=performance,
        fees_total=42.50,
        n_trades=14,
        initial_cash=10_000.0,
    )
