"""Tests for DSLEvaluator, validate_expression, IndicatorRegistry.

Roadmap v3.0 — Settimana 5.

Focus: sicurezza sandbox (nessun eval/exec), correttezza calcoli,
gestione errori, edge cases.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import MagicMock

import duckdb
import numpy as np
import pandas as pd
import pytest

from engine.technical.indicator_dsl import DSLEvaluator, list_supported_functions, validate_expression
from engine.technical.indicator_registry import IndicatorRegistry, reset_indicator_registry
from shared.exceptions import DSLEvalError, DSLParseError


# ─── Fixture DataFrame OHLCV ─────────────────────────────────────────────────

@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """DataFrame OHLCV sintetico deterministico (60 barre)."""
    rng   = np.random.default_rng(0)
    n     = 60
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    return pd.DataFrame({
        "ts":     pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC"),
        "open":   close * 0.999,
        "high":   close * 1.005,
        "low":    close * 0.995,
        "close":  close.astype(np.float64),
        "volume": np.ones(n) * 1_000_000,
    })


@pytest.fixture
def evaluator() -> DSLEvaluator:
    return DSLEvaluator()


@pytest.fixture
def in_memory_registry():
    """IndicatorRegistry con DuckDB in-memory + schema migration 014."""
    reset_indicator_registry()
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE user_indicators (
            indicator_id   VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
            name           VARCHAR NOT NULL,
            expression     VARCHAR NOT NULL,
            description    VARCHAR,
            ticker_filter  VARCHAR,
            chart_type     VARCHAR NOT NULL DEFAULT 'line',
            overlay        BOOLEAN NOT NULL DEFAULT FALSE,
            is_active      BOOLEAN NOT NULL DEFAULT TRUE,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    client = MagicMock()

    @contextmanager
    def _transaction():
        yield conn

    client.transaction = _transaction
    return IndicatorRegistry(client=client)


# ─── Test: funzioni DSL — correttezza calcoli ─────────────────────────────────

class TestDSLFunctions:
    """Tests di correttezza per le funzioni built-in del DSL."""

    def test_ema_length(self, evaluator, ohlcv_df) -> None:
        """EMA ritorna Series della stessa lunghezza del DataFrame."""
        result = evaluator.evaluate("EMA(close, 10)", ohlcv_df)
        assert len(result) == len(ohlcv_df)

    def test_ema_dtype_float64(self, evaluator, ohlcv_df) -> None:
        """EMA ritorna float64 (Regola 8)."""
        result = evaluator.evaluate("EMA(close, 10)", ohlcv_df)
        assert result.dtype == np.float64

    def test_sma_first_n_nan(self, evaluator, ohlcv_df) -> None:
        """SMA(close, 20): le prime 19 barre sono NaN (min_periods=period)."""
        result = evaluator.evaluate("SMA(close, 20)", ohlcv_df)
        assert result.iloc[:19].isna().all()
        assert not result.iloc[19:].isna().any()

    def test_rsi_range(self, evaluator, ohlcv_df) -> None:
        """RSI sempre in [0, 100] su valori non-NaN."""
        result = evaluator.evaluate("RSI(close, 14)", ohlcv_df)
        valid = result.dropna()
        assert (valid >= 0.0).all() and (valid <= 100.0).all()

    def test_macd_length_matches_input(self, evaluator, ohlcv_df) -> None:
        """MACD ritorna Series della stessa lunghezza."""
        result = evaluator.evaluate("MACD(close, 12, 26, 9)", ohlcv_df)
        assert len(result) == len(ohlcv_df)

    def test_macd_default_args(self, evaluator, ohlcv_df) -> None:
        """MACD(close) senza argomenti usa default (12, 26, 9)."""
        r1 = evaluator.evaluate("MACD(close)", ohlcv_df)
        r2 = evaluator.evaluate("MACD(close, 12, 26, 9)", ohlcv_df)
        pd.testing.assert_series_equal(r1, r2)

    def test_std_positive(self, evaluator, ohlcv_df) -> None:
        """STD ritorna valori non-negativi."""
        result = evaluator.evaluate("STD(close, 10)", ohlcv_df)
        assert (result.dropna() >= 0).all()

    def test_max_geq_min(self, evaluator, ohlcv_df) -> None:
        """MAX(close, 10) >= MIN(close, 10) in ogni punto."""
        mx = evaluator.evaluate("MAX(close, 10)", ohlcv_df)
        mn = evaluator.evaluate("MIN(close, 10)", ohlcv_df)
        assert (mx >= mn).all()

    def test_pct_change(self, evaluator, ohlcv_df) -> None:
        """PCT_CHANGE ritorna variazioni tipicamente piccole (< 10%)."""
        result = evaluator.evaluate("PCT_CHANGE(close, 1)", ohlcv_df)
        valid  = result.dropna().abs()
        assert (valid < 0.10).all()

    def test_abs_nonnegative(self, evaluator, ohlcv_df) -> None:
        """ABS(close - EMA(close, 20)) sempre >= 0."""
        result = evaluator.evaluate("ABS(close - EMA(close, 20))", ohlcv_df)
        assert (result.dropna() >= 0).all()


# ─── Test: espressioni composte ───────────────────────────────────────────────

class TestCompositeExpressions:
    """Tests per espressioni aritmetiche e composte."""

    def test_arithmetic_add(self, evaluator, ohlcv_df) -> None:
        """Addizione di due colonne."""
        result = evaluator.evaluate("close + open", ohlcv_df)
        expected = ohlcv_df["close"] + ohlcv_df["open"]
        pd.testing.assert_series_equal(result, expected.astype(np.float64), check_names=False)

    def test_arithmetic_div_scalar(self, evaluator, ohlcv_df) -> None:
        """Divisione per scalare."""
        result = evaluator.evaluate("close / 2", ohlcv_df)
        assert (result == ohlcv_df["close"].values / 2).all()

    def test_distance_from_ema(self, evaluator, ohlcv_df) -> None:
        """close / EMA(close, 20) - 1: ritorna valori piccoli attorno a 0."""
        result = evaluator.evaluate("close / EMA(close, 20) - 1", ohlcv_df)
        valid  = result.dropna().abs()
        assert (valid < 0.5).all()  # entro 50% — serie random ma non esplosiva

    def test_comparison_rsi_overbought(self, evaluator, ohlcv_df) -> None:
        """RSI(close, 14) > 70 ritorna Series booleana."""
        result = evaluator.evaluate("RSI(close, 14) > 70", ohlcv_df)
        assert result.dtype in (bool, np.bool_, object) or result.dtype == np.float64
        # I valori devono essere 0 o 1 (boolean Series può essere cast a float)
        valid = result.dropna()
        assert set(valid.astype(int).unique()).issubset({0, 1})

    def test_unary_negation(self, evaluator, ohlcv_df) -> None:
        """Negazione unaria: -close."""
        result = evaluator.evaluate("-close", ohlcv_df)
        assert (result.values == -ohlcv_df["close"].values).all()

    def test_nested_functions(self, evaluator, ohlcv_df) -> None:
        """EMA di RSI: EMA(RSI(close, 14), 5) — composizione."""
        result = evaluator.evaluate("EMA(RSI(close, 14), 5)", ohlcv_df)
        valid  = result.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_empty_expression_raises(self, evaluator, ohlcv_df) -> None:
        """Espressione vuota → DSLParseError."""
        with pytest.raises(DSLParseError, match="vuota"):
            evaluator.evaluate("", ohlcv_df)

    def test_division_by_zero_series_returns_nan(self, evaluator, ohlcv_df) -> None:
        """Divisione per Serie di zeri → NaN (non eccezione)."""
        df = ohlcv_df.copy()
        df["volume"] = 0.0
        result = evaluator.evaluate("close / volume", df)
        assert result.isna().all()


# ─── Test: sicurezza sandbox ──────────────────────────────────────────────────

class TestDSLSecurity:
    """Tests che verificano che il sandbox impedisce codice malevolo.

    ANTI-REGRESSIONE: questi test devono sempre passare. Se qualcuno aggiunge
    eval() o modifica il whitelist AST, questi test falliscono.
    """

    def test_import_blocked(self, evaluator, ohlcv_df) -> None:
        """import os non permesso nel DSL."""
        with pytest.raises(DSLParseError):
            evaluator.evaluate("__import__('os')", ohlcv_df)

    def test_lambda_blocked(self, evaluator, ohlcv_df) -> None:
        """Lambda non permessa."""
        with pytest.raises((DSLParseError, SyntaxError)):
            evaluator.evaluate("lambda x: x", ohlcv_df)

    def test_attribute_access_blocked(self, evaluator, ohlcv_df) -> None:
        """Accesso ad attributi (obj.attr) non permesso."""
        with pytest.raises(DSLParseError):
            evaluator.evaluate("close.__class__", ohlcv_df)

    def test_unknown_function_raises(self, evaluator, ohlcv_df) -> None:
        """Funzione non in whitelist → DSLParseError con nome funzione."""
        with pytest.raises(DSLParseError, match="EVIL"):
            evaluator.evaluate("EVIL(close, 10)", ohlcv_df)

    def test_unknown_column_raises(self, evaluator, ohlcv_df) -> None:
        """Colonna non in whitelist → DSLParseError."""
        with pytest.raises(DSLParseError):
            evaluator.evaluate("secret_column + 1", ohlcv_df)

    def test_assignment_blocked(self, evaluator, ohlcv_df) -> None:
        """Assegnazione (x = ...) non permessa (mode='eval' la blocca)."""
        with pytest.raises((DSLParseError, SyntaxError)):
            evaluator.evaluate("x = close", ohlcv_df)

    def test_subscript_blocked(self, evaluator, ohlcv_df) -> None:
        """Subscript (obj[key]) non permesso."""
        with pytest.raises(DSLParseError):
            evaluator.evaluate("close[0]", ohlcv_df)

    def test_list_literal_blocked(self, evaluator, ohlcv_df) -> None:
        """Liste non permesse."""
        with pytest.raises(DSLParseError):
            evaluator.evaluate("[1, 2, 3]", ohlcv_df)


# ─── Test: validate_expression ───────────────────────────────────────────────

class TestValidateExpression:
    def test_valid_ema_returns_none(self, ohlcv_df) -> None:
        assert validate_expression("EMA(close, 20)", ohlcv_df) is None

    def test_invalid_returns_string(self, ohlcv_df) -> None:
        err = validate_expression("UNKNOWN_FN(close)", ohlcv_df)
        assert isinstance(err, str)
        assert len(err) > 0

    def test_syntax_error_returns_string(self, ohlcv_df) -> None:
        err = validate_expression("close +++", ohlcv_df)
        assert isinstance(err, str)

    def test_list_supported_functions(self) -> None:
        fns = list_supported_functions()
        assert "EMA" in fns
        assert "RSI" in fns
        assert "MACD" in fns
        assert len(fns) >= 8


# ─── Test: IndicatorRegistry ─────────────────────────────────────────────────

class TestIndicatorRegistry:
    def test_save_and_list(self, in_memory_registry, ohlcv_df) -> None:
        """Salva un indicatore e lo recupera."""
        reg = in_memory_registry
        ind = reg.save("Test EMA", "EMA(close, 20)", sample_df=ohlcv_df)
        assert ind.name == "Test EMA"
        active = reg.list_active()
        assert any(i.indicator_id == ind.indicator_id for i in active)

    def test_save_invalid_expression_raises(self, in_memory_registry) -> None:
        """Espressione invalida → DSLParseError (non persiste)."""
        with pytest.raises(DSLParseError):
            in_memory_registry.save("Bad", "EVIL(close)")

    def test_delete_marks_inactive(self, in_memory_registry, ohlcv_df) -> None:
        """delete() rimuove dall'elenco attivi."""
        ind = in_memory_registry.save("ToDelete", "SMA(close, 5)", sample_df=ohlcv_df)
        in_memory_registry.delete(ind.indicator_id)
        active = in_memory_registry.list_active()
        assert not any(i.indicator_id == ind.indicator_id for i in active)

    def test_ticker_filter(self, in_memory_registry, ohlcv_df) -> None:
        """Indicatore con ticker_filter non appare per altri ticker."""
        in_memory_registry.save("AAPL Only", "RSI(close, 14)",
                                ticker_filter="AAPL", sample_df=ohlcv_df)
        others = in_memory_registry.list_active("MSFT")
        assert not any(i.name == "AAPL Only" for i in others)
        aapls = in_memory_registry.list_active("AAPL")
        assert any(i.name == "AAPL Only" for i in aapls)

    def test_evaluate_all_returns_dict(self, in_memory_registry, ohlcv_df) -> None:
        """evaluate_all ritorna dict {nome: Series}."""
        in_memory_registry.save("EMA20", "EMA(close, 20)", sample_df=ohlcv_df)
        results = in_memory_registry.evaluate_all(ohlcv_df, "AAPL")
        assert "EMA20" in results
        assert isinstance(results["EMA20"], pd.Series)

    def test_evaluate_all_empty_registry(self, in_memory_registry, ohlcv_df) -> None:
        """Registry vuoto → dict vuoto."""
        results = in_memory_registry.evaluate_all(ohlcv_df, "AAPL")
        assert results == {}

    def test_evaluate_one_preview(self, in_memory_registry, ohlcv_df) -> None:
        """evaluate_one per preview senza salvataggio."""
        series = in_memory_registry.evaluate_one("RSI(close, 14)", ohlcv_df)
        assert isinstance(series, pd.Series)
        assert len(series) == len(ohlcv_df)
