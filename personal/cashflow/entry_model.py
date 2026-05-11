"""Cash flow data models — entries (income/expense)."""
from __future__ import annotations

import uuid
from datetime import date  # noqa: TC003 — required at runtime by Pydantic
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__version__ = "6.0.0"

__all__ = ["CashFlowDirection", "CashFlowEntry"]


class CashFlowDirection(StrEnum):
    """Sign of a cashflow entry."""

    IN = "in"      # Income
    OUT = "out"    # Expense


class CashFlowEntry(BaseModel):
    """A single cashflow record (income or expense)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    entry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    profile_id: str
    occurred_at: date
    direction: CashFlowDirection
    category: str
    subcategory: str | None = None
    amount: float = Field(gt=0)        # Sempre positivo; il segno è in `direction`
    currency: str = "EUR"
    description: str | None = None
    is_recurring: bool = False

    @property
    def signed_amount(self) -> float:
        """+amount if income, -amount if expense."""
        return self.amount if self.direction == CashFlowDirection.IN else -self.amount
