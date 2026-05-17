"""Editor di asset e passivita' del patrimonio (Rule 41).

Risolve "non posso modificare il valore del portafoglio" della v6.
Persiste asset e liabilities su UserDataStore. Il patrimonio netto
e' calcolato come somma_asset - somma_liabilities.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from personal.data_entry.user_data_store import (
    UserDataStore,
    get_default_store,
    new_id,
)

__version__ = "7.2.0"

__all__ = [
    "Asset",
    "AssetType",
    "Liability",
    "LiabilityType",
    "delete_asset",
    "delete_liability",
    "list_assets",
    "list_liabilities",
    "net_worth_summary",
    "new_id",
    "save_asset",
    "save_liability",
]

ASSET_TYPE = "asset"
LIABILITY_TYPE = "liability"


class AssetType(str, Enum):
    """Categorie di asset patrimoniali."""

    CHECKING = "CONTO_CORRENTE"
    SAVINGS = "CONTO_DEPOSITO"
    INVESTMENT = "PORTAFOGLIO_INVESTIMENTO"
    REAL_ESTATE = "IMMOBILE"
    CRYPTO = "CRYPTO"
    PENSION = "FONDO_PENSIONE"
    INSURANCE = "POLIZZA"
    OTHER = "ALTRO"


class LiabilityType(str, Enum):
    """Categorie di passivita'."""

    MORTGAGE = "MUTUO"
    LOAN = "PRESTITO_PERSONALE"
    CREDIT_CARD = "CARTA_CREDITO"
    OTHER = "ALTRO"


class Asset(BaseModel):
    """Asset patrimoniale modificabile."""

    model_config = ConfigDict(str_strip_whitespace=True)

    asset_id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1, max_length=120)
    asset_type: AssetType = AssetType.OTHER
    value: float = Field(gt=0)
    currency: str = "EUR"
    valuation_date: date = Field(default_factory=date.today)
    is_liquid: bool = True
    notes: str = ""

    @field_validator("currency")
    @classmethod
    def _ccy_upper(cls, v: str) -> str:
        return v.strip().upper()

    def to_payload(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "asset_type": self.asset_type.value,
            "value": self.value,
            "currency": self.currency,
            "valuation_date": self.valuation_date.isoformat(),
            "is_liquid": self.is_liquid,
            "notes": self.notes,
            "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Asset":
        data = dict(payload)
        if isinstance(data.get("valuation_date"), str):
            data["valuation_date"] = date.fromisoformat(data["valuation_date"])
        return cls.model_validate(data)


class Liability(BaseModel):
    """Passivita' modificabile."""

    model_config = ConfigDict(str_strip_whitespace=True)

    liability_id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1, max_length=120)
    liability_type: LiabilityType = LiabilityType.OTHER
    outstanding_amount: float = Field(gt=0)
    monthly_payment: float | None = Field(default=None, ge=0)
    end_date: date | None = None
    interest_rate_pct: float | None = Field(default=None, ge=0)
    currency: str = "EUR"
    notes: str = ""

    @field_validator("currency")
    @classmethod
    def _ccy_upper(cls, v: str) -> str:
        return v.strip().upper()

    def to_payload(self) -> dict[str, Any]:
        return {
            "liability_id": self.liability_id,
            "name": self.name,
            "liability_type": self.liability_type.value,
            "outstanding_amount": self.outstanding_amount,
            "monthly_payment": self.monthly_payment,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "interest_rate_pct": self.interest_rate_pct,
            "currency": self.currency,
            "notes": self.notes,
            "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Liability":
        data = dict(payload)
        if isinstance(data.get("end_date"), str):
            data["end_date"] = date.fromisoformat(data["end_date"])
        return cls.model_validate(data)


# ─────────────────────────────────────────────── persistence
def list_assets(store: UserDataStore | None = None) -> list[Asset]:
    """Tutti gli asset salvati."""
    s = store or get_default_store()
    out: list[Asset] = []
    for r in s.list_by_type(ASSET_TYPE):
        try:
            out.append(Asset.from_payload(r.payload))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def list_liabilities(store: UserDataStore | None = None) -> list[Liability]:
    """Tutte le passivita' salvate."""
    s = store or get_default_store()
    out: list[Liability] = []
    for r in s.list_by_type(LIABILITY_TYPE):
        try:
            out.append(Liability.from_payload(r.payload))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def save_asset(asset: Asset, store: UserDataStore | None = None) -> None:
    s = store or get_default_store()
    s.upsert(ASSET_TYPE, asset.asset_id, asset.to_payload())


def save_liability(
    liability: Liability, store: UserDataStore | None = None
) -> None:
    s = store or get_default_store()
    s.upsert(LIABILITY_TYPE, liability.liability_id, liability.to_payload())


def delete_asset(asset_id: str, store: UserDataStore | None = None) -> bool:
    s = store or get_default_store()
    return s.delete(ASSET_TYPE, asset_id)


def delete_liability(
    liability_id: str, store: UserDataStore | None = None
) -> bool:
    s = store or get_default_store()
    return s.delete(LIABILITY_TYPE, liability_id)


def net_worth_summary(
    store: UserDataStore | None = None,
) -> dict[str, float]:
    """Calcola riepilogo patrimoniale corrente (in EUR, no FX conversion).

    Per semplicita' assume tutti i valori in EUR. Conversione cross-currency
    sara' aggiunta in fase successiva via shared/fx_service.py.

    Returns:
        dict con 'total_assets', 'total_liabilities', 'net_worth',
        'liquid_assets'.
    """
    assets = list_assets(store)
    liabilities = list_liabilities(store)

    total_assets = sum(a.value for a in assets)
    liquid_assets = sum(a.value for a in assets if a.is_liquid)
    total_liabilities = sum(l.outstanding_amount for l in liabilities)

    return {
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "net_worth": total_assets - total_liabilities,
        "liquid_assets": liquid_assets,
        "n_assets": float(len(assets)),
        "n_liabilities": float(len(liabilities)),
    }


