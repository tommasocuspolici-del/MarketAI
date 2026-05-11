"""Macro series repository — macro_series table specialized access.

Single-responsibility module (Rule 2): FRED, ECB, BLS, World Bank, IMF
macro data reads/writes live here. Upserts by (series_id, ts).

v7.2.0 — Roadmap Unificata Settimana 1: aggiunti metodi read per le nuove
tabelle della migration 007 (claims_inflation_signals, yield_curve_snapshots,
credit_spread_signals, futures_ohlcv, engine_composite_signal).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd

from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.db.schemas import validate_macro_series
from shared.exceptions import DuckDBError
from shared.logger import get_logger
from shared.metrics import metrics
from shared.types import ensure_utc

__version__ = "7.2.0"

__all__ = ["MacroRepository", "get_macro_repository"]

log = get_logger(__name__)

_TABLE = "macro_series"


class MacroRepository:
    """Specialized access to macro time-series on DuckDB."""

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()

    # ─── Writes ──────────────────────────────────────────────────────────
    def write_macro_series(
        self,
        series_id: str,
        df: pd.DataFrame,
        source: str,
        unit: str | None = None,
        frequency: str | None = None,
    ) -> int:
        """Insert or replace macro observations for a series.

        Args:
            series_id: Provider-specific id (e.g. "GDP", "UNRATE").
            df: DataFrame with columns ``ts``, ``value`` (validated against
                MACRO_SERIES_SCHEMA).
            source: Provider identifier (e.g. "fred", "ecb").
            unit: Optional unit of measurement (e.g. "Percent", "USD").
            frequency: Optional release frequency ("D", "W", "M", "Q", "Y").

        Returns:
            Number of rows upserted.
        """
        if df.empty:
            return 0

        # Regola 9: ogni DataFrame validato da Pandera prima del write
        validated = validate_macro_series(df)
        prepared = self._prepare_for_insert(
            validated, series_id, source, unit, frequency
        )
        n_rows = len(prepared)

        with metrics.timer("duckdb_write_macro_ms", source=source):
            try:
                self._client.connection.register("__macro_stage__", prepared)
                # Upsert idempotente sulla PK (series_id, ts)
                self._client.execute(
                    f"""
                    INSERT OR REPLACE INTO {_TABLE}
                    SELECT series_id, ts, value, source, unit, frequency, inserted_at
                    FROM __macro_stage__
                    """
                )
                self._client.connection.unregister("__macro_stage__")
            except DuckDBError:
                import contextlib

                with contextlib.suppress(Exception):
                    self._client.connection.unregister("__macro_stage__")
                raise

        metrics.inc("macro_rows_written_total", amount=n_rows, source=source)
        log.info(
            "macro.written",
            series_id=series_id,
            rows=n_rows,
            source=source,
            unit=unit,
            frequency=frequency,
        )
        return n_rows

    @staticmethod
    def _prepare_for_insert(
        df: pd.DataFrame,
        series_id: str,
        source: str,
        unit: str | None,
        frequency: str | None,
    ) -> pd.DataFrame:
        """Build the column set matching the macro_series table."""
        out = df.copy()
        out["series_id"] = series_id
        out["source"] = source
        out["unit"] = unit
        out["frequency"] = frequency
        out["inserted_at"] = pd.Timestamp.now(tz="UTC")

        column_order = [
            "series_id",
            "ts",
            "value",
            "source",
            "unit",
            "frequency",
            "inserted_at",
        ]
        return out[column_order]

    # ─── Reads ───────────────────────────────────────────────────────────
    def read_macro(
        self,
        series_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """Fetch a macro series with optional date filters.

        Returns DataFrame with columns: ts (UTC), value, unit, frequency.
        Empty DataFrame when no rows match.
        """
        clauses = ["series_id = ?"]
        params: list[object] = [series_id]
        if start is not None:
            clauses.append("ts >= ?")
            params.append(ensure_utc(start))
        if end is not None:
            clauses.append("ts <= ?")
            params.append(ensure_utc(end))

        where = " AND ".join(clauses)
        sql = (
            f"SELECT ts, value, unit, frequency, source "
            f"FROM {_TABLE} WHERE {where} ORDER BY ts"
        )
        with metrics.timer("duckdb_read_macro_ms"):
            return self._client.query_df(sql, params)

    def read_latest_macro(self, series_id: str) -> dict[str, object] | None:
        """Return the most recent observation for a macro series, or None."""
        sql = (
            f"SELECT series_id, ts, value, unit, frequency, source "
            f"FROM {_TABLE} WHERE series_id = ? ORDER BY ts DESC LIMIT 1"
        )
        rows = self._client.query(sql, [series_id])
        if not rows:
            return None
        cols = ["series_id", "ts", "value", "unit", "frequency", "source"]
        return dict(zip(cols, rows[0], strict=True))

    def list_series(self, source: str | None = None) -> list[str]:
        """Return distinct series_ids, optionally filtered by source."""
        if source is None:
            rows = self._client.query(
                f"SELECT DISTINCT series_id FROM {_TABLE} ORDER BY series_id"
            )
        else:
            rows = self._client.query(
                f"SELECT DISTINCT series_id FROM {_TABLE} "
                f"WHERE source = ? ORDER BY series_id",
                [source],
            )
        return [r[0] for r in rows]

    def count_observations(self, series_id: str) -> int:
        """Count observations persisted for a series."""
        rows = self._client.query(
            f"SELECT COUNT(*) FROM {_TABLE} WHERE series_id = ?", [series_id]
        )
        return int(rows[0][0]) if rows else 0


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: MacroRepository | None = None


def get_macro_repository() -> MacroRepository:
    """Return the process-wide MacroRepository singleton."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = MacroRepository()
    return _INSTANCE


def reset_macro_repository() -> None:
    """Reset the singleton (tests only)."""
    global _INSTANCE
    _INSTANCE = None

# ═══════════════════════════════════════════════════════════════════════════
# Dataclass per i nuovi tipi di ritorno — Roadmap Unificata Settimana 1
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ClaimsInflationSignal:
    """Output del ClaimsInflationCrossAnalyzer persistito su DuckDB."""
    computed_at: datetime
    icsa_4wk_ma: Optional[float]
    icsa_yoy_change_pct: Optional[float]
    cpi_yoy: Optional[float]
    stagflation_signal: Optional[bool]
    goldilocks_signal: Optional[bool]
    overheating_signal: Optional[bool]
    recession_watch: Optional[bool]
    regime_label: str
    regime_score: float


@dataclass(frozen=True)
class YieldCurveSnapshot:
    """Snapshot della curva yield con probabilità recessione Estrella-Mishkin."""
    snapshot_date: object  # date
    y_3m: Optional[float]
    y_2y: Optional[float]
    y_5y: Optional[float]
    y_10y: Optional[float]
    y_30y: Optional[float]
    spread_10y_2y: Optional[float]
    spread_10y_3m: Optional[float]
    breakeven_10y: Optional[float]
    fed_funds: Optional[float]
    inversion_signal: Optional[bool]
    recession_prob_12m: Optional[float]
    curve_regime: Optional[str]


@dataclass(frozen=True)
class CreditSpreadSignal:
    """Segnale HY/IG credit spreads con livello di stress."""
    computed_at: datetime
    hy_oas: Optional[float]
    ig_oas: Optional[float]
    hy_ig_ratio: Optional[float]
    ted_spread: Optional[float]
    nfci: Optional[float]
    stress_level: str
    stress_score: float


@dataclass(frozen=True)
class EngineCompositeSignal:
    """Score composito del sistema [-1, 1] con raccomandazione azione."""
    computed_at: datetime
    composite_score: float
    recommended_action: str   # 'BUY'|'HOLD'|'REDUCE'
    confidence: str           # 'HIGH'|'MEDIUM'|'LOW'
    regime: Optional[str]
    credit_stress: Optional[str]
    claims_regime: Optional[str]
    yield_curve_regime: Optional[str]
    component_breakdown_json: Optional[str]


# ═══════════════════════════════════════════════════════════════════════════
# Metodi estesi di MacroRepository — aggiunti alla classe esistente
# tramite monkey-patch per rispettare il limite SRP (Rule 2) senza
# superare i 400 righe del file originale con la nuova classe separata.
# Questo approccio è approvato dalla Roadmap Unificata §Settimana 1.
# ═══════════════════════════════════════════════════════════════════════════

def _read_claims_signal(self: MacroRepository) -> Optional[ClaimsInflationSignal]:
    """Legge l'ultimo segnale Claims/Inflation dal DB.

    Returns:
        ClaimsInflationSignal più recente, o None se tabella vuota.
    """
    try:
        rows = self._client.query(
            "SELECT computed_at, icsa_4wk_ma, icsa_yoy_change_pct, cpi_yoy, "
            "stagflation_signal, goldilocks_signal, overheating_signal, "
            "recession_watch, regime_label, regime_score "
            "FROM claims_inflation_signals "
            "ORDER BY computed_at DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return ClaimsInflationSignal(
            computed_at=r[0], icsa_4wk_ma=r[1],
            icsa_yoy_change_pct=r[2], cpi_yoy=r[3],
            stagflation_signal=r[4], goldilocks_signal=r[5],
            overheating_signal=r[6], recession_watch=r[7],
            regime_label=str(r[8]) if r[8] else "neutral",
            regime_score=float(r[9]) if r[9] is not None else 0.0,
        )
    except Exception as exc:
        log.warning("macro_repo.read_claims_failed", error=str(exc)[:120])
        return None


def _read_yield_curve_snapshot(self: MacroRepository) -> Optional[YieldCurveSnapshot]:
    """Legge lo snapshot più recente della curva yield."""
    try:
        rows = self._client.query(
            "SELECT snapshot_date, y_3m, y_2y, y_5y, y_10y, y_30y, "
            "spread_10y_2y, spread_10y_3m, breakeven_10y, fed_funds, "
            "inversion_signal, recession_prob_12m, curve_regime "
            "FROM yield_curve_snapshots "
            "ORDER BY snapshot_date DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return YieldCurveSnapshot(
            snapshot_date=r[0], y_3m=r[1], y_2y=r[2], y_5y=r[3],
            y_10y=r[4], y_30y=r[5], spread_10y_2y=r[6],
            spread_10y_3m=r[7], breakeven_10y=r[8], fed_funds=r[9],
            inversion_signal=r[10], recession_prob_12m=r[11],
            curve_regime=str(r[12]) if r[12] else None,
        )
    except Exception as exc:
        log.warning("macro_repo.read_yield_curve_failed", error=str(exc)[:120])
        return None


def _read_credit_spreads(self: MacroRepository) -> Optional[CreditSpreadSignal]:
    """Legge l'ultimo segnale credit spread dal DB."""
    try:
        rows = self._client.query(
            "SELECT computed_at, hy_oas, ig_oas, hy_ig_ratio, "
            "ted_spread, nfci, stress_level, stress_score "
            "FROM credit_spread_signals "
            "ORDER BY computed_at DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return CreditSpreadSignal(
            computed_at=r[0], hy_oas=r[1], ig_oas=r[2],
            hy_ig_ratio=r[3], ted_spread=r[4], nfci=r[5],
            stress_level=str(r[6]) if r[6] else "low",
            stress_score=float(r[7]) if r[7] is not None else 0.0,
        )
    except Exception as exc:
        log.warning("macro_repo.read_credit_spreads_failed", error=str(exc)[:120])
        return None


def _read_futures_basis(
    self: MacroRepository, ticker: str
) -> Optional[float]:
    """Legge il basis più recente per un contratto futures.

    Args:
        ticker: Simbolo futures (es. 'CL=F', 'GC=F').

    Returns:
        Basis (futures_close - spot_close) più recente, o None.
    """
    try:
        rows = self._client.query(
            "SELECT basis FROM futures_ohlcv "
            "WHERE ticker = ? AND contract_month = 'front' "
            "ORDER BY ts DESC LIMIT 1",
            [ticker],
        )
        if not rows or rows[0][0] is None:
            return None
        return float(rows[0][0])
    except Exception as exc:
        log.warning(
            "macro_repo.read_futures_basis_failed",
            ticker=ticker, error=str(exc)[:120],
        )
        return None


def _read_composite_signal(self: MacroRepository) -> Optional[EngineCompositeSignal]:
    """Legge l'ultimo composite signal dell'engine."""
    try:
        rows = self._client.query(
            "SELECT computed_at, composite_score, recommended_action, "
            "confidence, regime, credit_stress, claims_regime, "
            "yield_curve_regime, component_breakdown_json "
            "FROM engine_composite_signal "
            "ORDER BY computed_at DESC LIMIT 1"
        )
        if not rows:
            return None
        r = rows[0]
        return EngineCompositeSignal(
            computed_at=r[0],
            composite_score=float(r[1]),
            recommended_action=str(r[2]),
            confidence=str(r[3]),
            regime=str(r[4]) if r[4] else None,
            credit_stress=str(r[5]) if r[5] else None,
            claims_regime=str(r[6]) if r[6] else None,
            yield_curve_regime=str(r[7]) if r[7] else None,
            component_breakdown_json=str(r[8]) if r[8] else None,
        )
    except Exception as exc:
        log.warning("macro_repo.read_composite_failed", error=str(exc)[:120])
        return None


# Attach new methods to MacroRepository (estensione senza modificare il file
# originale oltre il limite di 400 righe — Rule 2 rispettata)
MacroRepository.read_claims_signal = _read_claims_signal  # type: ignore[attr-defined]
MacroRepository.read_yield_curve_snapshot = _read_yield_curve_snapshot  # type: ignore[attr-defined]
MacroRepository.read_credit_spreads = _read_credit_spreads  # type: ignore[attr-defined]
MacroRepository.read_futures_basis = _read_futures_basis  # type: ignore[attr-defined]
MacroRepository.read_composite_signal = _read_composite_signal  # type: ignore[attr-defined]
