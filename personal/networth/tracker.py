"""Net Worth tracker — assets - liabilities + periodic snapshots."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from shared.db.sqlite_client import SQLiteClient, get_sqlite_client
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = [
    "Asset",
    "AssetType",
    "Liability",
    "NetWorthSnapshot",
    "NetWorthTracker",
]

log = get_logger(__name__)


class AssetType(StrEnum):
    """Asset categories tracked in net worth."""

    CASH = "cash"
    EQUITY = "equity"
    BONDS = "bonds"
    REAL_ESTATE = "real_estate"
    CRYPTO = "crypto"
    OTHER = "other"


class Asset(BaseModel):
    """An owned asset contributing to net worth."""

    model_config = ConfigDict(str_strip_whitespace=True)

    asset_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    profile_id: str
    asset_type: AssetType
    name: str
    current_value: float = Field(ge=0)
    currency: str = "EUR"


class Liability(BaseModel):
    """A liability subtracted from net worth (mortgage, loan, etc.)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    liability_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    profile_id: str
    name: str
    current_balance: float = Field(ge=0)
    currency: str = "EUR"


@dataclass(frozen=True, slots=True)
class NetWorthSnapshot:
    """Snapshot of net worth at a point in time."""

    profile_id: str
    captured_at: datetime
    total_assets: float
    total_liabilities: float
    net_worth: float
    currency: str
    breakdown: dict[str, float]   # asset_type → value

    @property
    def is_positive(self) -> bool:
        return self.net_worth > 0


class NetWorthTracker:
    """CRUD for assets/liabilities + snapshot computation."""

    def __init__(self, client: SQLiteClient | None = None) -> None:
        self._client = client or get_sqlite_client()

    # ─── Assets CRUD ────────────────────────────────────────────────────
    def add_asset(self, asset: Asset) -> str:
        """Insert an asset record. Returns the asset_id."""
        with self._client.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO assets (
                        asset_id, profile_id, asset_type, name,
                        current_value, currency, last_updated
                    ) VALUES (
                        :asset_id, :profile_id, :asset_type, :name,
                        :current_value, :currency, :last_updated
                    )
                    """
                ),
                {
                    "asset_id": asset.asset_id,
                    "profile_id": asset.profile_id,
                    "asset_type": asset.asset_type.value,
                    "name": asset.name,
                    "current_value": asset.current_value,
                    "currency": asset.currency,
                    "last_updated": datetime.now(UTC),
                },
            )
        return asset.asset_id

    def list_assets(self, profile_id: str) -> list[Asset]:
        """Return all assets for a profile."""
        with self._client.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM assets WHERE profile_id = :pid"),
                {"pid": profile_id},
            ).mappings().all()

        return [
            Asset(
                asset_id=str(r["asset_id"]),
                profile_id=str(r["profile_id"]),
                asset_type=AssetType(r["asset_type"]),
                name=str(r["name"]),
                current_value=float(r["current_value"]),
                currency=str(r["currency"]),
            )
            for r in rows
        ]

    # ─── Liabilities CRUD ───────────────────────────────────────────────
    def add_liability(self, liability: Liability) -> str:
        """Insert a liability record. Returns the liability_id."""
        with self._client.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO liabilities (
                        liability_id, profile_id, name, current_balance,
                        currency, last_updated
                    ) VALUES (
                        :liability_id, :profile_id, :name, :current_balance,
                        :currency, :last_updated
                    )
                    """
                ),
                {
                    "liability_id": liability.liability_id,
                    "profile_id": liability.profile_id,
                    "name": liability.name,
                    "current_balance": liability.current_balance,
                    "currency": liability.currency,
                    "last_updated": datetime.now(UTC),
                },
            )
        return liability.liability_id

    def list_liabilities(self, profile_id: str) -> list[Liability]:
        """Return all liabilities for a profile."""
        with self._client.engine.connect() as conn:
            rows = conn.execute(
                text("SELECT * FROM liabilities WHERE profile_id = :pid"),
                {"pid": profile_id},
            ).mappings().all()

        return [
            Liability(
                liability_id=str(r["liability_id"]),
                profile_id=str(r["profile_id"]),
                name=str(r["name"]),
                current_balance=float(r["current_balance"]),
                currency=str(r["currency"]),
            )
            for r in rows
        ]

    # ─── Snapshots ──────────────────────────────────────────────────────
    def compute_current_snapshot(
        self, profile_id: str, currency: str = "EUR"
    ) -> NetWorthSnapshot:
        """Compute the current net worth snapshot (assets - liabilities)."""
        assets = self.list_assets(profile_id)
        liabs = self.list_liabilities(profile_id)

        total_assets = sum(a.current_value for a in assets)
        total_liabs = sum(liab.current_balance for liab in liabs)
        net = total_assets - total_liabs

        # Breakdown per asset_type
        breakdown: dict[str, float] = {}
        for asset in assets:
            key = asset.asset_type.value
            breakdown[key] = breakdown.get(key, 0.0) + asset.current_value

        return NetWorthSnapshot(
            profile_id=profile_id,
            captured_at=datetime.now(UTC),
            total_assets=float(total_assets),
            total_liabilities=float(total_liabs),
            net_worth=float(net),
            currency=currency,
            breakdown=breakdown,
        )

    def save_snapshot(self, snapshot: NetWorthSnapshot) -> str:
        """Persist a snapshot to the wealth_snapshots table."""
        snapshot_id = str(uuid.uuid4())
        with self._client.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO wealth_snapshots (
                        snapshot_id, profile_id, captured_at,
                        total_assets, total_liabilities, net_worth,
                        currency, breakdown_json
                    ) VALUES (
                        :sid, :pid, :captured_at,
                        :ta, :tl, :nw,
                        :currency, :bd
                    )
                    """
                ),
                {
                    "sid": snapshot_id,
                    "pid": snapshot.profile_id,
                    "captured_at": snapshot.captured_at,
                    "ta": snapshot.total_assets,
                    "tl": snapshot.total_liabilities,
                    "nw": snapshot.net_worth,
                    "currency": snapshot.currency,
                    "bd": json.dumps(snapshot.breakdown),
                },
            )
        log.info(
            "networth.snapshot_saved",
            profile_id=snapshot.profile_id,
            net_worth=snapshot.net_worth,
        )
        return snapshot_id

    def list_snapshots(self, profile_id: str, limit: int = 50) -> list[NetWorthSnapshot]:
        """Return historical snapshots ordered by date desc."""
        with self._client.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT * FROM wealth_snapshots
                    WHERE profile_id = :pid
                    ORDER BY captured_at DESC
                    LIMIT :limit
                    """
                ),
                {"pid": profile_id, "limit": limit},
            ).mappings().all()

        return [
            NetWorthSnapshot(
                profile_id=str(r["profile_id"]),
                captured_at=(
                    r["captured_at"]
                    if isinstance(r["captured_at"], datetime)
                    else datetime.fromisoformat(str(r["captured_at"]))
                ),
                total_assets=float(r["total_assets"]),
                total_liabilities=float(r["total_liabilities"]),
                net_worth=float(r["net_worth"]),
                currency=str(r["currency"]),
                breakdown=json.loads(str(r["breakdown_json"])),
            )
            for r in rows
        ]
