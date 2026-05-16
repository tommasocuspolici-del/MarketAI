"""Publisher — publishes custom indicator results to the Signal Bus."""
from __future__ import annotations

from shared.signal_bus import get_signal_bus
from shared.signal_types import Signal

__version__ = "10.0.0"

__all__ = ["publish_indicator_signal"]


def publish_indicator_signal(signal: Signal, ttl_seconds: int = 1800) -> None:
    """Publish a custom indicator result to the Signal Bus (and registry).

    Args:
        signal:      Signal produced by a custom indicator's to_signal() method.
        ttl_seconds: TTL for the SignalRegistry entry (default 30 min).
    """
    bus = get_signal_bus()
    bus._registry.publish(signal, ttl_seconds=ttl_seconds)
    bus.publish(signal)
