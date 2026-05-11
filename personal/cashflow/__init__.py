"""Cash flow sub-package — entries CRUD + projection."""
from __future__ import annotations

from personal.cashflow.engine import CashFlowEngine
from personal.cashflow.entry_model import CashFlowDirection, CashFlowEntry
from personal.cashflow.projector import CashFlowProjection, CashFlowProjector

__version__ = "6.0.0"

__all__ = [
    "CashFlowDirection",
    "CashFlowEngine",
    "CashFlowEntry",
    "CashFlowProjection",
    "CashFlowProjector",
]
