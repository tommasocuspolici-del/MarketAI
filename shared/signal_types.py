"""Signal — typed event emitted by every analytical module (v10, QC-1).

Every module that produces a signal MUST publish a Signal instance to the
SignalBus after each computation. Quality fields (ic_estimate, quality_flag)
are populated by AlphaDecayMonitor and should start as None / "ok".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import numpy as np

__version__ = "10.0.0"

__all__ = [
    "QUALITY_FLAGS",
    "SIGNAL_CUSTOM_PREFIX",
    "Signal",
]

SIGNAL_CUSTOM_PREFIX = "custom."

QualityFlag = Literal["ok", "low_ic", "insufficient_data", "stale"]
QUALITY_FLAGS: tuple[QualityFlag, ...] = ("ok", "low_ic", "insufficient_data", "stale")


@dataclass(frozen=True)
class Signal:
    """Typed signal — v10 with IC and quality tracking (QC-1).

    value ∈ [-1, 1] (clamped), confidence ∈ [0, 1] (clamped).
    ic_estimate: rolling-6M IC, None if < 30 observations yet.
    quality_flag: "ok" | "low_ic" | "insufficient_data" | "stale"
    """

    name: str
    value: float                                   # [-1, 1] — clamped in __post_init__
    confidence: float                              # [0, 1] — clamped in __post_init__
    source_module: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    regime_label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    # Quality fields (QC-1) — None = not yet estimated (< 30 observations)
    ic_estimate: float | None = None
    quality_flag: QualityFlag = "ok"

    # ── Derived properties ─────────────────────────────────────────────────

    @property
    def direction(self) -> str:
        if self.value > 0.3:
            return "bullish"
        if self.value < -0.3:
            return "bearish"
        return "neutral"

    @property
    def is_reliable(self) -> bool:
        """True if the signal has sufficient IC or hasn't been estimated yet."""
        if self.quality_flag == "stale":
            return False
        if self.ic_estimate is None:
            return True          # benefit of the doubt before 30 observations
        return self.quality_flag == "ok"

    def __post_init__(self) -> None:
        object.__setattr__(self, "value",      float(np.clip(self.value, -1.0, 1.0)))
        object.__setattr__(self, "confidence", float(np.clip(self.confidence, 0.0, 1.0)))
        if self.quality_flag not in QUALITY_FLAGS:
            raise ValueError(
                f"quality_flag must be one of {QUALITY_FLAGS}, got {self.quality_flag!r}"
            )
