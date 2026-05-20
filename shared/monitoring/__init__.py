"""shared.monitoring — System health and observability utilities."""
from __future__ import annotations

from shared.monitoring.system_status import SystemStatus, get_system_status

__all__ = ["SystemStatus", "get_system_status"]
