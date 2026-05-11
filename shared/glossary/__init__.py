"""Glossary package — centralized financial terminology (Rule 34)."""
from __future__ import annotations

from shared.glossary.lookup import GlossaryEntry, GlossaryService, get_glossary

__version__ = "7.1.0"

__all__ = ["GlossaryEntry", "GlossaryService", "get_glossary"]
