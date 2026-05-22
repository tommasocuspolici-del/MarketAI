"""Tests per engine.data_universe.cross_source_validator_v2."""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from engine.data_universe.cross_source_validator_v2 import (
    CrossSourceValidatorV2,
    ValidationResult,
    EMPLOYMENT_DISCREPANCY_THRESHOLD,
    CPI_DISCREPANCY_THRESHOLD,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_db(query_results: dict[str, pd.DataFrame] | None = None) -> MagicMock:
    """Crea un mock DuckDBClient che restituisce DataFrames predefiniti per query_df."""
    db = MagicMock()
    results = query_results or {}

    def _query_df(sql: str, params: list | None = None) -> pd.DataFrame:
        if params:
            series_id = params[0]
            return results.get(series_id, pd.DataFrame())
        return pd.DataFrame()

    db.query_df = _query_df
    return db


def _make_series(values: list[float]) -> pd.DataFrame:
    """Crea un DataFrame ts/value per N periodi mensili."""
    dates = pd.date_range("2024-01-01", periods=len(values), freq="MS")
    return pd.DataFrame({"ts": dates, "value": values})


# ─── Instantiation ────────────────────────────────────────────────────────────

class TestInstantiation:
    def test_instantiates_with_mock_db(self) -> None:
        db = _make_db()
        validator = CrossSourceValidatorV2(db=db)
        assert validator is not None

    def test_run_all_returns_list(self) -> None:
        """run_all() restituisce una lista (eventualmente vuota) anche senza dati."""
        db = _make_db()  # tutte le query restituiscono DataFrame vuoto
        validator = CrossSourceValidatorV2(db=db)
        results = validator.run_all()
        assert isinstance(results, list)
        # Tre validazioni eseguite: employment, CPI, VIX
        assert len(results) == 3

    def test_run_all_handles_query_exception(self) -> None:
        """run_all() non solleva se query_df lancia eccezione."""
        db = MagicMock()
        db.query_df.side_effect = RuntimeError("DB not available")
        validator = CrossSourceValidatorV2(db=db)
        # Non deve sollevare; le eccezioni vengono swallowate internamente
        results = validator.run_all()
        assert isinstance(results, list)


# ─── _compute_discrepancy ─────────────────────────────────────────────────────

class TestComputeDiscrepancy:
    def test_identical_series_ok(self) -> None:
        """Serie identiche → severity='ok', discrepancy_pct=0."""
        values = [100.0, 101.0, 99.5, 102.3]
        df = _make_series(values)
        result = CrossSourceValidatorV2._compute_discrepancy(
            df_a=df,
            df_b=df.copy(),
            threshold=EMPLOYMENT_DISCREPANCY_THRESHOLD,
            series_a="PAYEMS",
            series_b="CES0000000001",
            source_a="FRED",
            source_b="BLS",
        )
        assert result.severity == "ok"
        assert result.discrepancy_pct == 0.0
        assert result.n_compared == len(values)

    def test_twenty_percent_diff_warn_or_critical(self) -> None:
        """20% di differenza → severity warn o critical (mai ok)."""
        df_a = _make_series([100.0, 100.0, 100.0])
        df_b = _make_series([120.0, 120.0, 120.0])  # 20% gap
        result = CrossSourceValidatorV2._compute_discrepancy(
            df_a=df_a,
            df_b=df_b,
            threshold=EMPLOYMENT_DISCREPANCY_THRESHOLD,  # 1%
            series_a="PAYEMS",
            series_b="CES0000000001",
            source_a="FRED",
            source_b="BLS",
        )
        assert result.severity in ("warn", "critical")
        assert result.discrepancy_pct > 0

    def test_empty_df_a_returns_ok_no_data(self) -> None:
        """df_a vuoto → n_compared=0, severity='ok', messaggio dati insufficienti."""
        df_b = _make_series([100.0, 101.0])
        result = CrossSourceValidatorV2._compute_discrepancy(
            df_a=pd.DataFrame(),
            df_b=df_b,
            threshold=CPI_DISCREPANCY_THRESHOLD,
            series_a="CPIAUCSL",
            series_b="CUUR0000SA0",
            source_a="FRED",
            source_b="BLS",
        )
        assert result.severity == "ok"
        assert result.n_compared == 0

    def test_empty_df_b_returns_ok_no_data(self) -> None:
        """df_b vuoto → n_compared=0, severity='ok'."""
        df_a = _make_series([100.0, 101.0])
        result = CrossSourceValidatorV2._compute_discrepancy(
            df_a=df_a,
            df_b=pd.DataFrame(),
            threshold=CPI_DISCREPANCY_THRESHOLD,
            series_a="CPIAUCSL",
            series_b="CUUR0000SA0",
            source_a="FRED",
            source_b="BLS",
        )
        assert result.severity == "ok"
        assert result.n_compared == 0

    def test_both_empty_returns_ok(self) -> None:
        result = CrossSourceValidatorV2._compute_discrepancy(
            df_a=pd.DataFrame(),
            df_b=pd.DataFrame(),
            threshold=0.01,
            series_a="A",
            series_b="B",
            source_a="src1",
            source_b="src2",
        )
        assert result.severity == "ok"
        assert result.n_compared == 0

    def test_no_common_dates_returns_ok(self) -> None:
        """Serie senza date comuni → n_compared=0, severity='ok'."""
        df_a = _make_series([100.0])
        df_b = _make_series([100.0])
        # Shift df_b dates so there is no overlap
        df_b["ts"] = pd.date_range("2025-01-01", periods=1, freq="MS")
        result = CrossSourceValidatorV2._compute_discrepancy(
            df_a=df_a,
            df_b=df_b,
            threshold=0.01,
            series_a="A",
            series_b="B",
            source_a="src1",
            source_b="src2",
        )
        assert result.n_compared == 0
        assert result.severity == "ok"

    def test_result_fields_populated(self) -> None:
        """ValidationResult ha tutti i campi attesi popolati correttamente."""
        df = _make_series([200.0, 200.0])
        result = CrossSourceValidatorV2._compute_discrepancy(
            df_a=df,
            df_b=df.copy(),
            threshold=0.05,
            series_a="VIXCLS",
            series_b="^VIX",
            source_a="FRED",
            source_b="Yahoo Finance",
        )
        assert result.series_a == "VIXCLS"
        assert result.series_b == "^VIX"
        assert result.source_a == "FRED"
        assert result.source_b == "Yahoo Finance"
        assert isinstance(result.message, str)


# ─── Individual validate_* methods ───────────────────────────────────────────

class TestValidateMethods:
    def test_validate_employment_no_data(self) -> None:
        db = _make_db()
        v = CrossSourceValidatorV2(db=db)
        result = v.validate_employment_fred_vs_bls(lookback_days=90)
        assert isinstance(result, ValidationResult)
        assert result.series_a == "PAYEMS"
        assert result.series_b == "CES0000000001"

    def test_validate_cpi_no_data(self) -> None:
        db = _make_db()
        v = CrossSourceValidatorV2(db=db)
        result = v.validate_cpi_fred_vs_bls(lookback_days=90)
        assert isinstance(result, ValidationResult)
        assert result.series_a == "CPIAUCSL"
        assert result.series_b == "CUUR0000SA0"

    def test_validate_vix_no_data(self) -> None:
        db = _make_db()
        v = CrossSourceValidatorV2(db=db)
        result = v.validate_vix_fred_vs_yahoo(lookback_days=30)
        assert isinstance(result, ValidationResult)
        assert result.series_a == "VIXCLS"
        assert result.series_b == "^VIX"

    def test_validate_employment_with_matching_data(self) -> None:
        """Con dati identici l'employment check è ok."""
        values = [158_000.0, 158_100.0, 158_050.0]
        df = _make_series(values)
        db = _make_db({"PAYEMS": df, "CES0000000001": df.copy()})
        v = CrossSourceValidatorV2(db=db)
        result = v.validate_employment_fred_vs_bls()
        assert result.severity == "ok"
        assert result.n_compared == len(values)

    def test_validate_cpi_small_discrepancy_warn(self) -> None:
        """0.5% discrepancy su CPI (threshold 0.1%) → warn."""
        df_a = _make_series([300.0, 301.0, 302.0])
        df_b = _make_series([301.5, 302.5, 303.5])  # ~0.5% gap
        db = _make_db({"CPIAUCSL": df_a, "CUUR0000SA0": df_b})
        v = CrossSourceValidatorV2(db=db)
        result = v.validate_cpi_fred_vs_bls()
        assert result.severity in ("warn", "critical")
