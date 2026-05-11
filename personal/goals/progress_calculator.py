"""Progress and feasibility calculator for SMART financial goals."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

import numpy as np

from shared.logger import get_logger

if TYPE_CHECKING:
    from personal.goals.goal_model import Goal

__version__ = "6.0.0"

__all__ = ["FeasibilityResult", "GoalProgress", "ProgressCalculator"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GoalProgress:
    """Snapshot of a goal's progress at a point in time."""

    goal_id: str
    progress_pct: float           # 0..1+
    remaining_amount: float
    days_remaining: int
    months_remaining: int
    required_monthly_savings: float   # To reach target by date
    on_track: bool


@dataclass(frozen=True, slots=True)
class FeasibilityResult:
    """Outcome of a goal feasibility check.

    A goal is feasible if the user's current savings rate + expected
    investment returns can plausibly reach the target by the target date.
    """

    goal_id: str
    is_feasible: bool
    required_monthly_savings: float
    available_monthly_savings: float
    shortfall_per_month: float        # >0 if infeasible
    suggested_extension_months: int   # Months to add to make feasible


class ProgressCalculator:
    """Compute progress + feasibility for SMART goals (Rule 8: numpy)."""

    def compute_progress(
        self,
        goal: Goal,
        annual_return: float = 0.05,
        today: date | None = None,
    ) -> GoalProgress:
        """Compute progress including required monthly savings.

        Args:
            goal: The goal to evaluate.
            annual_return: Expected annual return on the saved capital.
            today: Override for tests.
        """
        today = today or date.today()
        days_remaining = max((goal.target_date - today).days, 0)
        months_remaining = max(days_remaining // 30, 0)

        # Required monthly savings (PMT formula vettorizzata):
        # FV = PMT * [(1+r)^n - 1] / r  →  PMT = FV * r / [(1+r)^n - 1]
        if months_remaining > 0:
            r = annual_return / 12.0
            n = months_remaining
            target_remaining = goal.remaining_amount
            if r > 0:
                # Future value formula: necessitiamo del FV che, con i contributi
                # mensili pmt e capitale iniziale current_amount, raggiunga target.
                # FV = current * (1+r)^n + pmt * [(1+r)^n - 1] / r = target
                growth = float(np.power(1.0 + r, n))
                fv_capital = goal.current_amount * growth
                fv_needed = goal.target_amount - fv_capital
                annuity_factor = (growth - 1.0) / r
                required_pmt = (
                    fv_needed / annuity_factor if annuity_factor > 0 else target_remaining / n
                )
            else:
                required_pmt = target_remaining / n
            required_pmt = max(required_pmt, 0.0)
        else:
            required_pmt = 0.0

        # On track se progress_pct ≥ percentuale tempo trascorso
        elapsed_total = max((goal.target_date - today).days + 1, 1)
        on_track = goal.progress_pct >= 1.0 - (days_remaining / elapsed_total)

        return GoalProgress(
            goal_id=goal.goal_id,
            progress_pct=goal.progress_pct,
            remaining_amount=goal.remaining_amount,
            days_remaining=days_remaining,
            months_remaining=months_remaining,
            required_monthly_savings=float(required_pmt),
            on_track=bool(on_track),
        )

    def check_feasibility(
        self,
        goal: Goal,
        available_monthly_savings: float,
        annual_return: float = 0.05,
        today: date | None = None,
    ) -> FeasibilityResult:
        """Verify if goal is reachable with available savings rate."""
        progress = self.compute_progress(goal, annual_return=annual_return, today=today)
        required = progress.required_monthly_savings
        shortfall = max(required - available_monthly_savings, 0.0)
        is_feasible = shortfall <= 1e-6

        # Quanti mesi extra servirebbero per renderlo fattibile?
        suggested_ext = 0
        if not is_feasible and available_monthly_savings > 0:
            # Calcolo approssimato: aggiungiamo mesi finché PMT richiesto ≤ disponibile
            # Numpy-based: semplice loop max 60 mesi (Rule 8: piccolissimo, accettabile)
            r = annual_return / 12.0
            for extra in range(1, 60):
                n_total = progress.months_remaining + extra
                if n_total <= 0:
                    continue
                if r > 0:
                    growth = float(np.power(1.0 + r, n_total))
                    fv_capital = goal.current_amount * growth
                    fv_needed = goal.target_amount - fv_capital
                    annuity_factor = (growth - 1.0) / r
                    pmt = fv_needed / annuity_factor if annuity_factor > 0 else 0.0
                else:
                    pmt = goal.remaining_amount / n_total
                if pmt <= available_monthly_savings:
                    suggested_ext = extra
                    break

        log.info(
            "goal_feasibility.checked",
            goal_id=goal.goal_id,
            feasible=is_feasible,
            shortfall=round(shortfall, 2),
        )
        return FeasibilityResult(
            goal_id=goal.goal_id,
            is_feasible=is_feasible,
            required_monthly_savings=required,
            available_monthly_savings=available_monthly_savings,
            shortfall_per_month=shortfall,
            suggested_extension_months=suggested_ext,
        )
