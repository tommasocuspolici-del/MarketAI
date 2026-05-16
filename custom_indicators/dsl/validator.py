"""DSL expression validator — checks names against the safe namespace.

Runs after DSLParser (which validates node types) and before DSLEvaluator.
Ensures that every Name in the expression refers to a known safe function,
not an arbitrary identifier that could be used for introspection.
"""
from __future__ import annotations

import ast

from custom_indicators.dsl.namespace import build_namespace
from custom_indicators.dsl.parser import DSLSyntaxError

__version__ = "10.0.0"

__all__ = [
    "DSLValidator",
]

# Names that are constants, not function calls — always allowed.
_CONSTANT_NAMES: frozenset[str] = frozenset({"True", "False", "None"})


class DSLValidator:
    """Validates that all Name nodes in a DSL expression are whitelisted.

    Usage::

        parser    = DSLParser()
        validator = DSLValidator()
        tree = parser.parse("signal('macro') > 0.2 and n_agreeing(0.2) >= 3")
        validator.validate(tree)   # raises DSLSyntaxError if unknown names
    """

    def __init__(self) -> None:
        # Build the safe namespace once to get the set of allowed names
        _ns = build_namespace()
        self._allowed_names: frozenset[str] = frozenset(_ns.keys()) | _CONSTANT_NAMES

    def validate(self, tree: ast.Expression) -> None:
        """Check that all Name nodes reference whitelisted identifiers.

        Raises:
            DSLSyntaxError: if an unknown identifier is found.
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id not in self._allowed_names:
                raise DSLSyntaxError(
                    f"unknown identifier '{node.id}' — "
                    f"only safe functions are allowed: {sorted(self._allowed_names - {'__builtins__'})}"
                )
