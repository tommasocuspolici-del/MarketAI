"""GoalManager — CRUD on the SQLite ``financial_goals`` table."""
from __future__ import annotations

from datetime import UTC, date, datetime
from typing import cast

from sqlalchemy import text

from personal.goals.goal_model import Goal, GoalPriority, GoalStatus
from shared.db.sqlite_client import SQLiteClient, get_sqlite_client
from shared.exceptions import GoalError
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["GoalManager"]

log = get_logger(__name__)


class GoalManager:
    """CRUD for financial goals on SQLite."""

    def __init__(self, client: SQLiteClient | None = None) -> None:
        self._client = client or get_sqlite_client()

    # ─── Read ───────────────────────────────────────────────────────────
    def get(self, goal_id: str) -> Goal:
        """Load a goal by ID. Raises GoalError if missing."""
        with self._client.engine.connect() as conn:
            row = conn.execute(
                text("SELECT * FROM financial_goals WHERE goal_id = :gid"),
                {"gid": goal_id},
            ).mappings().first()
        if row is None:
            raise GoalError(f"goal '{goal_id}' not found")
        return self._row_to_goal(dict(row))

    def list_for_profile(
        self,
        profile_id: str,
        status: GoalStatus | None = None,
    ) -> list[Goal]:
        """Return all goals for a profile, optionally filtered by status."""
        sql = "SELECT * FROM financial_goals WHERE profile_id = :pid"
        params: dict[str, object] = {"pid": profile_id}
        if status is not None:
            sql += " AND status = :status"
            params["status"] = status.value
        sql += " ORDER BY priority DESC, target_date ASC"

        with self._client.engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
        return [self._row_to_goal(dict(r)) for r in rows]

    # ─── Write ──────────────────────────────────────────────────────────
    def save(self, goal: Goal) -> str:
        """Insert or update a goal. Returns the goal_id."""
        now = datetime.now(UTC)
        exists = self._exists(goal.goal_id)

        data = {
            "goal_id": goal.goal_id,
            "profile_id": goal.profile_id,
            "name": goal.name,
            "description": goal.description,
            "target_amount": goal.target_amount,
            "currency": goal.currency,
            "target_date": goal.target_date,
            "current_amount": goal.current_amount,
            "priority": int(goal.priority),
            "status": goal.status.value,
            "updated_at": now,
        }

        with self._client.engine.begin() as conn:
            if exists:
                set_clause = ", ".join(f"{k} = :{k}" for k in data if k != "goal_id")
                conn.execute(
                    text(
                        f"UPDATE financial_goals SET {set_clause} "
                        f"WHERE goal_id = :goal_id"
                    ),
                    data,
                )
                log.info("goal.updated", goal_id=goal.goal_id)
            else:
                data["created_at"] = now
                cols = ", ".join(data.keys())
                placeholders = ", ".join(f":{k}" for k in data)
                conn.execute(
                    text(
                        f"INSERT INTO financial_goals ({cols}) VALUES ({placeholders})"
                    ),
                    data,
                )
                log.info("goal.created", goal_id=goal.goal_id)
        return goal.goal_id

    def update_progress(self, goal_id: str, current_amount: float) -> Goal:
        """Update current_amount on a goal and return the refreshed object."""
        if current_amount < 0:
            raise GoalError(f"current_amount must be >= 0, got {current_amount}")
        goal = self.get(goal_id)
        # Auto-promote ad ACHIEVED se raggiunto
        new_status = (
            GoalStatus.ACHIEVED
            if current_amount >= goal.target_amount
            else goal.status
        )
        # Pydantic frozen=False (default), ma costruiamo nuovo per chiarezza
        updated = goal.model_copy(
            update={"current_amount": current_amount, "status": new_status}
        )
        self.save(updated)
        return updated

    def delete(self, goal_id: str) -> None:
        """Delete a goal. No-op if not found."""
        with self._client.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM financial_goals WHERE goal_id = :gid"),
                {"gid": goal_id},
            )
        log.info("goal.deleted", goal_id=goal_id)

    # ─── Helpers ────────────────────────────────────────────────────────
    def _exists(self, goal_id: str) -> bool:
        with self._client.engine.connect() as conn:
            n = conn.execute(
                text("SELECT COUNT(*) FROM financial_goals WHERE goal_id = :gid"),
                {"gid": goal_id},
            ).scalar()
        return bool(n)

    @staticmethod
    def _row_to_goal(row: dict[str, object]) -> Goal:
        return Goal(
            goal_id=str(row["goal_id"]),
            profile_id=str(row["profile_id"]),
            name=str(row["name"]),
            description=str(row["description"]) if row.get("description") else None,
            target_amount=float(row["target_amount"]),  # type: ignore[arg-type]
            currency=str(row["currency"]),
            current_amount=float(row.get("current_amount") or 0.0),  # type: ignore[arg-type]
            target_date=(
                row["target_date"]
                if isinstance(row["target_date"], date)
                else date.fromisoformat(str(row["target_date"]))
            ),
            priority=GoalPriority(cast("int", row.get("priority") or 3)),
            status=GoalStatus(str(row.get("status", "active"))),
        )
