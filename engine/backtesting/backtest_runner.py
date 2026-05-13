"""BacktestRunner — orchestratore backtest completo con persistenza DuckDB.

Coordina il flusso:
  dati OHLCV → DataQualityReport → BacktestEngine.run() → persist → return

Supporta:
  · Single run: risultato singolo in-sample
  · Walk-forward: validazione OOS con N split
  · Batch run: stessa strategia su N ticker

Regola 23: delega tutta la logica di backtest a BacktestEngine (nessun
loop Python su serie temporali in questo modulo — solo orchestrazione).

ANTI-REGRESSIONE: BacktestRunner NON modifica le posizioni della Strategy.
La Strategy emette segnali grezzi, BacktestEngine gestisce shift+fees+slippage.
"""
from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from engine.backtesting.engine import BacktestEngine, BacktestResult, WalkForwardResult
from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import BacktestError, DatabaseError
from shared.logger import get_logger

if TYPE_CHECKING:
    from engine.backtesting.strategy import Strategy

__version__ = "9.0.0"
__all__ = [
    "BacktestConfig",
    "BacktestRunner",
    "get_backtest_runner",
    "reset_backtest_runner",
]

log = get_logger(__name__)


@dataclass
class BacktestConfig:
    """Configurazione per un singolo run BacktestRunner.

    Raggruppa tutti i parametri necessari per garantire riproducibilità
    del backtest (il run_id e la configurazione vengono persistiti insieme).
    """
    ticker:        str
    exchange:      str         = "NASDAQ"
    initial_cash:  float       = 10_000.0
    fees:          float       = 0.001   # 0.1% minimo (Regola 23)
    slippage:      float       = 0.001   # 0.1% minimo (Regola 23)
    n_splits:      int         = 5       # per walk-forward
    train_pct:     float       = 0.60    # per walk-forward
    scenario:      str | None  = None    # per stress test
    extra: dict    = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "ticker": self.ticker,
            "exchange": self.exchange,
            "initial_cash": self.initial_cash,
            "fees": self.fees,
            "slippage": self.slippage,
            "n_splits": self.n_splits,
            "train_pct": self.train_pct,
            "scenario": self.scenario,
            **self.extra,
        })


class BacktestRunner:
    """Orchestratore backtest: carica dati → esegue → persiste risultati.

    Separa il fetching dei dati dall'engine di calcolo (Regola 2 SRP).
    Tutti i risultati vengono persistiti in backtest_results (migration 016).
    """

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()

    # ─── Public API ──────────────────────────────────────────────────────────

    def run(
        self,
        strategy: Strategy,
        config: BacktestConfig,
        ohlcv: pd.DataFrame | None = None,
    ) -> BacktestResult:
        """Esegue un singolo backtest in-sample e persiste il risultato.

        Args:
            strategy: Strategy da testare (DSLStrategy, MovingAverageCrossover, ecc.)
            config:   Configurazione del backtest.
            ohlcv:    DataFrame OHLCV già caricato. Se None, viene caricato
                      da DuckDB tramite PricesRepository.

        Returns:
            BacktestResult con equity curve, performance e metriche.
        """
        df = ohlcv if ohlcv is not None else self._load_ohlcv(config)

        engine = BacktestEngine(
            initial_cash=config.initial_cash,
            fees=config.fees,
            slippage=config.slippage,
        )
        result = engine.run(df, strategy, ticker=config.ticker)

        self._persist(
            result=result,
            run_type="single",
            config=config,
        )
        return result

    def run_walk_forward(
        self,
        strategy: Strategy,
        config: BacktestConfig,
        ohlcv: pd.DataFrame | None = None,
    ) -> WalkForwardResult:
        """Esegue walk-forward validation e persiste il risultato aggregato."""
        df = ohlcv if ohlcv is not None else self._load_ohlcv(config)

        engine = BacktestEngine(
            initial_cash=config.initial_cash,
            fees=config.fees,
            slippage=config.slippage,
        )
        result = engine.walk_forward(
            df,
            strategy,
            ticker=config.ticker,
            n_splits=config.n_splits,
            train_pct=config.train_pct,
        )

        # Persiste il risultato aggregato (non i singoli split)
        self._persist_walk_forward(result=result, config=config)
        return result

    def run_batch(
        self,
        strategy: Strategy,
        tickers: list[str],
        base_config: BacktestConfig,
        ohlcv_map: dict[str, pd.DataFrame] | None = None,
    ) -> dict[str, BacktestResult]:
        """Esegue lo stesso backtest su N ticker e ritorna un dict di risultati.

        Args:
            strategy:   Strategy comune a tutti i ticker.
            tickers:    Lista di ticker.
            base_config: Configurazione base (ticker viene sovrapposto).
            ohlcv_map:  Se fornito, usa questi DataFrame invece di caricare dal DB.
        """
        results: dict[str, BacktestResult] = {}
        for ticker in tickers:
            cfg = BacktestConfig(
                ticker=ticker,
                exchange=base_config.exchange,
                initial_cash=base_config.initial_cash,
                fees=base_config.fees,
                slippage=base_config.slippage,
            )
            try:
                ohlcv = ohlcv_map.get(ticker) if ohlcv_map else None
                results[ticker] = self.run(strategy, cfg, ohlcv=ohlcv)
                log.info(
                    "backtest_runner.batch_ticker_done",
                    ticker=ticker,
                    sharpe=round(results[ticker].performance.sharpe_ratio, 3),
                )
            except Exception as exc:
                log.warning(
                    "backtest_runner.batch_ticker_skip",
                    ticker=ticker,
                    error=str(exc)[:100],
                )
                continue
        return results

    def read_results(
        self,
        strategy_name: str | None = None,
        ticker: str | None = None,
        run_type: str | None = None,
        limit: int = 50,
    ) -> pd.DataFrame:
        """Legge i risultati storici da backtest_results DuckDB."""
        conditions = ["TRUE"]
        params: list[object] = []
        if strategy_name:
            conditions.append("strategy_name = ?")
            params.append(strategy_name)
        if ticker:
            conditions.append("ticker = ?")
            params.append(ticker)
        if run_type:
            conditions.append("run_type = ?")
            params.append(run_type)
        params.append(limit)

        where = " AND ".join(conditions)
        try:
            with self._client.transaction() as conn:
                return conn.execute(
                    f"""
                    SELECT run_id, strategy_name, ticker, run_type, scenario,
                           sharpe_ratio, max_drawdown, total_return, win_rate,
                           n_trades, fees_total, run_at
                    FROM backtest_results
                    WHERE {where}
                    ORDER BY run_at DESC
                    LIMIT ?
                    """,
                    params,
                ).df()
        except Exception as exc:
            log.warning("backtest_runner.read_results_error", error=str(exc)[:100])
            return pd.DataFrame()

    # ─── Internals ───────────────────────────────────────────────────────────

    def _load_ohlcv(self, config: BacktestConfig) -> pd.DataFrame:
        """Carica OHLCV da PricesRepository DuckDB."""
        try:
            from shared.db.prices_repo import get_prices_repository
            from shared.types import TimeFrame
            repo = get_prices_repository()
            df = repo.read_ohlcv(
                ticker=config.ticker,
                exchange=config.exchange,
                timeframe=TimeFrame.D1,
                limit=1000,
            )
            if df is None or df.empty:
                raise BacktestError(
                    f"No OHLCV data for {config.ticker}. "
                    "Avvia lo scheduler per scaricare i prezzi."
                )
            return df
        except BacktestError:
            raise
        except Exception as exc:
            raise BacktestError(
                f"Failed to load OHLCV for {config.ticker}: {exc}"
            ) from exc

    def _persist(
        self,
        result: BacktestResult,
        run_type: str,
        config: BacktestConfig,
    ) -> None:
        """Persiste un BacktestResult in backtest_results DuckDB."""
        perf = result.performance
        try:
            with self._client.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO backtest_results
                    (run_id, strategy_name, ticker, run_type, scenario,
                     sharpe_ratio, max_drawdown, total_return, win_rate,
                     calmar_ratio, n_trades, fees_total, initial_cash,
                     config_json, run_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        str(uuid.uuid4()),
                        result.strategy_name,
                        result.ticker,
                        run_type,
                        config.scenario,
                        float(perf.sharpe_ratio) if not np.isnan(perf.sharpe_ratio) else None,
                        float(perf.max_drawdown),
                        float(perf.total_return),
                        float(perf.win_rate) if hasattr(perf, "win_rate") else None,
                        float(perf.calmar_ratio) if hasattr(perf, "calmar_ratio") else None,
                        result.n_trades,
                        float(result.fees_total),
                        result.initial_cash,
                        config.to_json(),
                        datetime.now(UTC).isoformat(),
                    ],
                )
        except Exception as exc:
            log.warning("backtest_runner.persist_failed", error=str(exc)[:100])

    def _persist_walk_forward(
        self,
        result: WalkForwardResult,
        config: BacktestConfig,
    ) -> None:
        """Persiste il risultato aggregato walk-forward."""
        perf = result.aggregate_performance
        try:
            with self._client.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO backtest_results
                    (run_id, strategy_name, ticker, run_type, scenario,
                     sharpe_ratio, max_drawdown, total_return, n_trades,
                     initial_cash, config_json, run_at)
                    VALUES (?, ?, ?, 'walkforward', NULL, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        str(uuid.uuid4()),
                        result.strategy_name,
                        result.ticker,
                        float(perf.sharpe_ratio) if not np.isnan(perf.sharpe_ratio) else None,
                        float(perf.max_drawdown),
                        float(perf.total_return),
                        result.n_splits,
                        config.initial_cash,
                        config.to_json(),
                        datetime.now(UTC).isoformat(),
                    ],
                )
        except Exception as exc:
            log.warning("backtest_runner.persist_wf_failed", error=str(exc)[:100])


# ─── Singleton ────────────────────────────────────────────────────────────────

_runner_lock   = threading.Lock()
_default_runner: BacktestRunner | None = None


def get_backtest_runner() -> BacktestRunner:
    """Singleton thread-safe per BacktestRunner."""
    global _default_runner  # noqa: PLW0603
    with _runner_lock:
        if _default_runner is None:
            _default_runner = BacktestRunner()
        return _default_runner


def reset_backtest_runner() -> None:
    """Reset singleton — uso esclusivo nei test."""
    global _default_runner  # noqa: PLW0603
    with _runner_lock:
        _default_runner = None
