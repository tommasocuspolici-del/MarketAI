"""Financial goals sub-package — SMART goal CRUD + progress."""
from __future__ import annotations

from personal.goals.goal_manager import GoalManager
from personal.goals.goal_model import Goal, GoalPriority, GoalStatus
from personal.goals.progress_calculator import (
    FeasibilityResult,
    GoalProgress,
    ProgressCalculator,
)

__version__ = "6.0.0"

__all__ = [
    "FeasibilityResult",
    "Goal",
    "GoalManager",
    "GoalPriority",
    "GoalProgress",
    "GoalStatus",
    "ProgressCalculator",
]
