"""PersonalAlert model — v7.2 (fix B8).

Modello dell'alert personale persistito su UserDataStore. Usato dal
``rule_engine`` per generare alert basati su regole reali (goal a rischio,
soglie patrimonio, cashflow negativo, ribilanciamento), sostituendo il
contenuto hardcoded della pagina P9 v6.

Schema persistenza (UserDataStore):
  entity_type: "personal_alert"
  entity_id:   alert_id (uuid breve)
  payload:     PersonalAlert.to_payload()

Le soglie configurate dall'utente (es. min/max patrimonio per allerta)
sono salvate separatamente con entity_type="personal_alert_threshold".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from personal.data_entry.user_data_store import new_id

__version__ = "7.2.0"

__all__ = [
    "ALERT_TYPE",
    "AlertKind",
    "AlertSeverity",
    "PersonalAlert",
    "THRESHOLD_TYPE",
]

# UserDataStore entity_types per gli alert
ALERT_TYPE = "personal_alert"
THRESHOLD_TYPE = "personal_alert_threshold"


class AlertSeverity(str, Enum):
    """Livello di gravita' dell'alert."""

    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertKind(str, Enum):
    """Tipologia di alert generata dal rule_engine.

    L'identita' del kind viene usata per deduplication: in una finestra
    temporale di 24h, lo stesso AlertKind non viene generato due volte
    (evita spam quando una soglia rimane violata per giorni).
    """

    GOAL_AT_RISK = "GOAL_A_RISCHIO"
    GOAL_ACHIEVED = "GOAL_RAGGIUNTO"
    REBALANCING_NEEDED = "RIBILANCIAMENTO"
    WEALTH_BELOW_MIN = "PATRIMONIO_SOTTO_SOGLIA"
    WEALTH_ABOVE_TARGET = "PATRIMONIO_SOPRA_OBIETTIVO"
    NEGATIVE_CASHFLOW = "CASHFLOW_NEGATIVO"


@dataclass(frozen=True, slots=True)
class PersonalAlert:
    """Singolo alert generato dal rule_engine.

    L'alert e' immutabile dopo la creazione (frozen=True). Per "leggerlo"
    si crea un nuovo record con ``is_read=True`` (vedi ``rule_engine.mark_read``).

    Attributes:
        kind: Tipologia (usata per dedup 24h).
        severity: INFO / WARNING / CRITICAL.
        title: Headline breve mostrata nell'UI (max ~80 char).
        detail: Descrizione lunga, accetta markdown semplice.
        alert_id: UUID breve auto-generato.
        triggered_at: Timestamp UTC di generazione.
        is_read: True se l'utente ha cliccato "✓ Segna come letto".
        goal_id: Link al goal correlato (solo per kind GOAL_*).
    """

    kind: AlertKind
    severity: AlertSeverity
    title: str
    detail: str
    alert_id: str = field(default_factory=new_id)
    triggered_at: datetime = field(default_factory=datetime.utcnow)
    is_read: bool = False
    goal_id: str | None = None

    def to_payload(self) -> dict[str, Any]:
        """Serializza per UserDataStore (JSON-friendly)."""
        return {
            "alert_id": self.alert_id,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "title": self.title,
            "detail": self.detail,
            "triggered_at": self.triggered_at.isoformat(timespec="seconds"),
            "is_read": self.is_read,
            "goal_id": self.goal_id,
        }

    @classmethod
    def from_payload(cls, p: dict[str, Any]) -> "PersonalAlert":
        """Deserializza da UserDataStore. Tollerante a chiavi mancanti."""
        triggered_raw = p.get("triggered_at")
        if isinstance(triggered_raw, datetime):
            triggered = triggered_raw
        elif isinstance(triggered_raw, str):
            triggered = datetime.fromisoformat(triggered_raw)
        else:
            triggered = datetime.utcnow()
        return cls(
            alert_id=str(p["alert_id"]),
            kind=AlertKind(p["kind"]),
            severity=AlertSeverity(p["severity"]),
            title=str(p["title"]),
            detail=str(p["detail"]),
            triggered_at=triggered,
            is_read=bool(p.get("is_read", False)),
            goal_id=p.get("goal_id"),
        )
