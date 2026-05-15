"""Generatore del segnale valutation composito [-1, +1] per Composite Signal v2.

Pipeline:
  1. Legge PEMetrics da pe_metrics (o calcola via PECalculator)
  2. Calcola contesto storico via PEContextBuilder
  3. Produce ValuationSignalResult con score e label
  4. Persiste in valuation_signal

Regola 27: persist via DuckDB client.
"""
from __future__ import annotations

import logging
from datetime import date, UTC, datetime
from typing import TYPE_CHECKING

import numpy as np

from engine.analytics.valuation.pe_calculator import PECalculator
from engine.analytics.valuation.pe_context_builder import PEContextBuilder
from engine.analytics.valuation.schemas import PEMetrics, ValuationSignalResult

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
log = logging.getLogger(__name__)

_TABLE = "valuation_signal"


class ValuationSignalGenerator:
    """Genera il segnale di valuation per il Composite Signal v2.

    Usage::

        gen = ValuationSignalGenerator(client=get_duckdb_client())
        result = gen.compute("^GSPC")
        print(result.valuation_score, result.label)
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client
        self._calc   = PECalculator(client)
        self._ctx    = PEContextBuilder(client)

    def compute(self, ticker: str = "^GSPC", as_of: date | None = None) -> ValuationSignalResult:
        """Calcola il segnale di valutation per il ticker.

        Args:
            ticker: Ticker (default '^GSPC' = S&P 500).
            as_of:  Data di riferimento (default: oggi).

        Returns:
            ValuationSignalResult con score [-1,+1], label e breakdown.
        """
        as_of = as_of or date.today()
        metrics = self._calc.compute(ticker, as_of)
        ctx     = self._ctx.build(metrics)

        z_t  = ctx.get("trailing_zscore") or 0.0
        z_f  = ctx.get("forward_zscore")  or 0.0
        z_c  = ctx.get("cape_zscore")     or 0.0
        score = float(ctx.get("composite_score", 0.0))
        label = ctx.get("label", "fair_value")

        # Segnali per componente (invertiti: z-score alto = costoso = segnale negativo)
        t_signal = float(np.clip(-z_t / 2.0, -1, 1)) if ctx.get("trailing_zscore") is not None else 0.0
        f_signal = float(np.clip(-z_f / 2.0, -1, 1)) if ctx.get("forward_zscore")  is not None else 0.0
        c_signal = float(np.clip(-z_c / 2.0, -1, 1)) if ctx.get("cape_zscore")     is not None else 0.0

        # ERP signal: ERP > 3% → positivo; ERP < 0% → molto negativo
        erp_signal = 0.0
        if metrics.erp_implied is not None:
            erp_signal = float(np.clip((metrics.erp_implied - 0.02) / 0.02, -1, 1))

        result = ValuationSignalResult(
            signal_date=as_of,
            ticker=ticker,
            valuation_score=score,
            trailing_pe_signal=t_signal,
            forward_pe_signal=f_signal,
            cape_signal=c_signal,
            erp_signal=erp_signal,
            label=label,
            pe_metrics=metrics,
        )

        self._persist(result, ctx)
        return result

    def get_latest_signal(self, ticker: str = "^GSPC") -> float | None:
        """Legge il segnale più recente da valuation_signal.

        Usato dal CompositeSignalAggregator.

        Returns:
            Score [-1,+1] o None se non disponibile.
        """
        try:
            rows = self._client.query(
                f"SELECT valuation_score FROM {_TABLE} "
                f"WHERE ticker=? ORDER BY signal_date DESC LIMIT 1",
                [ticker],
            )
            return float(rows[0][0]) if rows and rows[0][0] is not None else None
        except Exception as exc:
            log.debug("valuation_signal.read_failed", error=str(exc)[:80])
            return None

    def _persist(self, result: ValuationSignalResult, ctx: dict) -> None:
        """Upsert in valuation_signal."""
        try:
            self._client.execute(
                f"""
                INSERT INTO {_TABLE}
                    (signal_date, ticker, valuation_score, trailing_pe_signal,
                     forward_pe_signal, cape_signal, erp_signal, label)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT (signal_date, ticker) DO UPDATE SET
                    valuation_score    = excluded.valuation_score,
                    trailing_pe_signal = excluded.trailing_pe_signal,
                    forward_pe_signal  = excluded.forward_pe_signal,
                    cape_signal        = excluded.cape_signal,
                    erp_signal         = excluded.erp_signal,
                    label              = excluded.label,
                    computed_at        = NOW()
                """,
                [
                    result.signal_date, result.ticker, result.valuation_score,
                    result.trailing_pe_signal, result.forward_pe_signal,
                    result.cape_signal, result.erp_signal, result.label,
                ],
            )
            # Persist PE metrics con contesto
            if result.pe_metrics:
                self._calc.persist(
                    result.pe_metrics,
                    zscore_trailing=ctx.get("trailing_zscore"),
                    zscore_forward=ctx.get("forward_zscore"),
                    zscore_cape=ctx.get("cape_zscore"),
                    pct_trailing=ctx.get("trailing_pct"),
                    pct_forward=ctx.get("forward_pct"),
                    pct_cape=ctx.get("cape_pct"),
                )
        except Exception as exc:
            log.warning("valuation_signal.persist_failed", ticker=result.ticker,
                        error=str(exc)[:120])
