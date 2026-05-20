"""design_tokens — TOKENS singleton + re-export from theme.py.

Convenience shim so new components can write:
    from presentation.ui.design_tokens import TOKENS

The authoritative source is ``presentation/ui/theme.py`` (YAML-backed).
TOKENS is loaded once at import time via the @lru_cache loader.
"""
from __future__ import annotations

from presentation.ui.theme import DesignTokens, Colors, load_design_tokens

__all__ = ["TOKENS", "DesignTokens", "Colors"]

TOKENS: DesignTokens = load_design_tokens()
