"""Alert system — rule-based + dedup + persistence."""
from __future__ import annotations

from engine.alerts.alert_model import Alert, AlertSeverity, AlertType
from engine.alerts.rule_engine import AlertRule, RuleEngine

__version__ = "6.0.0"

__all__ = [
    "Alert",
    "AlertRule",
    "AlertSeverity",
    "AlertType",
    "RuleEngine",
]
