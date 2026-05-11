"""GoalContribution + add_contribution + list_contributions (v7.2 fix B7).

Estratto da goal_form.py per rispettare Rule 2 (max 400 righe per file).
Mantiene l'API public identica: la riesporta da goal_form.__init__ via
``__all__``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from personal.data_entry.user_data_store import (
    UserDataStore,
    get_default_store,
    new_id,
)

__version__ = "7.2.0"

__all__ = [
    "CONTRIBUTION_TYPE",
    "ContributionKind",
    "GoalContribution",
    "add_contribution",
    "list_contributions",
]

# UserDataStore entity_type per contributi
CONTRIBUTION_TYPE = "goal_contribution"


# Re-import lazy per evitare ciclo:
# goal_form.py importa da qui → qui non possiamo importare da goal_form.
# I tipi GoalInput, ContributionKind necessari runtime sono recuperati lazy
# dentro le funzioni stesse.

# Per il modello: ContributionKind e' definita qui sotto, NON in goal_form.
from enum import Enum


class ContributionKind(str, Enum):
    """Tipo di operazione registrata nello storico contributi."""

    DEPOSIT = "DEPOSITO"
    WITHDRAWAL = "PRELIEVO"
    AUTO = "AUTO_PERIODICO"


class GoalContribution(BaseModel):
    """Singola operazione su un obiettivo (deposito / prelievo / auto).

    L'amount e' SEMPRE positivo per chiarezza UI; la direzione effettiva
    e' codificata in ``kind``: DEPOSIT/AUTO -> +amount, WITHDRAWAL -> -amount.
    Il delta applicato a current_amount del goal e' calcolato in
    ``add_contribution()`` in base a kind.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    contribution_id: str = Field(default_factory=new_id)
    goal_id: str
    amount: float = Field(gt=0)        # sempre positivo
    kind: ContributionKind
    note: str = ""
    executed_at: datetime = Field(default_factory=datetime.utcnow)

    def to_payload(self) -> dict[str, Any]:
        return {
            "contribution_id": self.contribution_id,
            "goal_id": self.goal_id,
            "amount": self.amount,
            "kind": self.kind.value,
            "note": self.note,
            "executed_at": self.executed_at.isoformat(timespec="seconds"),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "GoalContribution":
        data = dict(payload)
        if isinstance(data.get("executed_at"), str):
            data["executed_at"] = datetime.fromisoformat(data["executed_at"])
        return cls.model_validate(data)


def add_contribution(
    goal_id: str,
    amount: float,
    kind: ContributionKind,
    note: str = "",
    store: UserDataStore | None = None,
) -> Any:  # ritorna GoalInput; tipato Any per evitare import ciclico
    """Applica un deposito/prelievo/auto al goal e persiste lo storico.

    Comportamento:
      - DEPOSIT  -> current_amount += amount
      - AUTO     -> current_amount += amount (loggato come AUTO_PERIODICO)
      - WITHDRAWAL -> current_amount = max(0, current_amount - amount)
                      (il saldo non puo' scendere sotto 0)

    Args:
        goal_id: ID del goal target.
        amount: Importo SEMPRE positivo.
        kind: Tipo di operazione.
        note: Annotazione libera.
        store: Override per test. Default singleton.

    Returns:
        GoalInput aggiornato con il nuovo current_amount.

    Raises:
        ValueError: se amount <= 0 o se goal_id non esiste.
    """
    if amount <= 0:
        raise ValueError(
            f"add_contribution: amount deve essere > 0, ricevuto {amount}"
        )
    s = store or get_default_store()

    # Lazy import per rompere il ciclo goal_form ↔ goal_contributions
    from personal.data_entry.goal_form import list_goals, save_goal

    goals = list_goals(s)
    goal = next((g for g in goals if g.goal_id == goal_id), None)
    if goal is None:
        raise ValueError(f"Goal '{goal_id}' non trovato.")

    if kind in (ContributionKind.DEPOSIT, ContributionKind.AUTO):
        new_amount = goal.current_amount + amount
    else:  # WITHDRAWAL
        new_amount = max(0.0, goal.current_amount - amount)

    updated_goal = goal.model_copy(update={"current_amount": new_amount})
    save_goal(updated_goal, s)

    contrib = GoalContribution(
        goal_id=goal_id,
        amount=amount,
        kind=kind,
        note=note,
    )
    s.upsert(CONTRIBUTION_TYPE, contrib.contribution_id, contrib.to_payload())
    return updated_goal


def list_contributions(
    goal_id: str,
    store: UserDataStore | None = None,
) -> list[GoalContribution]:
    """Storico contributi per un goal, dal piu' recente.

    Filtra per goal_id e ordina per executed_at DESC.
    """
    s = store or get_default_store()
    out: list[GoalContribution] = []
    for r in s.list_by_type(CONTRIBUTION_TYPE):
        try:
            c = GoalContribution.from_payload(r.payload)
        except (ValueError, KeyError, TypeError):
            continue
        if c.goal_id == goal_id:
            out.append(c)
    out.sort(key=lambda c: c.executed_at, reverse=True)
    return out
