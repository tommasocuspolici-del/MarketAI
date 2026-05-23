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
    import pandera as pa  # pragma: no cover

from pandas.api.types import is_datetime64_any_dtype

if TYPE_CHECKING:
    import pandas as pd

__version__ = "8.0.0"

__all__ = [
    "MACRO_SERIES_SCHEMA",
    "OHLCV_SCHEMA",
    "validate_macro_series",
    "validate_ohlcv",
    # v12.0 schemas
    "SIGNAL_SCORECARD_SCHEMA",
    "MODEL_REGISTRY_SCHEMA",
    "WFO_RESULTS_SCHEMA",
    "MACRO_REGIME_TIMELINE_SCHEMA",
    "PORTFOLIO_RISK_METRICS_SCHEMA",
    "POSITION_RISK_CONTRIBUTION_SCHEMA",
    "VOL_SURFACE_SNAPSHOTS_SCHEMA",
    "validate_signal_scorecard",
    "validate_model_registry",
    "validate_wfo_results",
    "validate_macro_regime_timeline",
    "validate_portfolio_risk_metrics",
    "validate_position_risk_contribution",
    "validate_vol_surface_snapshots",
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


# ═══════════════════════════════════════════════════════════════════════════
# v12.0 Schemas
# ═══════════════════════════════════════════════════════════════════════════

def _make_validator(schema: pa.DataFrameSchema, name: str):
    """Factory for validate_* functions."""
    def _validate(df: pd.DataFrame) -> pd.DataFrame:
        from shared.exceptions import DataValidationError
        try:
            return schema.validate(df, lazy=True)
        except pa.errors.SchemaErrors as exc:
            raise DataValidationError(f"{name} schema validation failed: {exc}") from exc
        except pa.errors.SchemaError as exc:
            raise DataValidationError(f"{name} schema validation failed: {exc}") from exc
    _validate.__name__ = f"validate_{name.lower()}"
    return _validate


# signal_scorecard ─────────────────────────────────────────────────────────
SIGNAL_SCORECARD_SCHEMA = pa.DataFrameSchema(
    columns={
        "signal_id": pa.Column(str, nullable=False),
        "snapshot_date": pa.Column(nullable=False),
        "horizon_days": pa.Column(int, checks=pa.Check.gt(0), nullable=False),
        "hit_rate": pa.Column(float, checks=[pa.Check.ge(0.0), pa.Check.le(1.0)], nullable=False),
        "is_significant": pa.Column(bool, nullable=False),
    },
    strict=False,
    coerce=False,
    name="signal_scorecard_schema",
)
validate_signal_scorecard = _make_validator(SIGNAL_SCORECARD_SCHEMA, "signal_scorecard")


# model_registry ───────────────────────────────────────────────────────────
MODEL_REGISTRY_SCHEMA = pa.DataFrameSchema(
    columns={
        "model_id": pa.Column(str, nullable=False),
        "model_type": pa.Column(str, nullable=False),
        "horizon_days": pa.Column(int, checks=pa.Check.gt(0), nullable=False),
        "directional_acc": pa.Column(
            float,
            checks=[pa.Check.ge(0.0), pa.Check.le(1.0)],
            nullable=True,
        ),
    },
    strict=False,
    coerce=False,
    name="model_registry_schema",
)
validate_model_registry = _make_validator(MODEL_REGISTRY_SCHEMA, "model_registry")


# wfo_results ──────────────────────────────────────────────────────────────
WFO_RESULTS_SCHEMA = pa.DataFrameSchema(
    columns={
        "model_id": pa.Column(str, nullable=False),
        "fold_n": pa.Column(int, checks=pa.Check.ge(0), nullable=False),
        "sharpe_fold": pa.Column(float, nullable=True),
        "directional_acc": pa.Column(
            float,
            checks=[pa.Check.ge(0.0), pa.Check.le(1.0)],
            nullable=True,
        ),
    },
    strict=False,
    coerce=False,
    name="wfo_results_schema",
)
validate_wfo_results = _make_validator(WFO_RESULTS_SCHEMA, "wfo_results")


# macro_regime_timeline ────────────────────────────────────────────────────
_VALID_REGIMES = {"expansion", "slowdown", "contraction", "recovery"}

MACRO_REGIME_TIMELINE_SCHEMA = pa.DataFrameSchema(
    columns={
        "regime_label": pa.Column(
            str,
            checks=pa.Check(lambda s: s.isin(_VALID_REGIMES).all(), error="invalid regime label"),
            nullable=False,
        ),
        "prob_expansion": pa.Column(float, checks=[pa.Check.ge(0.0), pa.Check.le(1.0)], nullable=True),
        "prob_slowdown": pa.Column(float, checks=[pa.Check.ge(0.0), pa.Check.le(1.0)], nullable=True),
        "prob_contraction": pa.Column(float, checks=[pa.Check.ge(0.0), pa.Check.le(1.0)], nullable=True),
        "prob_recovery": pa.Column(float, checks=[pa.Check.ge(0.0), pa.Check.le(1.0)], nullable=True),
    },
    strict=False,
    coerce=False,
    name="macro_regime_timeline_schema",
)
validate_macro_regime_timeline = _make_validator(MACRO_REGIME_TIMELINE_SCHEMA, "macro_regime_timeline")


# portfolio_risk_metrics ───────────────────────────────────────────────────
PORTFOLIO_RISK_METRICS_SCHEMA = pa.DataFrameSchema(
    columns={
        "var_95": pa.Column(float, checks=pa.Check.lt(0.0), nullable=False),
        "max_drawdown_1y": pa.Column(
            float,
            checks=[pa.Check.ge(-1.0), pa.Check.le(0.0)],
            nullable=True,
        ),
    },
    strict=False,
    coerce=False,
    name="portfolio_risk_metrics_schema",
)
validate_portfolio_risk_metrics = _make_validator(PORTFOLIO_RISK_METRICS_SCHEMA, "portfolio_risk_metrics")


# position_risk_contribution ───────────────────────────────────────────────
POSITION_RISK_CONTRIBUTION_SCHEMA = pa.DataFrameSchema(
    columns={
        "ticker": pa.Column(str, nullable=False),
        "pct_risk": pa.Column(float, checks=[pa.Check.ge(0.0), pa.Check.le(1.0)], nullable=False),
    },
    strict=False,
    coerce=False,
    name="position_risk_contribution_schema",
)
validate_position_risk_contribution = _make_validator(
    POSITION_RISK_CONTRIBUTION_SCHEMA, "position_risk_contribution"
)


# vol_surface_snapshots ────────────────────────────────────────────────────
VOIL_SURFACE_VIX_CHECK = pa.Check(lambda s: (s > 0).all(), error="vix_* must be > 0")

VOL_SURFACE_SNAPSHOTS_SCHEMA = pa.DataFrameSchema(
    columns={
        "snapshot_at": pa.Column(
            dtype=None,
            checks=_UTC_DATETIME_CHECK,
            nullable=False,
            description="Snapshot timestamp, UTC-aware",
        ),
        "vix_spot": pa.Column(float, checks=pa.Check.gt(0.0), nullable=False),
    },
    strict=False,
    coerce=False,
    name="vol_surface_snapshots_schema",
)
validate_vol_surface_snapshots = _make_validator(VOL_SURFACE_SNAPSHOTS_SCHEMA, "vol_surface_snapshots")
