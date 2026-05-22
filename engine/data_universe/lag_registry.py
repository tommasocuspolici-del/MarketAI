"""Lag Registry — gestione dei ritardi di pubblicazione per le serie dati.

Permette di:
  - Registrare il lag tipico e massimo di una serie (publication_lag_registry)
  - Interrogare il lag per pianificare aggiornamenti
  - Seeding automatico da DataUniverse (bulk_register_from_universe)

Regola 12: solo letture/scritture DuckDB; nessuna API fetch.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pandas as pd

from shared.logger import get_logger
from shared.resilience.error_policy import apply_error_policy

if TYPE_CHECKING:
    from engine.data_universe.universe_loader import DataUniverse
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["LagRegistry"]

log = get_logger(__name__)

_TABLE = "publication_lag_registry"

# Mapping da revision_frequency (YAML) a stringa standard
_REVISION_FREQ_MAP: dict[str, str] = {
    "none": "none",
    "monthly": "monthly",
    "quarterly": "quarterly",
    "annual": "annual",
}


class LagRegistry:
    """Gestisce la tabella publication_lag_registry in DuckDB.

    Args:
        client: DuckDBClient per le operazioni sul DB.

    Esempio::

        from shared.db.duckdb_client import get_duckdb_client
        from engine.data_universe.lag_registry import LagRegistry

        reg = LagRegistry(client=get_duckdb_client())
        reg.register("ICSA", typical_lag=4, max_lag=7, revision_freq="none", source="fred")
        lag = reg.get_lag("ICSA")   # 4
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client

    # ─── Write operations ────────────────────────────────────────────────

    @apply_error_policy(
        level="DEGRADE",
        fallback=0,
        context="LagRegistry.register",
    )
    def register(
        self,
        series_id: str,
        *,
        typical_lag: int,
        max_lag: int,
        revision_freq: str = "none",
        revision_magnitude_avg: float | None = None,
        source: str = "fred",
    ) -> int:
        """Registra o aggiorna il lag di pubblicazione per una serie.

        Usa INSERT OR REPLACE per aggiornare se già esistente.

        Args:
            series_id: Codice serie (es. "ICSA").
            typical_lag: Giorni tipici tra fine periodo e pubblicazione.
            max_lag: Giorni massimi osservati.
            revision_freq: Frequenza revisioni (none/monthly/quarterly/annual).
            revision_magnitude_avg: Magnitudine media delle revisioni (opzionale).
            source: Provider dei dati.

        Returns:
            1 se operazione completata con successo.
        """
        now_utc = datetime.now(tz=timezone.utc)
        rev_freq = _REVISION_FREQ_MAP.get(revision_freq.lower(), "none")

        self._client.execute(
            f"""
            INSERT INTO {_TABLE}
                (series_id, typical_lag_days, max_lag_days,
                 revision_frequency, revision_magnitude_avg, source, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (series_id) DO UPDATE SET
                typical_lag_days       = excluded.typical_lag_days,
                max_lag_days           = excluded.max_lag_days,
                revision_frequency     = excluded.revision_frequency,
                revision_magnitude_avg = excluded.revision_magnitude_avg,
                source                 = excluded.source,
                last_updated           = excluded.last_updated
            """,
            [
                series_id,
                typical_lag,
                max_lag,
                rev_freq,
                revision_magnitude_avg,
                source,
                now_utc,
            ],
        )
        log.debug(
            "lag_registry.register",
            series_id=series_id,
            typical_lag=typical_lag,
            max_lag=max_lag,
        )
        return 1

    def bulk_register_from_universe(
        self,
        universe: DataUniverse,
    ) -> int:
        """Popola la tabella lag_registry dalle definizioni in DataUniverse.

        Itera su tutte le serie e chiama register() per ciascuna.
        Utile per il seeding iniziale del DB.

        Args:
            universe: DataUniverse caricato da UniverseLoader.

        Returns:
            Numero di serie registrate.
        """
        count = 0
        for defn in universe.series.values():
            result = self.register(
                series_id=defn.id,
                typical_lag=defn.publication_lag_days,
                max_lag=defn.publication_lag_days * 2,  # stima conservativa del massimo
                revision_freq=defn.revision_frequency,
                source=defn.source,
            )
            count += result

        log.info(
            "lag_registry.bulk_register_done",
            registered=count,
            total_in_universe=universe.count(),
        )
        return count

    # ─── Read operations ─────────────────────────────────────────────────

    @apply_error_policy(
        level="RECOVER",
        fallback=0,
        context="LagRegistry.get_lag",
    )
    def get_lag(self, series_id: str) -> int:
        """Restituisce il lag tipico di pubblicazione per una serie.

        Args:
            series_id: Codice serie.

        Returns:
            Giorni tipici di lag (0 se la serie non è registrata).
        """
        rows = self._client.query(
            f"SELECT typical_lag_days FROM {_TABLE} WHERE series_id = ? LIMIT 1",
            [series_id],
        )
        if not rows or rows[0][0] is None:
            log.warning("lag_registry.not_found", series_id=series_id)
            return 0
        return int(rows[0][0])

    @apply_error_policy(
        level="DEGRADE",
        fallback=None,
        context="LagRegistry.get_entry",
    )
    def get_entry(self, series_id: str) -> dict[str, object] | None:
        """Restituisce tutte le informazioni di lag per una serie.

        Args:
            series_id: Codice serie.

        Returns:
            Dict con campi della tabella, oppure None se non trovato.
        """
        rows = self._client.query(
            f"""
            SELECT series_id, typical_lag_days, max_lag_days,
                   revision_frequency, revision_magnitude_avg, source, last_updated
            FROM {_TABLE}
            WHERE series_id = ?
            LIMIT 1
            """,
            [series_id],
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "series_id": row[0],
            "typical_lag_days": row[1],
            "max_lag_days": row[2],
            "revision_frequency": row[3],
            "revision_magnitude_avg": row[4],
            "source": row[5],
            "last_updated": row[6],
        }

    @apply_error_policy(
        level="DEGRADE",
        fallback=pd.DataFrame(),
        context="LagRegistry.get_all",
    )
    def get_all(self) -> pd.DataFrame:
        """Restituisce l'intera tabella di lag come DataFrame.

        Returns:
            DataFrame con tutte le serie registrate.
        """
        return self._client.query_df(
            f"SELECT * FROM {_TABLE} ORDER BY series_id"
        )

    @apply_error_policy(
        level="DEGRADE",
        fallback=[],
        context="LagRegistry.series_needing_update",
    )
    def series_needing_update(self, lookback_hours: int = 24) -> list[str]:
        """Restituisce le serie la cui registrazione è più vecchia di lookback_hours.

        Utile per pianificare re-fetch selettivi.

        Args:
            lookback_hours: Soglia in ore per considerare un record stale.

        Returns:
            Lista di series_id da aggiornare.
        """
        rows = self._client.query(
            f"""
            SELECT series_id
            FROM {_TABLE}
            WHERE last_updated < NOW() - INTERVAL '{lookback_hours} hours'
            ORDER BY last_updated ASC
            """,
        )
        return [r[0] for r in rows]
