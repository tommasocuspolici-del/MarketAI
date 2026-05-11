"""Personal alerts sub-package — v7.2 (fix B8).

Esporta il modello + funzioni public del rule_engine.
"""
from __future__ import annotations

from personal.alerts.alert_model import (
    ALERT_TYPE,
    AlertKind,
    AlertSeverity,
    PersonalAlert,
    THRESHOLD_TYPE,
)
from personal.alerts.rule_engine import (
    list_alerts,
    load_thresholds,
    mark_read,
    run_rules,
    save_thresholds,
)

__version__ = "7.2.0"

__all__ = [
    "ALERT_TYPE",
    "AlertKind",
    "AlertSeverity",
    "PersonalAlert",
    "THRESHOLD_TYPE",
    "list_alerts",
    "load_thresholds",
    "mark_read",
    "run_rules",
    "save_thresholds",
]
