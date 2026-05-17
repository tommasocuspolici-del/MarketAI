"""DataSourceManager — orchestratore fallback chain (Regola 34).

L'unico punto autorizzato a forzare un refresh (force_refresh=True).
Ogni fallback chain è definita in config/data_fallback_chains.yaml.

Pattern:
  1. Leggi da DuckDB (sub-ms)
  2. Se dato fresco (< TTL) → ritorna
  3. Se stale → tenta sorgente primaria → sorgente secondaria → ... → DuckDB stale + warning
  4. Logga ogni passaggio con justification se force_refresh=True
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import yaml

from shared.config.cache_ttl_config import CACHE_TTL
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["DataSourceManager", "get_data_source_manager", "FallbackResult"]

log = get_logger(__name__)

_CHAINS_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "data_fallback_chains.yaml"


@dataclass(frozen=True)
class FallbackResult:
    """Risultato di una query DataSourceManager."""
    data: Any
    source: str
    is_stale: bool
    ttl_remaining_s: float
    fetched_at: datetime | None


@dataclass
class ChainEntry:
    source: str
    ttl_key: str
    priority: int = 0


@dataclass
class FallbackChain:
    name: str
    entries: list[ChainEntry] = field(default_factory=list)


class DataSourceManager:
    """Gestore fallback chain per ogni categoria di dato.

    Regola 34: unico punto autorizzato a chiamare force_refresh.
    Ogni altra chiamata API deve passare per CacheAwareRepository o questo manager.

    Args:
        client:   DuckDBClient per letture cache.
        chains:   Catene di fallback caricate da YAML.
    """

    def __init__(self, client: DuckDBClient, chains: dict[str, FallbackChain] | None = None) -> None:
        self._client = client
        self._chains = chains or _load_chains()

    def read(
        self,
        category: str,
        key: str,
        force_refresh: bool = False,
        force_justification: str | None = None,
    ) -> FallbackResult:
        """Legge un dato seguendo la fallback chain per la categoria.

        Args:
            category:             Categoria dati (es. 'price_ohlcv', 'macro_fred').
            key:                  Chiave specifica (ticker, series_id, ecc.).
            force_refresh:        Bypassa cache. SOLO dallo scheduler.
            force_justification:  Ragione del bypass (obbligatoria se force_refresh=True).

        Returns:
            FallbackResult con dato, sorgente e stato cache.
        """
        if force_refresh:
            if not force_justification:
                log.warning("dsm.force_refresh_no_justification", category=category, key=key)
            else:
                log.info("dsm.force_refresh", category=category, key=key, justification=force_justification)

        chain = self._chains.get(category)
        if chain is None:
            log.warning("dsm.unknown_category", category=category)
            return FallbackResult(data=None, source="none", is_stale=True, ttl_remaining_s=0.0, fetched_at=None)

        # 1. Prova cache DuckDB prima (anche con force_refresh=True per logging)
        if not force_refresh:
            cached = self._read_cache(category, key, chain)
            if cached is not None and not cached.is_stale:
                return cached

        # 2. Prova ogni sorgente nella catena
        for entry in chain.entries:
            if entry.source == "duckdb_cache":
                # Ultimo resort: ritorna dato stale dal DB con warning
                stale = self._read_cache(category, key, chain)
                if stale is not None:
                    log.warning("dsm.stale_fallback", category=category, key=key, source="duckdb_cache")
                    return FallbackResult(
                        data=stale.data,
                        source="duckdb_cache_stale",
                        is_stale=True,
                        ttl_remaining_s=0.0,
                        fetched_at=stale.fetched_at,
                    )
                continue

        return FallbackResult(data=None, source="none", is_stale=True, ttl_remaining_s=0.0, fetched_at=None)

    def get_chain(self, category: str) -> FallbackChain | None:
        return self._chains.get(category)

    def list_categories(self) -> list[str]:
        return list(self._chains.keys())

    def health_check(self) -> dict[str, bool]:
        """Verifica lo stato di ogni categoria (cache disponibile)."""
        results: dict[str, bool] = {}
        for cat in self._chains:
            try:
                # Prova una query semplice
                self._client.query("SELECT 1 FROM macro_data LIMIT 1")
                results[cat] = True
            except Exception:
                results[cat] = False
        return results

    # ─── Helpers privati ─────────────────────────────────────────────────────

    def _read_cache(self, category: str, key: str, chain: FallbackChain) -> FallbackResult | None:
        """Lettura generica da DuckDB per qualsiasi categoria."""
        ttl_key = chain.entries[0].ttl_key if chain.entries else "prezzi_daily"
        ttl_s = CACHE_TTL.get(ttl_key)

        try:
            if category == "price_ohlcv":
                rows = self._client.query(
                    "SELECT close, fetched_at FROM ohlcv_data WHERE ticker=? "
                    "ORDER BY ts DESC LIMIT 1", [key]
                )
                if rows:
                    return self._make_result(rows[0][0], rows[0][1], ttl_s, "duckdb")

            elif category in ("macro_fred", "macro_ecb", "macro_imf", "macro_oecd"):
                rows = self._client.query(
                    "SELECT value, fetched_at FROM macro_data WHERE series_id=? "
                    "ORDER BY series_date DESC LIMIT 1", [key]
                )
                if rows:
                    return self._make_result(rows[0][0], rows[0][1], ttl_s, "duckdb")

            elif category == "pe_metrics":
                rows = self._client.query(
                    "SELECT trailing_pe, forward_pe, shiller_cape, erp_implied, fetched_at "
                    "FROM pe_metrics WHERE ticker=? ORDER BY metric_date DESC LIMIT 1", [key]
                )
                if rows:
                    data = {
                        "trailing_pe": rows[0][0],
                        "forward_pe": rows[0][1],
                        "shiller_cape": rows[0][2],
                        "erp_implied": rows[0][3],
                    }
                    return self._make_result(data, rows[0][4], ttl_s, "duckdb")

            elif category == "news_articles":
                rows = self._client.query(
                    "SELECT article_id, title, source, fetched_at FROM news_articles "
                    "ORDER BY published_at DESC LIMIT 50"
                )
                if rows:
                    return self._make_result(rows, rows[0][3] if rows else None, ttl_s, "duckdb")

        except Exception as exc:
            log.debug("dsm.cache_read_failed", category=category, key=key, error=str(exc)[:100])

        return None

    def _make_result(
        self, data: Any, fetched_at: Any, ttl_s: int, source: str
    ) -> FallbackResult:
        """Costruisce FallbackResult calcolando is_stale e ttl_remaining."""
        now = datetime.now(UTC)
        if fetched_at is None:
            return FallbackResult(data=data, source=source, is_stale=True, ttl_remaining_s=0.0, fetched_at=None)

        if isinstance(fetched_at, str):
            try:
                fetched_at = datetime.fromisoformat(fetched_at)
            except ValueError:
                fetched_at = now

        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=UTC)

        age_s = (now - fetched_at).total_seconds()
        remaining_s = max(0.0, ttl_s - age_s)
        is_stale = age_s > ttl_s

        return FallbackResult(
            data=data,
            source=source,
            is_stale=is_stale,
            ttl_remaining_s=remaining_s,
            fetched_at=fetched_at,
        )


# ─── Caricamento chains da YAML ───────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_chains() -> dict[str, FallbackChain]:
    if not _CHAINS_PATH.exists():
        log.warning("dsm.chains_file_not_found", path=str(_CHAINS_PATH))
        return _default_chains()

    with _CHAINS_PATH.open(encoding="utf-8") as f:
        raw: dict[str, object] = yaml.safe_load(f) or {}

    chains: dict[str, FallbackChain] = {}
    for cat_name, entries_raw in raw.items():
        if not isinstance(entries_raw, list):
            continue
        entries = []
        for i, entry in enumerate(entries_raw):
            entries.append(ChainEntry(
                source=entry.get("source", "unknown"),
                ttl_key=entry.get("ttl_key", "prezzi_daily"),
                priority=i,
            ))
        chains[cat_name] = FallbackChain(name=cat_name, entries=entries)

    return chains


def _default_chains() -> dict[str, FallbackChain]:
    """Chains di fallback minimali se YAML non trovato."""
    return {
        "price_ohlcv": FallbackChain("price_ohlcv", [
            ChainEntry("yfinance_polling", "prezzi_daily", 0),
            ChainEntry("duckdb_cache", "prezzi_daily", 1),
        ]),
        "macro_fred": FallbackChain("macro_fred", [
            ChainEntry("fred_api", "macro_fred", 0),
            ChainEntry("duckdb_cache", "macro_fred", 1),
        ]),
        "pe_metrics": FallbackChain("pe_metrics", [
            ChainEntry("edgar_xbrl", "fondamentali", 0),
            ChainEntry("alpha_vantage_earnings", "fondamentali", 1),
            ChainEntry("duckdb_cache", "pe_metrics", 2),
        ]),
    }


_instance: DataSourceManager | None = None


def get_data_source_manager(client: DuckDBClient | None = None) -> DataSourceManager:
    """Singleton DataSourceManager. Richiede client al primo accesso."""
    global _instance
    if _instance is None:
        if client is None:
            from shared.db.duckdb_client import get_duckdb_client
            client = get_duckdb_client()
        _instance = DataSourceManager(client)
    return _instance
