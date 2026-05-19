"""Compatibility shim — SanityCheckerV2 re-esportato da engine.market_data.sanity_checker.

Il modulo engine.market_data.sanity_checker contiene già la classe SanityCheckerV2
(l'implementazione avanzata della Settimana 9). Questo file garantisce che il path
canonico ``engine.market_data.sanity_checker_v2`` funzioni per i test e il codice
legacy senza duplicare la logica.

Fare riferimento a sanity_checker.py per la documentazione completa.
"""
from __future__ import annotations

from engine.market_data.sanity_checker import SanityCheckerV2, SanityResult  # noqa: F401

__version__ = "1.0.0"
__all__ = ["SanityCheckerV2", "SanityResult"]
