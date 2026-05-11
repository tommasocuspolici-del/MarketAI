"""Financial goal model — SMART goals (Specific, Measurable, Achievable,
Relevant, Time-bound).

Goals are stored in SQLite (table ``financial_goals``) and tracked over
time by ``ProgressCalculator``.
"""
from __future__ import annotations

import uuid
from datetime import date
from enum import Enum, StrEnum

from pydantic import BaseModel, ConfigDict, Field

__version__ = "6.0.0"

__all__ = ["Goal", "GoalPriority", "GoalStatus"]


class GoalStatus(StrEnum):
    """Lifecycle states for a financial goal."""

    ACTIVE = "active"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"
    PAUSED = "paused"


class GoalPriority(int, Enum):
    """Goal priority — used to break ties when allocating savings."""

    LOW = 1
    MEDIUM_LOW = 2
    MEDIUM = 3
    MEDIUM_HIGH = 4
    HIGH = 5


class Goal(BaseModel):
    """A SMART financial goal."""

    model_config = ConfigDict(str_strip_whitespace=True)

    goal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    profile_id: str
    name: str
    description: str | None = None

    # Financial target (Measurable)
    target_amount: float = Field(gt=0)
    currency: str = "EUR"
    current_amount: float = Field(default=0.0, ge=0)

    # Time-bound
    target_date: date

    # Priority
    priority: GoalPriority = GoalPriority.MEDIUM

    # Lifecycle
    status: GoalStatus = GoalStatus.ACTIVE

    @property
    def progress_pct(self) -> float:
        """Fraction of target reached, in [0, 1+]."""
        if self.target_amount <= 0:
            return 0.0
        return min(self.current_amount / self.target_amount, 1.5)

    @property
    def remaining_amount(self) -> float:
        """Amount still missing (>=0)."""
        return max(self.target_amount - self.current_amount, 0.0)

    @property
    def is_achieved(self) -> bool:
        """True if current_amount >= target_amount."""
        return self.current_amount >= self.target_amount

    @property
    def days_to_target(self) -> int:
        """Days until target_date (negative if past due)."""
        return (self.target_date - date.today()).days
