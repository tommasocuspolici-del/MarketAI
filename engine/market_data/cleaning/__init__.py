"""Data cleaning package (Rule 14).

Every raw DataFrame must traverse this package BEFORE Pandera validation
and DuckDB write. The orchestrator is :class:`DataCleaner`; helper modules
implement the individual transforms.
"""
from __future__ import annotations

from engine.market_data.cleaning.data_cleaner import CleaningResult, DataCleaner

__version__ = "6.0.0"

__all__ = ["CleaningResult", "DataCleaner"]
