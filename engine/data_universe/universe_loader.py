"""Data Universe Loader — Convenzione 38.

Carica e valida config/data_universe.yaml come fonte di verità per le serie dati.
Espone DataUniverse con lookup per ID, categoria e statistiche aggregate.

Uso::

    from engine.data_universe.universe_loader import UniverseLoader

    universe = UniverseLoader().load()
    defn = universe.get("ICSA")           # SeriesDefinition | None
    labour = universe.by_category("labour")   # list[SeriesDefinition]
    print(universe.count())               # 90+
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from shared.logger import get_logger
from shared.exceptions import ConfigurationError

__version__ = "1.0.0"
__all__ = ["DataUniverse", "SeriesDefinition", "UniverseLoader"]

log = get_logger(__name__)

# Frequenze valide ammesse in data_universe.yaml
_VALID_FREQUENCIES = frozenset({"daily", "weekly", "monthly", "quarterly", "annual"})
# Frequenze di revisione valide
_VALID_REVISION_FREQS = frozenset({"none", "monthly", "quarterly", "annual"})


@dataclass(frozen=True, slots=True)
class SeriesDefinition:
    """Definizione di una singola serie dati nel Data Universe.

    Attributi:
        id: Codice identificativo (es. "ICSA", "DGS10").
        name: Descrizione leggibile della serie.
        frequency: Frequenza di pubblicazione (daily/weekly/monthly/quarterly/annual).
        publication_lag_days: Giorni tipici tra fine periodo e pubblicazione.
        revision_frequency: Frequenza delle revisioni (none/monthly/quarterly/annual).
        retention_years: Anni di storico da mantenere in DuckDB.
        category: Categoria tematica (labour/inflation/rates/growth/credit/...).
        source: Provider dei dati (default "fred").
    """

    id: str
    name: str
    frequency: str
    publication_lag_days: int
    revision_frequency: str
    retention_years: int
    category: str
    source: str = "fred"


@dataclass
class DataUniverse:
    """Catalogo completo delle serie dati del sistema MarketAI.

    Indicizzato per series_id per lookup O(1).
    """

    series: dict[str, SeriesDefinition] = field(default_factory=dict)

    def get(self, series_id: str) -> SeriesDefinition | None:
        """Restituisce la definizione della serie o None se non trovata.

        Args:
            series_id: Codice della serie (es. "ICSA").

        Returns:
            SeriesDefinition oppure None.
        """
        return self.series.get(series_id)

    def by_category(self, category: str) -> list[SeriesDefinition]:
        """Restituisce tutte le serie di una categoria specifica.

        Args:
            category: Nome della categoria (es. "labour", "inflation").

        Returns:
            Lista (eventualmente vuota) di SeriesDefinition.
        """
        return [s for s in self.series.values() if s.category == category]

    def all_ids(self) -> list[str]:
        """Restituisce tutti gli ID serie ordinati alfabeticamente."""
        return sorted(self.series.keys())

    def count(self) -> int:
        """Numero totale di serie nel catalogo."""
        return len(self.series)

    def categories(self) -> list[str]:
        """Restituisce le categorie distinte presenti nel catalogo."""
        return sorted({s.category for s in self.series.values()})


class UniverseLoader:
    """Carica config/data_universe.yaml e restituisce un DataUniverse validato.

    Supporta override del path per i test.

    Uso::

        universe = UniverseLoader().load()
        # oppure:
        universe = UniverseLoader(config_path=Path("/path/to/data_universe.yaml")).load()
    """

    _DEFAULT_PATH: Path = (
        Path(__file__).parent.parent.parent / "config" / "data_universe.yaml"
    )

    def __init__(self, config_path: Path | None = None) -> None:
        self._path: Path = config_path or self._DEFAULT_PATH

    def load(self) -> DataUniverse:
        """Carica e valida il YAML. Restituisce DataUniverse popolato.

        Returns:
            DataUniverse con tutte le serie indicizzate per ID.

        Raises:
            FileNotFoundError: Se il file YAML non esiste.
            ValueError: Se la struttura YAML è invalida.
        """
        if not self._path.exists():
            raise FileNotFoundError(
                f"data_universe.yaml non trovato: {self._path}"
            )

        raw: dict[str, Any] = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigurationError("data_universe.yaml deve essere un mapping YAML valido")

        universe = DataUniverse()
        fred_sections: dict[str, Any] = raw.get("fred_series", {})

        for category, sub in fred_sections.items():
            if not isinstance(sub, dict):
                log.warning("universe_loader.invalid_category", category=category)
                continue

            for group_key in ("existing", "new"):
                group: list[dict[str, Any]] = sub.get(group_key, []) or []
                for entry in group:
                    defn = self._parse_entry(entry, category=category)
                    if defn is None:
                        continue
                    if defn.id in universe.series:
                        log.warning(
                            "universe_loader.duplicate_id",
                            series_id=defn.id,
                            category=category,
                        )
                        continue
                    universe.series[defn.id] = defn

        log.info(
            "universe_loader.loaded",
            total_series=universe.count(),
            categories=universe.categories(),
        )
        return universe

    # ─── Private helpers ──────────────────────────────────────────────────

    def _parse_entry(
        self,
        entry: dict[str, Any],
        *,
        category: str,
    ) -> SeriesDefinition | None:
        """Valida e costruisce un SeriesDefinition da un dict YAML.

        Args:
            entry: Dizionario con i campi della serie.
            category: Categoria tematica di appartenenza.

        Returns:
            SeriesDefinition validato oppure None se malformato.
        """
        required_fields = ("id", "name", "frequency", "publication_lag_days",
                           "revision_frequency", "retention_years")
        for field_name in required_fields:
            if field_name not in entry:
                log.warning(
                    "universe_loader.missing_field",
                    field=field_name,
                    entry=entry.get("id", "<unknown>"),
                )
                return None

        series_id: str = str(entry["id"]).strip()
        frequency: str = str(entry["frequency"]).lower().strip()
        revision_frequency: str = str(entry["revision_frequency"]).lower().strip()

        if frequency not in _VALID_FREQUENCIES:
            log.warning(
                "universe_loader.invalid_frequency",
                series_id=series_id,
                frequency=frequency,
            )
            return None

        if revision_frequency not in _VALID_REVISION_FREQS:
            log.warning(
                "universe_loader.invalid_revision_frequency",
                series_id=series_id,
                revision_frequency=revision_frequency,
            )
            return None

        try:
            lag = int(entry["publication_lag_days"])
            retention = int(entry["retention_years"])
        except (TypeError, ValueError):
            log.warning(
                "universe_loader.invalid_numeric",
                series_id=series_id,
            )
            return None

        return SeriesDefinition(
            id=series_id,
            name=str(entry["name"]).strip(),
            frequency=frequency,
            publication_lag_days=lag,
            revision_frequency=revision_frequency,
            retention_years=retention,
            category=category,
            source=str(entry.get("source", "fred")),
        )
