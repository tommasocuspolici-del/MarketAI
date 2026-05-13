"""Strategy Builder — converte sorgenti dati in Strategy per BacktestEngine.

Aggiunge due nuove strategie al framework esistente (engine/backtesting/):

  · DSLStrategy:             Qualsiasi espressione DSL (IndicatorRegistry)
                             → posizioni [-1, 1]. Reusa DSLEvaluator.
  · CompositeSignalStrategy: Legge composite_score da DuckDB (CompositeSignalV3)
                             → posizioni allineate al OHLCV input.

Design:
  · Entrambe estendono Strategy (pattern già definito in strategy.py).
  · I segnali grezzi sono normalizzati a [-1, 1] con Z-score rolling
    (finestra configurabile) — zero loop Python, solo numpy/pandas.
  · Shift(1) anti-lookahead è gestito dal BacktestEngine (Regola 23) —
    le Strategy NON devono shiftare le proprie posizioni.

ANTI-REGRESSIONE (Regola 23):
  · Le Strategy emettono posizioni NON-shiftate. Il BacktestEngine chiama
    shift(1) prima dell'esecuzione. NON aggiungere shift() in questa classe.
  · Z-score normalization: finestra rolling per evitare look-ahead bias
    sui dati storici di normalizzazione.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from engine.backtesting.strategy import Strategy, StrategySignal
from shared.exceptions import BacktestError
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "9.0.0"
__all__ = [
    "DSLStrategy",
    "CompositeSignalStrategy",
    "build_strategy_from_dsl",
]

log = get_logger(__name__)

# Finestra rolling per Z-score normalization (Regola 7: nessun magic number)
_DEFAULT_ZSCORE_WINDOW: int = 20
# Clip dello Z-score prima del mapping → [-1, 1]
_ZSCORE_CLIP: float = 3.0


# ─── Utility vettorizzate ─────────────────────────────────────────────────────

def _normalize_to_positions(series: pd.Series, window: int) -> pd.Series:
    """Normalizza una serie float in posizioni [-1, 1] via Z-score rolling.

    Completamente vettorizzato (pandas rolling + numpy clip), zero loop Python.
    La normalizzazione rolling evita look-ahead bias sui parametri statistici.

    Args:
        series: Serie float da normalizzare (es. output DSL).
        window: Finestra rolling per mean e std.

    Returns:
        pd.Series in [-1.0, 1.0] con indice invariato.
    """
    roll_mean = series.rolling(window, min_periods=1).mean()
    roll_std  = series.rolling(window, min_periods=1).std().fillna(np.float64(1e-9))
    # Protegge dalla divisione per zero
    roll_std  = roll_std.replace(0.0, np.float64(1e-9))
    z = (series - roll_mean) / roll_std
    return (z.clip(-_ZSCORE_CLIP, _ZSCORE_CLIP) / _ZSCORE_CLIP).astype(np.float64)


def _bool_to_positions(series: pd.Series, allow_short: bool) -> pd.Series:
    """Converte una serie booleana/0-1 in posizioni.

    True  → +1.0 (long)
    False →  0.0 (flat) o -1.0 (short, se allow_short=True)
    """
    long_mask = (series > 0.5).astype(np.float64)
    if allow_short:
        short_mask = (series <= 0.5).astype(np.float64)
        return (long_mask - short_mask).astype(np.float64)
    return long_mask


# ─── DSL Strategy ─────────────────────────────────────────────────────────────

class DSLStrategy(Strategy):
    """Converte un'espressione DSL in segnali di posizione per il backtesting.

    Mapping DSL → posizioni:
      · Serie booleana (tutti 0/1) → +1 when True, 0 (o -1) when False
      · Serie float generale → Z-score rolling normalizzato a [-1, 1]

    Parametri raccomandati:
      · expression: "RSI(close, 14) > 70"     → segnale overbought (boolean)
      · expression: "EMA(close, 20) - close"  → distanza da EMA (float)
      · expression: "MACD(close, 12, 26, 9)"  → MACD histogram (float)
    """

    def __init__(
        self,
        expression: str,
        *,
        allow_short: bool = False,
        zscore_window: int = _DEFAULT_ZSCORE_WINDOW,
    ) -> None:
        if not expression.strip():
            raise BacktestError("DSLStrategy: expression cannot be empty")
        self._expression = expression.strip()
        self._allow_short = allow_short
        self._zscore_window = zscore_window

    @property
    def name(self) -> str:
        # Tronca l'espressione per usarla come nome identificativo
        short_expr = self._expression[:40].replace(" ", "_").replace("(", "").replace(")", "")
        return f"DSL_{short_expr}"

    def generate_signals(self, ohlcv: pd.DataFrame) -> StrategySignal:
        """Valuta l'espressione DSL sull'OHLCV e produce posizioni.

        ANTI-REGRESSIONE: NON shiftare le posizioni qui.
        Il BacktestEngine gestisce lo shift(1) anti-lookahead (Regola 23).
        """
        try:
            from engine.technical.indicator_dsl import DSLEvaluator
        except ImportError as exc:
            raise BacktestError(
                f"DSLEvaluator non disponibile: {exc}. "
                "Verifica che engine/technical/indicator_dsl.py esista."
            ) from exc

        close = self._ensure_close(ohlcv)
        if len(close) < 2:
            return self._zero_signal(ohlcv.index, self.name, self._params())

        try:
            ev = DSLEvaluator()
            raw: pd.Series = ev.evaluate(self._expression, ohlcv)
        except Exception as exc:
            raise BacktestError(
                f"DSL evaluation failed for '{self._expression}': {exc}"
            ) from exc

        raw = raw.fillna(0.0).astype(np.float64)

        # Determina se la serie è booleana (0/1) o float generale
        unique_vals = raw.dropna().unique()
        is_boolean = len(unique_vals) <= 2 and set(unique_vals).issubset({0.0, 1.0, True, False})

        if is_boolean:
            positions = _bool_to_positions(raw, self._allow_short)
        else:
            positions = _normalize_to_positions(raw, self._zscore_window)
            if not self._allow_short:
                # Long-only: clip a [0, 1]
                positions = positions.clip(0.0, 1.0)

        return StrategySignal(
            positions=positions,
            name=self.name,
            params=self._params(),
        )

    def _params(self) -> dict[str, Any]:
        return {
            "expression": self._expression,
            "allow_short": int(self._allow_short),
            "zscore_window": self._zscore_window,
        }


# ─── Composite Signal Strategy ────────────────────────────────────────────────

class CompositeSignalStrategy(Strategy):
    """Usa il composite_score di CompositeSignalV3 come segnale di posizione.

    Legge i composite_score storici dalla tabella engine_composite_signal
    (migration 007), allinea ai timestamp dell'OHLCV input (forward-fill),
    e usa i valori come posizioni dirette (già in [-1, 1]).

    Useful for backtesting "what if we followed the composite signal".
    """

    def __init__(
        self,
        client: DuckDBClient,
        *,
        long_threshold: float = 0.10,   # score > this → long
        short_threshold: float = -0.10, # score < this → short (if allow_short)
        allow_short: bool = True,
    ) -> None:
        if long_threshold <= short_threshold:
            raise BacktestError(
                f"long_threshold ({long_threshold}) must be > short_threshold ({short_threshold})"
            )
        self._client = client
        self._long_th  = long_threshold
        self._short_th = short_threshold
        self._allow_short = allow_short

    @property
    def name(self) -> str:
        return f"CompositeV3_lt{self._long_th}_st{self._short_th}"

    def generate_signals(self, ohlcv: pd.DataFrame) -> StrategySignal:
        """Allinea composite_score ai timestamp OHLCV e genera posizioni.

        ANTI-REGRESSIONE: usa forward-fill per allineamento (NON backward-fill).
        Il backward-fill introdurrebbe lookahead bias.
        """
        close = self._ensure_close(ohlcv)
        if len(close) < 2:
            return self._zero_signal(ohlcv.index, self.name, self._params())

        try:
            scores = self._load_scores(ohlcv)
        except Exception as exc:
            log.warning(
                "composite_strategy.load_failed",
                error=str(exc)[:100],
                fallback="zero signal",
            )
            return self._zero_signal(ohlcv.index, self.name, self._params())

        # Converte score [-1, 1] in posizioni con soglie
        positions = pd.Series(np.float64(0.0), index=ohlcv.index)
        positions[scores > self._long_th]  = np.float64(1.0)
        if self._allow_short:
            positions[scores < self._short_th] = np.float64(-1.0)

        return StrategySignal(
            positions=positions.astype(np.float64),
            name=self.name,
            params=self._params(),
        )

    def _load_scores(self, ohlcv: pd.DataFrame) -> pd.Series:
        """Carica composite_score allineati alle date OHLCV (forward-fill)."""
        # Legge tutti i score nel range temporale dell'OHLCV
        ts_col = "ts" if "ts" in ohlcv.columns else ohlcv.columns[0]
        start  = pd.Timestamp(ohlcv[ts_col].min()).isoformat()
        end    = pd.Timestamp(ohlcv[ts_col].max()).isoformat()

        with self._client.transaction() as conn:
            df_scores = conn.execute(
                """
                SELECT computed_at, composite_score
                FROM engine_composite_signal
                WHERE computed_at >= ?::TIMESTAMPTZ
                  AND computed_at <= ?::TIMESTAMPTZ
                ORDER BY computed_at ASC
                """,
                [start, end],
            ).df()

        if df_scores.empty:
            return pd.Series(np.float64(0.0), index=ohlcv.index)

        # Allinea tramite reindex + forward-fill (no lookahead)
        score_series = pd.Series(
            df_scores["composite_score"].to_numpy(np.float64),
            index=pd.to_datetime(df_scores["computed_at"], utc=True),
        )
        ohlcv_ts = pd.DatetimeIndex(
            pd.to_datetime(ohlcv[ts_col], utc=True)
        )
        aligned = score_series.reindex(
            score_series.index.union(ohlcv_ts)
        ).ffill().reindex(ohlcv_ts).fillna(0.0)

        return aligned.astype(np.float64)

    def _params(self) -> dict[str, Any]:
        return {
            "long_threshold": self._long_th,
            "short_threshold": self._short_th,
            "allow_short": int(self._allow_short),
        }


# ─── Factory function ─────────────────────────────────────────────────────────

def build_strategy_from_dsl(
    expression: str,
    *,
    allow_short: bool = False,
    zscore_window: int = _DEFAULT_ZSCORE_WINDOW,
) -> DSLStrategy:
    """Factory: crea una DSLStrategy validata dall'espressione fornita.

    Valida l'espressione su un DataFrame dummy prima di restituire la strategia.
    Questo evita che un'espressione malformata fallisca silenziosamente al run.

    Args:
        expression: Espressione DSL (es. "EMA(close, 20) > close").
        allow_short: Se True, genera anche posizioni short (-1).
        zscore_window: Finestra rolling per normalizzazione Z-score.

    Returns:
        DSLStrategy pronta per BacktestEngine.run().

    Raises:
        BacktestError: Se l'espressione DSL non è valida.
    """
    from engine.technical.indicator_dsl import validate_expression
    import numpy as np

    # Validazione su dati dummy (non ha bisogno di dati reali)
    dummy = pd.DataFrame({
        "ts":    pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC"),
        "open":  np.ones(30, dtype=np.float64) * 100.0,
        "high":  np.ones(30, dtype=np.float64) * 101.0,
        "low":   np.ones(30, dtype=np.float64) * 99.0,
        "close": np.linspace(95, 110, 30, dtype=np.float64),
        "volume": np.ones(30, dtype=np.float64) * 1_000_000,
    })
    err = validate_expression(expression, dummy)
    if err is not None:
        raise BacktestError(f"DSL expression invalid: {err}")

    return DSLStrategy(
        expression,
        allow_short=allow_short,
        zscore_window=zscore_window,
    )
