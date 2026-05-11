"""Alert rule engine — declarative rules from YAML + dedup + persistence.

Rules format (config/alert_rules.yaml):

    rules:
      - id: regime_stress
        type: regime_change
        condition:
          field: regime.label
          op: eq
          value: stress
        severity: critical
        message: "Market regime shifted to STRESS"
        dedup_window_minutes: 60
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from engine.alerts.alert_model import Alert, AlertSeverity, AlertType
from shared.exceptions import AlertError
from shared.logger import get_logger
from shared.types import now_utc

if TYPE_CHECKING:
    from collections.abc import Iterable

__version__ = "6.0.0"

__all__ = ["AlertRule", "RuleEngine"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AlertRule:
    """A single declarative alert rule."""

    rule_id: str
    type: AlertType
    severity: AlertSeverity
    field_path: str            # e.g. "regime.label", "risk_score.score"
    op: str                    # "eq", "ne", "gt", "ge", "lt", "le"
    value: float | str
    message_template: str
    dedup_window_minutes: int = 60


@dataclass(slots=True)
class _DedupRecord:
    """Internal dedup tracking."""
    alert_dedup_key: str
    last_seen: Any                      # datetime
    rule_id: str


class RuleEngine:
    """Evaluates rules against a context dict and produces Alerts."""

    def __init__(
        self,
        rules: Iterable[AlertRule] | None = None,
        rules_path: Path | None = None,
    ) -> None:
        if rules is not None:
            self._rules: list[AlertRule] = list(rules)
        else:
            self._rules = self._load_rules(rules_path)
        # Dedup state — in-memory; production would persist this to SQLite
        self._dedup: dict[str, _DedupRecord] = {}

    @staticmethod
    def _load_rules(path: Path | None) -> list[AlertRule]:
        cfg_path = path or Path("config/alert_rules.yaml")
        if not cfg_path.exists():
            log.warning("alerts.rules_missing", path=str(cfg_path))
            return []
        data = yaml.safe_load(cfg_path.read_text()) or {}
        rules: list[AlertRule] = []
        for raw in data.get("rules", []):
            try:
                rules.append(AlertRule(
                    rule_id=raw["id"],
                    type=AlertType(raw["type"]),
                    severity=AlertSeverity(raw["severity"]),
                    field_path=raw["condition"]["field"],
                    op=raw["condition"]["op"],
                    value=raw["condition"]["value"],
                    message_template=raw["message"],
                    dedup_window_minutes=int(raw.get("dedup_window_minutes", 60)),
                ))
            except (KeyError, ValueError) as e:
                log.error("alerts.invalid_rule", rule=raw, error=str(e))
        log.info("alerts.rules_loaded", n=len(rules))
        return rules

    @property
    def rules(self) -> list[AlertRule]:
        return list(self._rules)

    def evaluate(
        self, context: dict[str, Any], suppress_dedup: bool = False
    ) -> list[Alert]:
        """Evaluate all rules against the context.

        Args:
            context: A dict possibly containing nested objects (dataclasses,
                pydantic models, plain dicts). Rule field_path supports dotted
                navigation (e.g. "risk_score.score").
            suppress_dedup: When True, dedup is bypassed (useful for tests).

        Returns:
            List of triggered Alert objects (after dedup).
        """
        triggered: list[Alert] = []
        for rule in self._rules:
            value = _resolve_path(context, rule.field_path)
            if value is None:
                continue
            if not _eval_op(rule.op, value, rule.value):
                continue
            alert = Alert(
                type=rule.type,
                severity=rule.severity,
                message=rule.message_template.format(value=value),
                metadata={"rule_id": rule.rule_id, "field": rule.field_path},
            )
            dedup_key = alert.compute_dedup_key()
            if not suppress_dedup and self._is_duplicate(
                dedup_key, rule.dedup_window_minutes
            ):
                log.debug("alerts.deduplicated", rule=rule.rule_id)
                continue
            self._dedup[dedup_key] = _DedupRecord(
                alert_dedup_key=dedup_key,
                last_seen=now_utc(),
                rule_id=rule.rule_id,
            )
            triggered.append(alert)
        return triggered

    def _is_duplicate(self, dedup_key: str, window_min: int) -> bool:
        record = self._dedup.get(dedup_key)
        if record is None:
            return False
        delta = now_utc() - record.last_seen
        return bool(delta < timedelta(minutes=window_min))


def _resolve_path(obj: Any, path: str) -> Any:
    """Navigate a dotted path through nested structures."""
    parts = path.split(".")
    cur = obj
    for part in parts:
        if cur is None:
            return None
        cur = cur.get(part) if isinstance(cur, dict) else getattr(cur, part, None)
    return cur


def _eval_op(op: str, actual: Any, expected: Any) -> bool:
    """Evaluate a comparison op."""
    try:
        if op == "eq":
            return bool(actual == expected)
        if op == "ne":
            return bool(actual != expected)
        if op == "gt":
            return float(actual) > float(expected)
        if op == "ge":
            return float(actual) >= float(expected)
        if op == "lt":
            return float(actual) < float(expected)
        if op == "le":
            return float(actual) <= float(expected)
        raise AlertError(f"unsupported op: {op}")
    except (TypeError, ValueError) as e:
        log.warning("alerts.eval_error", op=op, actual=actual, error=str(e))
        return False
