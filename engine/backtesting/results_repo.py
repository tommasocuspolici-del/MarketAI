"""Backtest results repository — persists ``BacktestResult`` to DuckDB.

Schema lives in the initial DuckDB migration (table ``backtest_results``).
Each row stores one in-sample backtest summary; walk-forward runs persist
one row per split.

The equity curve itself is NOT stored — too heavy. Callers who need to
reproduce the full curve should re-run the engine with the same params
(strategy + params_json are persisted, so it's deterministic).
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC
from typing import TYPE_CHECKING

from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import DuckDBError
from shared.logger import get_logger
from shared.metrics import metrics

if TYPE_CHECKING:
    from engine.backtesting.engine import BacktestResult, WalkForwardResult

__version__ = "6.0.0"

__all__ = ["BacktestResultsRepository", "get_backtest_results_repo"]

log = get_logger(__name__)

_TABLE = "backtest_results"


class BacktestResultsRepository:
    """Persists backtest summaries to DuckDB."""

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()

    # ─── Writes ─────────────────────────────────────────────────────────
    def save_result(
        self,
        result: BacktestResult,
        timeframe: str = "1d",
        fees: float | None = None,
        slippage: float | None = None,
        strategy_params: dict[str, object] | None = None,
    ) -> str:
        """Persist a single backtest result. Returns the generated backtest_id."""
        backtest_id = str(uuid.uuid4())

        # Equity index può essere posizionale (numerico) — usiamo le colonne ts
        # del positions index per derivare start/end. Se non sono datetime,
        # generiamo timestamps fittizi (caso solo nei test sintetici).
        eq = result.equity_curve
        if hasattr(eq.index, "to_pydatetime") and len(eq.index) > 0:
            try:
                start_ts = eq.index[0].to_pydatetime()
                end_ts = eq.index[-1].to_pydatetime()
            except (AttributeError, ValueError):
                # Fallback per indici non temporali
                from datetime import datetime

                now = datetime.now(UTC)
                start_ts = now
                end_ts = now
        else:
            from datetime import datetime

            now = datetime.now(UTC)
            start_ts = now
            end_ts = now

        params_json = json.dumps(strategy_params or {})

        with metrics.timer("backtest_results_write_ms"):
            try:
                self._client.execute(
                    f"""
                    INSERT INTO {_TABLE} (
                        backtest_id, strategy_name, ticker, timeframe,
                        start_ts, end_ts, fees, slippage,
                        total_return, sharpe_ratio, sortino_ratio,
                        max_drawdown, win_rate, profit_factor,
                        n_trades, params_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        backtest_id,
                        result.strategy_name,
                        result.ticker,
                        timeframe,
                        start_ts,
                        end_ts,
                        fees if fees is not None else 0.001,
                        slippage if slippage is not None else 0.001,
                        result.performance.total_return,
                        result.performance.sharpe_ratio,
                        result.performance.sortino_ratio,
                        result.performance.max_drawdown,
                        result.performance.win_rate,
                        result.performance.profit_factor,
                        result.n_trades,
                        params_json,
                    ],
                )
            except DuckDBError:
                log.exception("backtest_results.write_failed", backtest_id=backtest_id)
                raise

        log.info(
            "backtest_results.saved",
            backtest_id=backtest_id,
            strategy=result.strategy_name,
            ticker=result.ticker,
            sharpe=round(result.performance.sharpe_ratio, 3),
        )
        return backtest_id

    def save_walk_forward(
        self,
        wf_result: WalkForwardResult,
        timeframe: str = "1d",
        fees: float | None = None,
        slippage: float | None = None,
        strategy_params: dict[str, object] | None = None,
    ) -> list[str]:
        """Persist all splits of a walk-forward run. Returns list of ids."""
        ids: list[str] = []
        for split_result in wf_result.split_results:
            bid = self.save_result(
                split_result,
                timeframe=timeframe,
                fees=fees,
                slippage=slippage,
                strategy_params=strategy_params,
            )
            ids.append(bid)
        log.info(
            "backtest_results.walk_forward_saved",
            strategy=wf_result.strategy_name,
            ticker=wf_result.ticker,
            n_splits=len(ids),
        )
        return ids

    # ─── Reads ──────────────────────────────────────────────────────────
    def read_by_id(self, backtest_id: str) -> dict[str, object] | None:
        """Fetch a single backtest summary by id, or None."""
        rows = self._client.query(
            f"""
            SELECT backtest_id, strategy_name, ticker, timeframe,
                   start_ts, end_ts, fees, slippage,
                   total_return, sharpe_ratio, sortino_ratio,
                   max_drawdown, win_rate, profit_factor,
                   n_trades, params_json, run_at
            FROM {_TABLE} WHERE backtest_id = ?
            """,
            [backtest_id],
        )
        if not rows:
            return None
        return self._row_to_dict(rows[0])

    def read_by_ticker(
        self,
        ticker: str,
        strategy_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """Fetch most-recent backtest results for a ticker."""
        if strategy_name is not None:
            sql = (
                f"SELECT * FROM {_TABLE} WHERE ticker = ? AND strategy_name = ? "
                f"ORDER BY run_at DESC LIMIT ?"
            )
            params: list[object] = [ticker, strategy_name, limit]
        else:
            sql = f"SELECT * FROM {_TABLE} WHERE ticker = ? ORDER BY run_at DESC LIMIT ?"
            params = [ticker, limit]
        rows = self._client.query(sql, params)
        return [self._row_to_dict(r) for r in rows]

    def count(self) -> int:
        """Total number of backtest results persisted."""
        rows = self._client.query(f"SELECT COUNT(*) FROM {_TABLE}")
        return int(rows[0][0]) if rows else 0

    @staticmethod
    def _row_to_dict(row: tuple) -> dict[str, object]:  # type: ignore[type-arg]
        cols = [
            "backtest_id", "strategy_name", "ticker", "timeframe",
            "start_ts", "end_ts", "fees", "slippage",
            "total_return", "sharpe_ratio", "sortino_ratio",
            "max_drawdown", "win_rate", "profit_factor",
            "n_trades", "params_json", "run_at",
        ]
        return dict(zip(cols, row, strict=False))


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: BacktestResultsRepository | None = None


def get_backtest_results_repo() -> BacktestResultsRepository:
    """Return the process-wide BacktestResultsRepository singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = BacktestResultsRepository()
    return _INSTANCE


def reset_backtest_results_repo() -> None:
    """Reset singleton (tests only)."""
    global _INSTANCE
    _INSTANCE = None
