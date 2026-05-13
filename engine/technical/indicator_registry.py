"""IndicatorRegistry — persistenza e valutazione degli indicatori DSL utente.

Gestisce la tabella ``user_indicators`` (migration 014).
Separato da DSLEvaluator per rispettare la Regola 2 (SRP).

Flusso tipico:
  1. L'utente inserisce espressione nella UI → validate_expression()
  2. Se valida → registry.save(name, expression, ...)
  3. Al render del chart → registry.evaluate_all(df, ticker) → lista Series
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from engine.technical.indicator_dsl import DSLEvaluator, validate_expression
from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.exceptions import DatabaseError, DSLParseError
from shared.logger import get_logger

if TYPE_CHECKING:
    pass

__version__ = "9.0.0"
__all__ = [
    "IndicatorRegistry",
    "UserIndicator",
    "get_indicator_registry",
    "reset_indicator_registry",
]

log = get_logger(__name__)


@dataclass(frozen=True)
class UserIndicator:
    """Indicatore DSL salvato dall'utente."""

    indicator_id: str
    name: str
    expression: str
    description: str
    ticker_filter: str | None   # None = tutti i ticker
    chart_type: str             # 'line' | 'bar' | 'area'
    overlay: bool               # True = sovrapposto al candlestick
    is_active: bool
    created_at: datetime


class IndicatorRegistry:
    """CRUD per ``user_indicators`` DuckDB + valutazione su OHLCV.

    Metodi principali:
      · save(name, expression, ...) → salva se valido
      · list_active(ticker)         → indicatori applicabili al ticker
      · delete(indicator_id)        → disattiva (soft delete)
      · evaluate_all(df, ticker)    → valuta tutti e ritorna {name: Series}
    """

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()
        self._evaluator = DSLEvaluator()

    # ─── Write ───────────────────────────────────────────────────────────────

    def save(
        self,
        name: str,
        expression: str,
        *,
        description: str = "",
        ticker_filter: str | None = None,
        chart_type: str = "line",
        overlay: bool = False,
        sample_df: pd.DataFrame | None = None,
    ) -> UserIndicator:
        """Valida e persiste un nuovo indicatore DSL.

        Args:
            name: Nome leggibile (es. "RSI 14").
            expression: Stringa DSL (es. "RSI(close, 14)").
            description: Note opzionali.
            ticker_filter: Se non None, l'indicatore è applicato solo a quel ticker.
            chart_type: 'line' | 'bar' | 'area'.
            overlay: Se True, sovrapposto al candlestick in UI.
            sample_df: DataFrame OHLCV per la validazione. Se None, usa dati dummy.

        Returns:
            UserIndicator appena creato.

        Raises:
            DSLParseError: Se l'espressione non è valida.
            DatabaseError: Se la persistenza fallisce.
        """
        # Validazione DSL su DataFrame campione
        test_df = sample_df if sample_df is not None else _make_dummy_ohlcv()
        err = validate_expression(expression, test_df)
        if err is not None:
            raise DSLParseError(err)

        # Sanifica name e chart_type
        name       = name.strip()[:100]
        chart_type = chart_type if chart_type in ("line", "bar", "area") else "line"
        now        = datetime.now(UTC)
        iid        = str(uuid.uuid4())

        try:
            with self._client.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO user_indicators
                    (indicator_id, name, expression, description,
                     ticker_filter, chart_type, overlay,
                     is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, TRUE, ?, ?)
                    """,
                    [
                        iid, name, expression.strip(), description[:500],
                        ticker_filter, chart_type, overlay,
                        now.isoformat(), now.isoformat(),
                    ],
                )
            log.info("indicator_registry.saved", name=name, indicator_id=iid)
            return UserIndicator(
                indicator_id=iid,
                name=name,
                expression=expression.strip(),
                description=description,
                ticker_filter=ticker_filter,
                chart_type=chart_type,
                overlay=overlay,
                is_active=True,
                created_at=now,
            )
        except Exception as exc:
            raise DatabaseError(f"Salvataggio indicatore fallito: {exc}") from exc

    def delete(self, indicator_id: str) -> bool:
        """Soft-delete: marca l'indicatore come inattivo.

        Returns:
            True se l'indicatore esisteva e è stato disattivato.
        """
        try:
            with self._client.transaction() as conn:
                conn.execute(
                    """
                    UPDATE user_indicators
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE indicator_id = ?
                    """,
                    [indicator_id],
                )
            log.info("indicator_registry.deleted", indicator_id=indicator_id)
            return True
        except Exception as exc:
            log.warning("indicator_registry.delete_error", error=str(exc)[:100])
            return False

    # ─── Read ─────────────────────────────────────────────────────────────────

    def list_active(self, ticker: str | None = None) -> list[UserIndicator]:
        """Ritorna gli indicatori attivi applicabili al ticker.

        Restituisce: indicatori con ticker_filter=None + indicatori specifici per ticker.
        """
        try:
            with self._client.transaction() as conn:
                if ticker:
                    rows = conn.execute(
                        """
                        SELECT indicator_id, name, expression, description,
                               ticker_filter, chart_type, overlay, is_active, created_at
                        FROM user_indicators
                        WHERE is_active = TRUE
                        AND (ticker_filter IS NULL OR ticker_filter = ?)
                        ORDER BY created_at DESC
                        """,
                        [ticker],
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT indicator_id, name, expression, description,
                               ticker_filter, chart_type, overlay, is_active, created_at
                        FROM user_indicators
                        WHERE is_active = TRUE
                        ORDER BY created_at DESC
                        """,
                    ).fetchall()
            return [_row_to_indicator(r) for r in rows]
        except Exception as exc:
            log.warning("indicator_registry.list_error", error=str(exc)[:100])
            return []

    # ─── Evaluate ─────────────────────────────────────────────────────────────

    def evaluate_all(
        self,
        df: pd.DataFrame,
        ticker: str,
    ) -> dict[str, pd.Series]:
        """Valuta tutti gli indicatori attivi applicabili al ticker.

        Args:
            df: DataFrame OHLCV con colonne ts, open, high, low, close, volume.
            ticker: Ticker corrente.

        Returns:
            Dict {nome_indicatore: pd.Series float64}.
            Indicatori che falliscono vengono skippati con log.warning.
        """
        indicators = self.list_active(ticker)
        results: dict[str, pd.Series] = {}

        for ind in indicators:
            try:
                series = self._evaluator.evaluate(ind.expression, df)
                results[ind.name] = series
            except Exception as exc:
                # Skip graceful: un indicatore malformato non blocca gli altri
                log.warning(
                    "indicator_registry.eval_skip",
                    name=ind.name,
                    error=str(exc)[:100],
                )
                continue

        return results

    def evaluate_one(
        self,
        expression: str,
        df: pd.DataFrame,
    ) -> pd.Series:
        """Valuta un'espressione DSL singola (per preview in UI prima del salvataggio)."""
        return self._evaluator.evaluate(expression, df)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _row_to_indicator(row: tuple) -> UserIndicator:
    """Converte una riga DuckDB in UserIndicator."""
    return UserIndicator(
        indicator_id=str(row[0]),
        name=str(row[1]),
        expression=str(row[2]),
        description=str(row[3]) if row[3] else "",
        ticker_filter=str(row[4]) if row[4] else None,
        chart_type=str(row[5]) if row[5] else "line",
        overlay=bool(row[6]),
        is_active=bool(row[7]),
        created_at=pd.Timestamp(row[8]).to_pydatetime() if row[8] else datetime.now(UTC),
    )


def _make_dummy_ohlcv(n: int = 60) -> pd.DataFrame:
    """Crea un DataFrame OHLCV dummy per la validazione offline delle espressioni DSL."""
    rng   = np.random.default_rng(42)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    return pd.DataFrame({
        "ts":     pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open":   close * rng.uniform(0.995, 1.005, n),
        "high":   close * rng.uniform(1.000, 1.010, n),
        "low":    close * rng.uniform(0.990, 1.000, n),
        "close":  close,
        "volume": rng.integers(100_000, 1_000_000, n).astype(np.float64),
    })


# ─── Singleton ────────────────────────────────────────────────────────────────

_registry_lock = threading.Lock()
_default_registry: IndicatorRegistry | None = None


def get_indicator_registry() -> IndicatorRegistry:
    """Singleton thread-safe per IndicatorRegistry."""
    global _default_registry  # noqa: PLW0603
    with _registry_lock:
        if _default_registry is None:
            _default_registry = IndicatorRegistry()
        return _default_registry


def reset_indicator_registry() -> None:
    """Reset singleton — uso esclusivo nei test."""
    global _default_registry  # noqa: PLW0603
    with _registry_lock:
        _default_registry = None
