"""Factory per ManualOverrideStore — punto di cablaggio bridge tra personal/ e engine/.

Regola 28: engine/ non importa da personal/. Il bridge è il solo layer autorizzato
a istanziare ManualOverrideStore e iniettarlo nel LiveMarketService via Protocol.
"""
from __future__ import annotations

from personal.data_entry.override_store import ManualOverrideStore

__all__ = ["get_default_override_store"]


def get_default_override_store() -> ManualOverrideStore:
    """Restituisce un'istanza di ManualOverrideStore con il DB SQLite di default."""
    return ManualOverrideStore()
