"""DSLEvaluator — sandboxed evaluation of custom indicator expressions.

Pipeline:
  1. DSLParser   → parse expression → AST (rejects disallowed node types)
  2. DSLValidator → validate Name nodes against safe namespace
  3. compile(tree) → code object
  4. eval(code, namespace) with __builtins__={} → result

The evaluator is re-entrant and thread-safe (no shared mutable state).
Target: < 2ms per evaluation (pytest-benchmark DoD).
"""
from __future__ import annotations

import ast
from typing import Any

import numpy as np

from custom_indicators.dsl.namespace import build_namespace
from custom_indicators.dsl.parser import DSLParser, DSLSyntaxError
from custom_indicators.dsl.validator import DSLValidator
from shared.alpha_decay_monitor import AlphaDecayMonitor
from shared.logger import get_logger
from shared.resilience.error_policy import apply_error_policy

__version__ = "10.0.0"

__all__ = [
    "DSLEvaluationError",
    "DSLEvaluator",
]

log = get_logger(__name__)


class DSLEvaluationError(RuntimeError):
    """Raised when evaluation of a DSL expression fails at runtime."""


class DSLEvaluator:
    """Safe sandboxed evaluator for DSL expressions.

    Usage::

        evaluator = DSLEvaluator(decay_monitor=monitor, weights_config=cfg)
        result = evaluator.evaluate("signal('macro_conviction') > 0.2")
        # result is True/False or float depending on expression
    """

    def __init__(
        self,
        decay_monitor: AlphaDecayMonitor | None = None,
        weights_config: dict[str, Any] | None = None,
    ) -> None:
        self._parser    = DSLParser()
        self._validator = DSLValidator()
        self._monitor   = decay_monitor
        self._weights   = weights_config or {}

    def evaluate(
        self,
        expression: str,
        extra_context: dict[str, Any] | None = None,
    ) -> bool | float | int | None:
        """Parse and evaluate *expression* in the safe namespace.

        Args:
            expression:    DSL expression string.
            extra_context: Additional context (e.g. portfolio_beta, cash_reserve_months).

        Returns:
            Result of the expression evaluation (bool, float, int, or None).

        Raises:
            DSLSyntaxError:     if parsing fails.
            DSLEvaluationError: if runtime evaluation fails.
        """
        tree = self._parser.parse(expression)
        self._validator.validate(tree)

        ns = build_namespace(
            decay_monitor  = self._monitor,
            weights_config = self._weights,
            extra          = extra_context,
        )

        try:
            code   = compile(tree, "<custom_indicator>", "eval")
            result = eval(code, ns)  # noqa: S307 — namespace has __builtins__={}
        except DSLSyntaxError:
            raise
        except Exception as exc:
            raise DSLEvaluationError(
                f"runtime error evaluating {expression!r}: {exc}"
            ) from exc

        log.debug("dsl.evaluated", expression=expression[:80], result=result)
        if not isinstance(result, (bool, float, int, type(None))):
            return None
        return result

    def is_safe(self, expression: str) -> bool:
        """Return True if *expression* parses and validates without errors."""
        try:
            tree = self._parser.parse(expression)
            self._validator.validate(tree)
            return True
        except DSLSyntaxError:
            return False
