"""GlossaryService: lookup centralizzato dei termini finanziari (Rule 34).

Carica `shared/glossary/terms.yaml` una volta sola in memoria e fornisce
accesso O(1) ai termini per chiave o sinonimo. Tollera l'assenza di campi
opzionali e l'assenza dello stesso file YAML (ritorna entry stub).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import yaml

__version__ = "7.1.0"

__all__ = ["GlossaryEntry", "GlossaryService", "get_glossary"]

# Percorso del file glossario rispetto alla root del progetto.
_GLOSSARY_FILE = Path(__file__).resolve().parent / "terms.yaml"


@dataclass(frozen=True, slots=True)
class GlossaryEntry:
    """Singola voce del glossario finanziario.

    All fields except ``term``, ``full_name``, ``category`` and ``description``
    are optional and may be empty. The dataclass is frozen so callers cannot
    accidentally mutate the cached entry.
    """

    term: str
    full_name: str
    category: str
    description: str
    interpretation: str = ""
    typical_range: str = ""
    formula: str = ""
    unit: str = ""
    synonyms: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def short_label(self) -> str:
        """Rende 'TERM · Full Name' per intestazioni di MetricCard."""
        return f"{self.term} · {self.full_name}"

    def tooltip_text(self, *, level: str = "intermediate") -> str:
        """Genera testo tooltip adattato al livello utente.

        Args:
            level: "beginner" | "intermediate" | "expert".
                Beginner -> sola descrizione.
                Intermediate -> descrizione + interpretazione + range.
                Expert -> tutto incl. formula e warnings.
        """
        parts: list[str] = [self.description]
        if level in {"intermediate", "expert"}:
            if self.interpretation:
                parts.append(f"\n\n**Interpretazione:** {self.interpretation}")
            if self.typical_range:
                parts.append(f"\n\n**Range tipico:** {self.typical_range}")
        if level == "expert":
            if self.formula:
                parts.append(f"\n\n**Formula:** `{self.formula}`")
            for warn in self.warnings:
                parts.append(f"\n\n⚠️ {warn}")
        return "".join(parts)


class GlossaryService:
    """Singleton-friendly servizio glossario.

    Use :func:`get_glossary` to obtain the shared instance.
    """

    _instance: ClassVar["GlossaryService | None"] = None

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _GLOSSARY_FILE
        self._terms: dict[str, GlossaryEntry] = {}
        self._load()

    # ------------------------------------------------------------------ load
    def _load(self) -> None:
        """Legge il file YAML e popola la mappa dei termini.

        Tollerante: se il file manca, il servizio resta vuoto e gli accessi
        ritornano entry stub. Questo permette al servizio di non bloccare
        l'avvio dell'app se il file viene rimosso accidentalmente.
        """
        if not self._path.exists():
            return
        try:
            raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError):
            return
        for entry_dict in raw.get("terms", []):
            entry = GlossaryEntry(
                term=str(entry_dict.get("term", "")).strip(),
                full_name=str(entry_dict.get("full_name", "")).strip(),
                category=str(entry_dict.get("category", "concept")).strip(),
                description=str(entry_dict.get("description", "")).strip(),
                interpretation=str(entry_dict.get("interpretation", "")).strip(),
                typical_range=str(entry_dict.get("typical_range", "")).strip(),
                formula=str(entry_dict.get("formula", "")).strip(),
                unit=str(entry_dict.get("unit", "")).strip(),
                synonyms=tuple(entry_dict.get("synonyms", []) or []),
                warnings=tuple(entry_dict.get("warnings", []) or []),
            )
            if not entry.term:
                continue
            key = entry.term.upper()
            self._terms[key] = entry
            # Registra anche i sinonimi come alias verso la stessa entry.
            for synonym in entry.synonyms:
                self._terms[synonym.upper()] = entry

    # ------------------------------------------------------------------ api
    def get(self, term: str) -> GlossaryEntry | None:
        """Ritorna la GlossaryEntry o None se il termine non e' definito."""
        if not term:
            return None
        return self._terms.get(term.strip().upper())

    def get_or_stub(self, term: str) -> GlossaryEntry:
        """Ritorna la entry o uno stub minimale se il termine manca.

        Garantisce che le UI possano sempre disporre di una entry leggibile.
        """
        existing = self.get(term)
        if existing is not None:
            return existing
        return GlossaryEntry(
            term=term,
            full_name=term,
            category="concept",
            description="Termine non ancora definito nel glossario.",
        )

    def all_terms(self) -> list[GlossaryEntry]:
        """Lista univoca di tutte le entry (deduplicata sui sinonimi)."""
        seen: set[str] = set()
        out: list[GlossaryEntry] = []
        for entry in self._terms.values():
            if entry.term in seen:
                continue
            seen.add(entry.term)
            out.append(entry)
        return out

    def has(self, term: str) -> bool:
        """True se il termine e' presente."""
        return self.get(term) is not None


def get_glossary() -> GlossaryService:
    """Singleton accessor con lazy initialization."""
    if GlossaryService._instance is None:
        GlossaryService._instance = GlossaryService()
    return GlossaryService._instance
