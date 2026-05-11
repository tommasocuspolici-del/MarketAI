"""Alert data model + severity levels."""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from shared.types import now_utc

if TYPE_CHECKING:
    from datetime import datetime

__version__ = "6.0.0"

__all__ = ["Alert", "AlertSeverity", "AlertType"]


class AlertSeverity(StrEnum):
    """Alert severity levels."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(StrEnum):
    """Categories of alerts the engine can raise."""

    DATA_QUALITY = "data_quality"
    SENTIMENT_EXTREME = "sentiment_extreme"
    REGIME_CHANGE = "regime_change"
    RISK_SCORE_HIGH = "risk_score_high"
    ANOMALY = "anomaly"
    STRESS_THRESHOLD = "stress_threshold"
    PIPELINE_FAILURE = "pipeline_failure"
    THRESHOLD_BREACH = "threshold_breach"


@dataclass(frozen=True, slots=True)
class Alert:
    """A single alert instance."""

    type: AlertType
    severity: AlertSeverity
    message: str
    triggered_at: datetime = field(default_factory=now_utc)
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict[str, str] = field(default_factory=dict)
    # Used for deduplication (same key within window → suppress)
    dedup_key: str | None = None

    def compute_dedup_key(self) -> str:
        """Stable key for deduplication.

        Same type + same first 100 chars of message yields same key.
        """
        if self.dedup_key:
            return self.dedup_key
        h = hashlib.sha256(
            f"{self.type.value}|{self.message[:100]}".encode()
        ).hexdigest()[:16]
        return h
