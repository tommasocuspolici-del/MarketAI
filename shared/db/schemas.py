"""Pandera schemas for all DataFrames entering the database (Rule 9).

Every DataFrame that gets written to DuckDB or read from a fetcher MUST be
validated against the relevant schema here. No dtype="object" is tolerated.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

# v7.1.4 (fix B7): pandera ha riorganizzato il namespace nella 0.20.
#   - pandera < 0.20:  ``import pandera as pa``         (namespace flat)
#   - pandera >= 0.20: ``import pandera.pandas as pa``  (backend-split)
# Per essere robusti su entrambe le linee installate dal pyproject.toml
# (caret ^0.18 puo' risolvere a 0.18.x, 0.19.x; o a 0.20+ se vincolo
# rilassato), proviamo prima il path nuovo, poi facciamo fallback al
# vecchio. La superficie di API che usiamo (Check, Column, DataFrameSchema,
# String, Float, Int, errors.SchemaError) e' identica in entrambi.
try:
    import pandera.pandas as pa  # pandera >= 0.20
except ModuleNotFoundError:  # pragma: no cover -- branch attivo su pandera 0.18/0.19
    import pandera as pa  # type: ignore[no-redef]

from pandas.api.types import is_datetime64_any_dtype

if TYPE_CHECKING:
    import pandas as pd

__version__ = "7.1.4"

__all__ = [
    "MACRO_SERIES_SCHEMA",
    "OHLCV_SCHEMA",
    "validate_macro_series",
    "validate_ohlcv",
]


# ═══════════════════════════════════════════════════════════════════════════
# Custom check: tz-aware datetime (accepts any precision: ns / us / ms)
# ═══════════════════════════════════════════════════════════════════════════
# pandas 2.x defaults to us precision; older code produces ns. Accept both.
# Il controllo verifica: tipo datetime64 + tz-aware (Regola 19).
def _is_utc_aware_datetime(series: pd.Series) -> bool:
    if not is_datetime64_any_dtype(series):
        return False
    # Il tz può essere UTC, pytz.UTC, o datetime.timezone.utc — tutti validi
    tz = getattr(series.dt, "tz", None)
    return tz is not None


_UTC_DATETIME_CHECK = pa.Check(
    _is_utc_aware_datetime,
    element_wise=False,
    error="column must be a tz-aware datetime (Rule 19)",
)


# ═══════════════════════════════════════════════════════════════════════════
# OHLCV schema — matches prices_ohlcv table
# ═══════════════════════════════════════════════════════════════════════════
# Colonne obbligatorie: ts, open, high, low, close, volume
# Colonna opzionale: adj_close
OHLCV_SCHEMA = pa.DataFrameSchema(
    columns={
        "ts": pa.Column(
            # dtype=None + custom check: accetta ns/us/ms purché UTC-aware
            dtype=None,
            checks=_UTC_DATETIME_CHECK,
            nullable=False,
            description="Bar timestamp, UTC-aware (any precision)",
        ),
        "open": pa.Column(
            float,
            checks=pa.Check.ge(0.0),
            nullable=False,
            description="Open price",
        ),
        "high": pa.Column(
            float,
            checks=pa.Check.ge(0.0),
            nullable=False,
            description="High price",
        ),
        "low": pa.Column(
            float,
            checks=pa.Check.ge(0.0),
            nullable=False,
            description="Low price",
        ),
        "close": pa.Column(
            float,
            checks=pa.Check.ge(0.0),
            nullable=False,
            description="Close price",
        ),
        "volume": pa.Column(
            "int64",
            checks=pa.Check.ge(0),
            nullable=False,
            description="Traded volume (shares or contracts)",
        ),
        "adj_close": pa.Column(
            float,
            checks=pa.Check.ge(0.0),
            nullable=True,
            required=False,
            description="Split/dividend adjusted close",
        ),
    },
    strict=False,
    coerce=False,
    name="ohlcv_schema",
)


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Validate an OHLCV DataFrame. Raises DataValidationError on failure."""
    from shared.exceptions import DataValidationError

    try:
        return OHLCV_SCHEMA.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise DataValidationError(f"OHLCV schema validation failed: {exc}") from exc
    except pa.errors.SchemaError as exc:
        raise DataValidationError(f"OHLCV schema validation failed: {exc}") from exc


# ═══════════════════════════════════════════════════════════════════════════
# Macro series schema — matches macro_series table
# ═══════════════════════════════════════════════════════════════════════════
MACRO_SERIES_SCHEMA = pa.DataFrameSchema(
    columns={
        "ts": pa.Column(
            dtype=None,
            checks=_UTC_DATETIME_CHECK,
            nullable=False,
            description="Observation timestamp, UTC-aware (any precision)",
        ),
        "value": pa.Column(
            float,
            nullable=True,  # FRED può avere "." (non rilasciati) → NaN
            description="Observation value (may be NaN for non-releases)",
        ),
    },
    strict=False,
    coerce=False,
    name="macro_series_schema",
)


def validate_macro_series(df: pd.DataFrame) -> pd.DataFrame:
    """Validate a macro-series DataFrame. Raises DataValidationError on failure."""
    from shared.exceptions import DataValidationError

    try:
        return MACRO_SERIES_SCHEMA.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise DataValidationError(f"Macro schema validation failed: {exc}") from exc
    except pa.errors.SchemaError as exc:
        raise DataValidationError(f"Macro schema validation failed: {exc}") from exc
