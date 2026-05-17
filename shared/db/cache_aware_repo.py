"""CacheAwareRepository — base class cache-first (Regola 34).

Ogni repository che eredita da questa classe:
  1. Cerca il dato in DuckDB prima di chiamare l'API esterna.
  2. Controlla il TTL: se fresco → ritorna subito (zero API call).
  3. Se stale → chiama l'API → scrive in DuckDB → ritorna il dato aggiornato.
  4. Logga ogni operazione con structlog (TTL remaining, source, latency).

Questo garantisce:
  - Lo scheduler popola DuckDB periodicamente.
  - Le query UI leggono da DuckDB (< 1ms) senza mai chiamare API.
  - Le API vengono chiamate SOLO dallo scheduler o da force_refresh.
  - Zero rate limit violations da accessi UI concorrenti.

Regola 34: ogni fetcher che bypassa il TTL senza motivo è un bug CRITICAL.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, TypeVar

import structlog

from shared.config.cache_ttl_config import CACHE_TTL
from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"

log = structlog.get_logger(__name__)

T = TypeVar("T")


class CacheAwareRepository(ABC, Generic[T]):
    """Base class per tutti i repository con cache-first pattern (Regola 34).

    Args:
        duckdb:      Client DuckDB (singleton di progetto).
        ttl_key:     Chiave TTL in config/cache_ttl.yaml (es. 'macro_fred').
        ttl_seconds: Override diretto in secondi (usato se ttl_key non trovato).
    """

    def __init__(
        self,
        duckdb: DuckDBClient,
        ttl_key: str,
        ttl_seconds: int | None = None,
    ) -> None:
        self._db = duckdb
        self._ttl_key = ttl_key
        _resolved = ttl_seconds if ttl_seconds is not None else CACHE_TTL.get(ttl_key)
        self._ttl = timedelta(seconds=_resolved)

    # ─── Public interface ────────────────────────────────────────────────────

    def read(self, key: str, force_refresh: bool = False) -> T | None:
        """Cache-first read (Regola 34).

        Args:
            key:           Identificatore del dato (ticker, series_id, ecc.).
            force_refresh: Bypassa cache — usare SOLO dallo scheduler
                           con justification loggata.

        Returns:
            Il valore (T) se disponibile, None se non reperibile.
        """
        t0 = time.monotonic()

        if not force_refresh:
            cached = self._read_from_db(key)
            if cached is not None and self._is_fresh(cached):
                remaining = self._ttl_remaining(cached)
                log.debug(
                    "cache.hit",
                    key=key,
                    ttl_key=self._ttl_key,
                    ttl_remaining_s=round(remaining, 1),
                    latency_ms=round((time.monotonic() - t0) * 1000, 2),
                )
                return self._extract_value(cached)

        # Cache miss o stale → aggiorna dalla sorgente
        fresh = self._fetch_from_source(key)
        if fresh is not None:
            self._write_to_db(key, fresh)
            log.info(
                "cache.refreshed",
                key=key,
                ttl_key=self._ttl_key,
                latency_ms=round((time.monotonic() - t0) * 1000, 2),
            )
        else:
            log.warning(
                "cache.fetch_failed",
                key=key,
                ttl_key=self._ttl_key,
            )
        return fresh

    def read_or_stale(self, key: str) -> T | None:
        """Come read(), ma ritorna dati stale in cache se fetch fallisce.

        Utile per UI: meglio un dato vecchio che un errore.
        """
        t0 = time.monotonic()
        cached = self._read_from_db(key)

        if cached is not None and self._is_fresh(cached):
            log.debug("cache.hit", key=key, ttl_key=self._ttl_key)
            return self._extract_value(cached)

        # Prova fetch fresco
        fresh = self._fetch_from_source(key)
        if fresh is not None:
            self._write_to_db(key, fresh)
            log.info("cache.refreshed", key=key, latency_ms=round((time.monotonic() - t0) * 1000, 2))
            return fresh

        # Fallback: ritorna dato stale se presente
        if cached is not None:
            log.warning("cache.stale_fallback", key=key, ttl_key=self._ttl_key)
            return self._extract_value(cached)

        return None

    def invalidate(self, key: str) -> None:
        """Invalida la cache per una chiave specifica (forza re-fetch)."""
        self._invalidate_in_db(key)
        log.info("cache.invalidated", key=key, ttl_key=self._ttl_key)

    # ─── Abstract interface — da implementare nelle sottoclassi ─────────────

    @abstractmethod
    def _read_from_db(self, key: str) -> dict[str, Any] | None:
        """Legge il record dalla tabella DuckDB. Ritorna None se assente."""

    @abstractmethod
    def _fetch_from_source(self, key: str) -> T | None:
        """Chiama la sorgente esterna. Ritorna None se non reperibile."""

    @abstractmethod
    def _write_to_db(self, key: str, value: T) -> None:
        """Scrive il valore in DuckDB con fetched_at = NOW()."""

    @abstractmethod
    def _extract_value(self, row: dict[str, Any]) -> T:
        """Deserializza il record DuckDB nel tipo T atteso."""

    def _invalidate_in_db(self, key: str) -> None:
        """Override per invalidazione custom. Default: no-op."""

    # ─── TTL helpers ─────────────────────────────────────────────────────────

    def _is_fresh(self, row: dict[str, Any]) -> bool:
        """True se il dato è stato aggiornato entro il TTL."""
        fetched_at = row.get("fetched_at") or row.get("computed_at") or row.get("updated_at")
        if fetched_at is None:
            return False
        if not isinstance(fetched_at, datetime):
            try:
                fetched_at = datetime.fromisoformat(str(fetched_at))
            except (ValueError, TypeError):
                return False
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        age = datetime.now(UTC) - fetched_at
        return age < self._ttl

    def _ttl_remaining(self, row: dict[str, Any]) -> float:
        """Secondi rimanenti prima che il dato diventi stale."""
        fetched_at = row.get("fetched_at") or row.get("computed_at") or row.get("updated_at")
        if fetched_at is None:
            return 0.0
        if not isinstance(fetched_at, datetime):
            try:
                fetched_at = datetime.fromisoformat(str(fetched_at))
            except (ValueError, TypeError):
                return 0.0
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)
        age = datetime.now(UTC) - fetched_at
        return max(0.0, (self._ttl - age).total_seconds())

    @property
    def ttl_seconds(self) -> float:
        """TTL configurato in secondi."""
        return self._ttl.total_seconds()
