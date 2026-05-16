"""DSL AST parser — validates that expressions use only allowed AST nodes.

Security model: parse with `ast.parse(mode='eval')`, walk the AST, and
reject any node type not in the SAFE_NODE_TYPES whitelist. This prevents
arbitrary code execution, attribute access, imports, and introspection.
"""
from __future__ import annotations

import ast
from typing import NoReturn

__version__ = "10.0.0"

__all__ = [
    "DSLSyntaxError",
    "DSLParser",
    "SAFE_NODE_TYPES",
]

# Whitelist of AST node types allowed in custom indicator expressions.
SAFE_NODE_TYPES: frozenset[type] = frozenset({
    ast.Expression,
    # Literals
    ast.Constant,
    # Names (variable / function references — validated against namespace)
    ast.Name,
    # Boolean operators
    ast.BoolOp, ast.And, ast.Or,
    # Comparison
    ast.Compare,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    # Arithmetic
    ast.BinOp,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    # Unary
    ast.UnaryOp, ast.USub, ast.UAdd, ast.Not,
    # Ternary (condition and inline-if)
    ast.IfExp,
    # Function call (validated against safe namespace)
    ast.Call,
    # Tuple / list constants used as call args
    ast.Tuple, ast.List,
    # Load context (attribute of Name, etc.)
    ast.Load,
})


class DSLSyntaxError(ValueError):
    """Raised when an expression contains disallowed AST nodes."""


# Dangerous built-in names that are whitelisted as AST Names but must be blocked.
_BLOCKED_NAMES: frozenset[str] = frozenset({
    "exec", "eval", "compile", "open", "__import__", "__builtins__",
    "globals", "locals", "vars", "dir", "getattr", "setattr", "delattr",
    "hasattr", "object", "type", "super", "input", "print", "breakpoint",
})


class DSLParser:
    """Parses and validates DSL expressions.

    Usage::

        parser = DSLParser()
        tree = parser.parse("signal('macro_conviction') > 0.2 and n_agreeing(0.2) >= 3")
        # tree is an ast.Expression ready for compilation
    """

    def parse(self, expression: str) -> ast.Expression:
        """Parse *expression* and return the AST tree.

        Raises:
            DSLSyntaxError: if the expression has invalid Python syntax or
                            uses disallowed AST node types.
        """
        expression = expression.strip()
        if not expression:
            raise DSLSyntaxError("expression cannot be empty")

        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise DSLSyntaxError(f"syntax error: {exc}") from exc

        self._check_nodes(tree)
        return tree

    # ── Internal ───────────────────────────────────────────────────────────

    def _check_nodes(self, tree: ast.AST) -> None:
        for node in ast.walk(tree):
            if type(node) not in SAFE_NODE_TYPES:
                self._reject(node)
            if isinstance(node, ast.Name) and node.id in _BLOCKED_NAMES:
                raise DSLSyntaxError(
                    f"blocked identifier '{node.id}' — dangerous built-ins are not allowed"
                )

    @staticmethod
    def _reject(node: ast.AST) -> NoReturn:
        name = type(node).__name__
        raise DSLSyntaxError(
            f"disallowed expression element '{name}' — "
            "only arithmetic, comparisons, boolean ops and safe function calls are allowed"
        )
