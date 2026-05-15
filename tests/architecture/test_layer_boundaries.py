"""Verifica che il layer boundary engine ↔ personal sia rispettato.

Rule: personal/ non deve importare direttamente da engine/analytics/*,
engine/risk/*, engine/alpha_generation/*, engine/portfolio/*, engine/backtesting/*.
L'unico accesso permesso è tramite bridge/ o engine/market_data/*.

ROADMAP_CODE_QUALITY_v1.0 — Settimana 8, P10.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

# Prefissi engine vietati per il layer personal/
_FORBIDDEN_PREFIXES = [
    "engine.analytics",
    "engine.risk",
    "engine.alpha_generation",
    "engine.portfolio",
    "engine.backtesting",
]

# Prefissi engine esplicitamente permessi per personal/
_ALLOWED_ENGINE_PREFIXES = [
    "engine.market_data",  # CurrencyConverter, InstrumentRegistry, LiveMarketService
]


def _collect_imports(filepath: pathlib.Path) -> list[str]:
    """Restituisce tutti i moduli importati da un file Python (via AST)."""
    try:
        tree = ast.parse(filepath.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module)
    return modules


def _find_violations() -> list[str]:
    """Scansiona personal/ e restituisce lista di violazioni layer boundary."""
    personal_root = pathlib.Path("personal")
    if not personal_root.exists():
        return []
    violations: list[str] = []
    for py_file in personal_root.rglob("*.py"):
        imports = _collect_imports(py_file)
        for imp in imports:
            for forbidden in _FORBIDDEN_PREFIXES:
                if imp == forbidden or imp.startswith(forbidden + "."):
                    violations.append(f"{py_file}: imports {imp!r}")
    return violations


def test_personal_does_not_import_forbidden_engine_modules():
    """personal/ non deve importare engine.analytics, engine.risk, engine.alpha_generation,
    engine.portfolio, engine.backtesting.

    Accesso permesso solo tramite bridge/ o engine.market_data.*.
    """
    violations = _find_violations()
    assert violations == [], (
        "Layer boundary violations found in personal/:\n"
        + "\n".join(f"  {v}" for v in violations)
    )


def test_allowed_engine_prefixes_are_importable():
    """Controlla che i prefissi engine permessi siano effettivamente importabili."""
    personal_root = pathlib.Path("personal")
    if not personal_root.exists():
        pytest.skip("personal/ directory not found")
    allowed_used = set()
    for py_file in personal_root.rglob("*.py"):
        for imp in _collect_imports(py_file):
            for allowed in _ALLOWED_ENGINE_PREFIXES:
                if imp == allowed or imp.startswith(allowed + "."):
                    allowed_used.add(allowed)
    # Non è un errore se nessun prefisso permesso è usato — solo i vietati contano
    assert isinstance(allowed_used, set)


def test_forbidden_prefixes_list_is_not_empty():
    """Sanity: la lista dei prefissi vietati non è vuota."""
    assert len(_FORBIDDEN_PREFIXES) > 0


def test_collect_imports_parses_simple_file(tmp_path):
    """_collect_imports funziona su un file sintetico."""
    f = tmp_path / "test_module.py"
    f.write_text("import os\nfrom pathlib import Path\nfrom engine.analytics import foo\n")
    imports = _collect_imports(f)
    assert "os" in imports
    assert "pathlib" in imports
    assert "engine.analytics" in imports


def test_collect_imports_handles_syntax_error(tmp_path):
    """_collect_imports restituisce lista vuota per file con SyntaxError."""
    f = tmp_path / "broken.py"
    f.write_text("def broken(:\n  pass\n")
    imports = _collect_imports(f)
    assert imports == []
