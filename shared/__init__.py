"""Shared infrastructure layer.

This package contains code that is layer-agnostic: exceptions, logging,
types, configuration, database clients, rate limiting, health checks, and
observability. ``engine/`` and ``personal/`` both depend on ``shared/``.

Rule 4: absolute imports, no circular deps.
Rule 16: every submodule exposes __version__.
"""
from __future__ import annotations

__version__ = "6.0.0"
__all__ = ["__version__"]
