"""Cash flow engine — CRUD + aggregation over SQLite ``cash_flow_entries``."""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import text

from personal.cashflow.entry_model import CashFlowDirection, CashFlowEntry
from shared.db.sqlite_client import SQLiteClient, get_sqlite_client
from shared.exceptions import PersonalError
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["CashFlowEngine"]

log = get_logger(__name__)


class CashFlowEngine:
    """CRUD on cash_flow_entries + aggregation queries."""

    def __init__(self, client: SQLiteClient | None = None) -> None:
        self._client = client or get_sqlite_client()

    # ─── Write ──────────────────────────────────────────────────────────
    def add_entry(self, entry: CashFlowEntry) -> str:
        """Insert a new cash flow entry. Returns the entry_id."""
        with self._client.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO cash_flow_entries (
                        entry_id, profile_id, occurred_at, direction,
                        category, subcategory, amount, currency,
                        description, is_recurring, created_at
                    ) VALUES (
                        :entry_id, :profile_id, :occurred_at, :direction,
                        :category, :subcategory, :amount, :currency,
                        :description, :is_recurring, :created_at
                    )
                    """
                ),
                {
                    "entry_id": entry.entry_id,
                    "profile_id": entry.profile_id,
                    "occurred_at": entry.occurred_at,
                    "direction": entry.direction.value,
                    "category": entry.category,
                    "subcategory": entry.subcategory,
                    "amount": entry.amount,
                    "currency": entry.currency,
                    "description": entry.description,
                    "is_recurring": entry.is_recurring,
                    "created_at": datetime.now(UTC),
                },
            )
        log.info(
            "cashflow.entry_added",
            profile_id=entry.profile_id,
            direction=entry.direction.value,
            amount=entry.amount,
        )
        return entry.entry_id

    def delete_entry(self, entry_id: str) -> None:
        """Delete an entry by ID. No-op if not found."""
        with self._client.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM cash_flow_entries WHERE entry_id = :eid"),
                {"eid": entry_id},
            )

    # ─── Read ───────────────────────────────────────────────────────────
    def list_entries(
        self,
        profile_id: str,
        start_date: date | None = None,
        end_date: date | None = None,
        direction: CashFlowDirection | None = None,
    ) -> list[CashFlowEntry]:
        """List entries with optional filters."""
        sql = "SELECT * FROM cash_flow_entries WHERE profile_id = :pid"
        params: dict[str, object] = {"pid": profile_id}
        if start_date is not None:
            sql += " AND occurred_at >= :start_date"
            params["start_date"] = start_date
        if end_date is not None:
            sql += " AND occurred_at <= :end_date"
            params["end_date"] = end_date
        if direction is not None:
            sql += " AND direction = :direction"
            params["direction"] = direction.value
        sql += " ORDER BY occurred_at DESC"

        with self._client.engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()

        return [self._row_to_entry(dict(r)) for r in rows]

    def monthly_summary(
        self,
        profile_id: str,
        year: int,
        month: int,
    ) -> dict[str, float]:
        """Compute total in/out/net for a given month."""
        if not 2000 <= year <= 2100:
            raise PersonalError(f"year out of range: {year}")
        if not 1 <= month <= 12:
            raise PersonalError(f"month out of range: {month}")

        # Calcolo intervallo del mese
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)

        with self._client.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT direction, SUM(amount) AS total
                    FROM cash_flow_entries
                    WHERE profile_id = :pid
                      AND occurred_at >= :start
                      AND occurred_at < :end
                    GROUP BY direction
                    """
                ),
                {"pid": profile_id, "start": start, "end": end},
            ).all()

        totals = {"in": 0.0, "out": 0.0}
        for row in rows:
            totals[row[0]] = float(row[1] or 0.0)

        return {
            "income": totals["in"],
            "expense": totals["out"],
            "net": totals["in"] - totals["out"],
        }

    # ─── Helpers ────────────────────────────────────────────────────────
    @staticmethod
    def _row_to_entry(row: dict[str, object]) -> CashFlowEntry:
        return CashFlowEntry(
            entry_id=str(row["entry_id"]),
            profile_id=str(row["profile_id"]),
            occurred_at=(
                row["occurred_at"]
                if isinstance(row["occurred_at"], date)
                else date.fromisoformat(str(row["occurred_at"]))
            ),
            direction=CashFlowDirection(str(row["direction"])),
            category=str(row["category"]),
            subcategory=str(row["subcategory"]) if row.get("subcategory") else None,
            amount=float(row["amount"]),  # type: ignore[arg-type]
            currency=str(row["currency"]),
            description=str(row["description"]) if row.get("description") else None,
            is_recurring=bool(row.get("is_recurring", False)),
        )
