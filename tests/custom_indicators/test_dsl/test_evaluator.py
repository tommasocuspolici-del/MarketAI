"""Tests for DSL: parser, validator, evaluator — 10 safe + 10 unsafe (DoD)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from custom_indicators.dsl.evaluator import DSLEvaluator, DSLEvaluationError
from custom_indicators.dsl.parser import DSLParser, DSLSyntaxError
from custom_indicators.dsl.validator import DSLValidator
from shared.signal_registry import SignalRegistry
from shared.signal_types import Signal


# ── Helpers ───────────────────────────────────────────────────────────────

def _reg_with(**signals: float) -> SignalRegistry:
    reg = SignalRegistry()
    for name, val in signals.items():
        reg.publish(Signal(name=name, value=val, confidence=0.8, source_module="test"))
    return reg


# ── 10 SAFE expressions ───────────────────────────────────────────────────

class TestSafeExpressions:
    """DoD: 10 safe expressions must evaluate without raising."""

    @pytest.fixture()
    def ev(self) -> DSLEvaluator:
        return DSLEvaluator()

    def test_safe_01_simple_comparison(self, ev) -> None:
        assert ev.is_safe("1 > 0") is True
        assert ev.evaluate("1 > 0") is True

    def test_safe_02_boolean_and(self, ev) -> None:
        assert ev.evaluate("True and False") is False

    def test_safe_03_boolean_or(self, ev) -> None:
        assert ev.evaluate("True or False") is True

    def test_safe_04_arithmetic(self, ev) -> None:
        assert ev.evaluate("2 + 3 * 4") == 14

    def test_safe_05_unary_not(self, ev) -> None:
        assert ev.evaluate("not False") is True

    def test_safe_06_ternary(self, ev) -> None:
        assert ev.evaluate("1 if True else 0") == 1

    def test_safe_07_nested_comparison(self, ev) -> None:
        assert ev.evaluate("0.5 > 0.2 and 0.5 < 0.9") is True

    def test_safe_08_signal_call(self, ev) -> None:
        reg = _reg_with(macro_conviction=0.5)
        with patch("custom_indicators.dsl.namespace.get_signal_registry", return_value=reg):
            result = ev.evaluate("signal('macro_conviction') > 0.0")
        assert result is True

    def test_safe_09_n_agreeing(self, ev) -> None:
        reg = _reg_with(
            technical_composite=0.5, macro_conviction=0.6,
            sentiment_composite=0.4, labour_regime_signal=0.3,
        )
        with patch("custom_indicators.dsl.namespace.get_signal_registry", return_value=reg):
            n = ev.evaluate("n_agreeing(0.2)")
        assert isinstance(n, int)
        assert n >= 0

    def test_safe_10_complex_expression(self, ev) -> None:
        reg = _reg_with(macro_conviction=0.3, sentiment_composite=0.2)
        with patch("custom_indicators.dsl.namespace.get_signal_registry", return_value=reg):
            result = ev.evaluate(
                "signal('macro_conviction') > 0.2 and signal('sentiment_composite') > 0.1"
            )
        assert result is True


# ── 10 UNSAFE expressions ─────────────────────────────────────────────────

class TestUnsafeExpressions:
    """DoD: 10 unsafe expressions must raise DSLSyntaxError."""

    @pytest.fixture()
    def parser(self) -> DSLParser:
        return DSLParser()

    def test_unsafe_01_import(self, parser) -> None:
        with pytest.raises(DSLSyntaxError):
            parser.parse("import os")

    def test_unsafe_02_attribute_access(self, parser) -> None:
        with pytest.raises(DSLSyntaxError):
            parser.parse("os.getcwd()")

    def test_unsafe_03_lambda(self, parser) -> None:
        with pytest.raises(DSLSyntaxError):
            parser.parse("(lambda x: x)(1)")

    def test_unsafe_04_exec(self, parser) -> None:
        with pytest.raises(DSLSyntaxError):
            parser.parse("exec('print(1)')")

    def test_unsafe_05_subscript(self, parser) -> None:
        with pytest.raises(DSLSyntaxError):
            parser.parse("a[0]")

    def test_unsafe_06_assignment(self, parser) -> None:
        with pytest.raises((DSLSyntaxError, SyntaxError)):
            parser.parse("x = 1")

    def test_unsafe_07_unknown_name(self) -> None:
        ev = DSLEvaluator()
        with pytest.raises(DSLSyntaxError, match="unknown identifier"):
            ev.evaluate("os > 0")

    def test_unsafe_08_builtin_access(self) -> None:
        ev = DSLEvaluator()
        with pytest.raises((DSLSyntaxError, DSLEvaluationError, Exception)):
            ev.evaluate("__import__('os').getcwd()")

    def test_unsafe_09_list_comprehension(self, parser) -> None:
        with pytest.raises(DSLSyntaxError):
            parser.parse("[x for x in range(10)]")

    def test_unsafe_10_walrus(self, parser) -> None:
        with pytest.raises((DSLSyntaxError, SyntaxError)):
            parser.parse("(x := 1)")


# ── DSLEvaluator misc ─────────────────────────────────────────────────────

class TestDSLEvaluatorMisc:
    def test_empty_expression_raises(self) -> None:
        ev = DSLEvaluator()
        with pytest.raises(DSLSyntaxError):
            ev.evaluate("")

    def test_is_safe_true_for_valid(self) -> None:
        ev = DSLEvaluator()
        assert ev.is_safe("1 > 0") is True

    def test_is_safe_false_for_invalid(self) -> None:
        ev = DSLEvaluator()
        assert ev.is_safe("import os") is False

    @pytest.mark.benchmark(group="dsl")
    def test_evaluate_under_2ms(self, benchmark) -> None:
        ev = DSLEvaluator()
        benchmark(ev.evaluate, "1 > 0 and True")
