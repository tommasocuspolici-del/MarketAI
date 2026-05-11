"""Cash flow projector — 12-month forward projection from historical data.

Aggregates historical entries by category and projects forward with
simple persistence rules (recurring entries continue, one-off don't).
Numpy-based aggregation (Rule 8).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from personal.cashflow.engine import CashFlowEngine
from personal.cashflow.entry_model import CashFlowDirection
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["CashFlowProjection", "CashFlowProjector"]

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CashFlowProjection:
    """Projected monthly cash flow for the next N months."""

    profile_id: str
    months_ahead: int
    monthly_income: np.ndarray      # Shape (months_ahead,)
    monthly_expense: np.ndarray
    monthly_net: np.ndarray
    cumulative_net: np.ndarray
    avg_monthly_savings: float


class CashFlowProjector:
    """Project cash flows forward based on recurring history."""

    def __init__(self, engine: CashFlowEngine | None = None) -> None:
        self._engine = engine or CashFlowEngine()

    def project(
        self,
        profile_id: str,
        months_ahead: int = 12,
        history_months: int = 12,
        today: date | None = None,
    ) -> CashFlowProjection:
        """Compute a forward projection of cash flows.

        Method:
          1. Pull last ``history_months`` of entries
          2. Filter to recurring + average non-recurring monthly impact
          3. Generate synthetic future months replicating recurring +
             diluted non-recurring as monthly average

        Args:
            profile_id: Investor profile.
            months_ahead: Future horizon in months.
            history_months: How many past months to base projection on.
            today: Override "now" for tests.
        """
        today = today or date.today()
        start_date = today - timedelta(days=history_months * 31)

        entries = self._engine.list_entries(
            profile_id=profile_id,
            start_date=start_date,
            end_date=today,
        )
        if not entries:
            log.warning("cashflow_projector.no_history", profile_id=profile_id)
            zeros = np.zeros(months_ahead, dtype="float64")
            return CashFlowProjection(
                profile_id=profile_id,
                months_ahead=months_ahead,
                monthly_income=zeros,
                monthly_expense=zeros,
                monthly_net=zeros,
                cumulative_net=zeros,
                avg_monthly_savings=0.0,
            )

        # Categorizza: recurring vs one-off
        recurring_in = sum(
            e.amount for e in entries
            if e.is_recurring and e.direction == CashFlowDirection.IN
        )
        recurring_out = sum(
            e.amount for e in entries
            if e.is_recurring and e.direction == CashFlowDirection.OUT
        )
        one_off_in = sum(
            e.amount for e in entries
            if not e.is_recurring and e.direction == CashFlowDirection.IN
        )
        one_off_out = sum(
            e.amount for e in entries
            if not e.is_recurring and e.direction == CashFlowDirection.OUT
        )

        # Recurring assumed to repeat at same monthly cadence, so divide by
        # number of months observed. One-off averaged into a flat monthly cost.
        # Heuristic semplificata: una entry "recurring" rilevata in N mesi
        # rappresenta N occorrenze → media mensile = total / history_months.
        avg_in = (recurring_in + one_off_in) / history_months
        avg_out = (recurring_out + one_off_out) / history_months

        # Numpy projection (Rule 8)
        monthly_income = np.full(months_ahead, avg_in, dtype="float64")
        monthly_expense = np.full(months_ahead, avg_out, dtype="float64")
        monthly_net = monthly_income - monthly_expense
        cumulative_net = np.cumsum(monthly_net)

        log.info(
            "cashflow_projector.projected",
            profile_id=profile_id,
            months_ahead=months_ahead,
            avg_savings=round(float(monthly_net.mean()), 2),
        )

        return CashFlowProjection(
            profile_id=profile_id,
            months_ahead=months_ahead,
            monthly_income=monthly_income,
            monthly_expense=monthly_expense,
            monthly_net=monthly_net,
            cumulative_net=cumulative_net,
            avg_monthly_savings=float(monthly_net.mean()),
        )
