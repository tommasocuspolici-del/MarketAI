"""ProfileLoader — CRUD on the SQLite ``investor_profiles`` table.

Stateless helper layer over SQLAlchemy core. Single source of truth for
loading/saving InvestorProfile instances.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text

from personal.investor_profile.profile_model import InvestorProfile
from shared.db.sqlite_client import SQLiteClient, get_sqlite_client
from shared.exceptions import ProfileNotFoundError
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["ProfileLoader", "get_profile_loader", "reset_profile_loader"]

log = get_logger(__name__)


class ProfileLoader:
    """CRUD for investor profiles on SQLite."""

    def __init__(self, client: SQLiteClient | None = None) -> None:
        self._client = client or get_sqlite_client()

    # ─── Read ───────────────────────────────────────────────────────────
    def load(self, profile_id: str) -> InvestorProfile:
        """Load a profile by ID. Raises ProfileNotFoundError if missing."""
        with self._client.engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM investor_profiles WHERE profile_id = :pid"),
                {"pid": profile_id},
            ).mappings().first()

        if result is None:
            raise ProfileNotFoundError(
                f"InvestorProfile with id '{profile_id}' not found"
            )
        return InvestorProfile.from_db_row(dict(result))

    def list_all(self) -> list[InvestorProfile]:
        """Return all profiles ordered by name."""
        with self._client.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM investor_profiles ORDER BY name")
            ).mappings().all()
        return [InvestorProfile.from_db_row(dict(r)) for r in rows]

    def exists(self, profile_id: str) -> bool:
        """True if a profile with the given ID exists."""
        with self._client.engine.connect() as conn:
            n = conn.execute(
                text("SELECT COUNT(*) FROM investor_profiles WHERE profile_id = :pid"),
                {"pid": profile_id},
            ).scalar()
        return bool(n)

    # ─── Write ──────────────────────────────────────────────────────────
    def save(self, profile: InvestorProfile) -> None:
        """Insert or update a profile."""
        data = profile.to_db_dict()
        now = datetime.now(UTC)
        data["updated_at"] = now

        already_exists = self.exists(profile.profile_id)

        with self._client.engine.begin() as conn:
            if already_exists:
                # UPDATE — escludi profile_id dal SET
                set_clause = ", ".join(
                    f"{k} = :{k}" for k in data if k != "profile_id"
                )
                conn.execute(
                    text(
                        f"UPDATE investor_profiles SET {set_clause} "
                        f"WHERE profile_id = :profile_id"
                    ),
                    data,
                )
                log.info("profile.updated", profile_id=profile.profile_id)
            else:
                # INSERT
                data["created_at"] = now
                cols = ", ".join(data.keys())
                placeholders = ", ".join(f":{k}" for k in data)
                conn.execute(
                    text(
                        f"INSERT INTO investor_profiles ({cols}) "
                        f"VALUES ({placeholders})"
                    ),
                    data,
                )
                log.info("profile.created", profile_id=profile.profile_id)

    def delete(self, profile_id: str) -> None:
        """Delete a profile. No-op if not found."""
        with self._client.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM investor_profiles WHERE profile_id = :pid"),
                {"pid": profile_id},
            )
        log.info("profile.deleted", profile_id=profile_id)


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════
_INSTANCE: ProfileLoader | None = None


def get_profile_loader() -> ProfileLoader:
    """Return the process-wide ProfileLoader."""
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = ProfileLoader()
    return _INSTANCE


def reset_profile_loader() -> None:
    """Reset the singleton — for tests only."""
    global _INSTANCE
    _INSTANCE = None
