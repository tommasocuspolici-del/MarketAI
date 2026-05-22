"""Data Universe package — Convenzione 38.

Fonte di verità per tutte le serie dati, vintage management,
publication lag registry e audit logging.
"""
from __future__ import annotations

from engine.data_universe.audit_logger import AuditLogger
from engine.data_universe.lag_registry import LagRegistry
from engine.data_universe.universe_loader import DataUniverse, SeriesDefinition, UniverseLoader
from engine.data_universe.vintage_manager import VintageManager

__all__ = [
    "AuditLogger",
    "DataUniverse",
    "LagRegistry",
    "SeriesDefinition",
    "UniverseLoader",
    "VintageManager",
]
