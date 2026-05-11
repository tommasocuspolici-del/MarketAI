"""API hardening layer (Rules 44-48)."""
from __future__ import annotations

from engine.market_data.hardening.sanity_checker import (
    SanityChecker,
    SanityViolation,
    Severity,
)
from engine.market_data.hardening.silent_failure_detector import (
    SilentFailureDetector,
    SilentFailureError,
)

__version__ = "7.1.0"

__all__ = [
    "SanityChecker",
    "SanityViolation",
    "Severity",
    "SilentFailureDetector",
    "SilentFailureError",
]
