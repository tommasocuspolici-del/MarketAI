"""ConsensusValidator — multi-source agreement check before critical alerts (QC-3).

A BUY/SELL/RISK alert fires only if ≥ N independent signal modules agree.
This eliminates single-module false positives and enforces multi-convergence
(Rule v6.0 §26).

Thresholds (configurable via constructor or config/alpha_decay.yaml):
    BUY_SIGNAL:   min_agreeing = 3 (out of 7 components)
    SELL_SIGNAL:  min_agreeing = 3
    RISK_ALERT:   min_agreeing = 2 (more sensitive)
    REBALANCE:    min_agreeing = 4 (more conservative)
"""
from __future__ import annotations

from dataclasses import dataclass

from shared.logger import get_logger
from shared.signal_registry import get_signal_registry

__version__ = "10.0.0"

__all__ = [
    "AlertType",
    "ConsensusResult",
    "ConsensusValidator",
    "DEFAULT_MIN_AGREEING",
]

log = get_logger(__name__)

AlertType = str

DEFAULT_MIN_AGREEING: dict[str, int] = {
    "BUY_SIGNAL":   3,
    "SELL_SIGNAL":  3,
    "RISK_ALERT":   2,
    "REBALANCE":    4,
}


@dataclass(frozen=True)
class ConsensusResult:
    alert_type:      str
    consensus_met:   bool
    agreeing_count:  int
    required_count:  int
    agreeing_signals: tuple[str, ...]


class ConsensusValidator:
    """Check that ≥ min_agreeing signal modules agree before emitting an alert.

    Usage::

        validator = ConsensusValidator(min_agreeing=3)
        result = validator.check(
            alert_type="BUY_SIGNAL",
            signal_names=["technical_composite", "macro_conviction", "sentiment_composite"],
            threshold=0.2,
        )
        if result.consensus_met:
            emit_alert(...)
    """

    def __init__(self, min_agreeing: int | None = None) -> None:
        self._default_min = min_agreeing

    def check(
        self,
        alert_type: str,
        signal_names: list[str],
        threshold: float = 0.2,
    ) -> ConsensusResult:
        """Return ConsensusResult indicating whether consensus is met.

        A signal 'agrees' when its absolute value ≥ *threshold* and its
        direction matches the expected direction of *alert_type*:
            BUY_SIGNAL / REBALANCE → value > 0
            SELL_SIGNAL / RISK_ALERT → value < 0 (or abs >= threshold for RISK)

        Args:
            alert_type:   one of BUY_SIGNAL, SELL_SIGNAL, RISK_ALERT, REBALANCE
            signal_names: list of signal names to consult (from SignalRegistry)
            threshold:    minimum |value| to count as 'agreeing' (default 0.2)
        """
        min_required = self._default_min or DEFAULT_MIN_AGREEING.get(alert_type, 3)
        snapshot = get_signal_registry().snapshot()

        agreeing: list[str] = []
        for name in signal_names:
            value = snapshot.get(name)
            if value is None:
                continue
            if self._agrees(alert_type, value, threshold):
                agreeing.append(name)

        met = len(agreeing) >= min_required
        result = ConsensusResult(
            alert_type       = alert_type,
            consensus_met    = met,
            agreeing_count   = len(agreeing),
            required_count   = min_required,
            agreeing_signals = tuple(agreeing),
        )
        log.info(
            "consensus_validator.checked",
            alert_type=alert_type,
            met=met,
            agreeing=len(agreeing),
            required=min_required,
        )
        return result

    @staticmethod
    def _agrees(alert_type: str, value: float, threshold: float) -> bool:
        if alert_type in ("BUY_SIGNAL", "REBALANCE"):
            return value >= threshold
        if alert_type == "SELL_SIGNAL":
            return value <= -threshold
        # RISK_ALERT: any strong deviation (either direction) counts
        return abs(value) >= threshold
