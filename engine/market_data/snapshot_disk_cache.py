"""Persistent disk cache for MarketSnapshot.

Salva l'ultimo snapshot di mercato fetchato con successo su disco (JSON).
Viene usato come fallback di ultima istanza quando l'API è offline e la
cache in-memory è vuota (es. dopo un riavvio del server Streamlit).

La cache ha un TTL configurabile (default 24h) per evitare di mostrare
dati troppo vecchi. Oltre il TTL il file viene ignorato.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from shared.constants import DATA_DIR
from shared.logger import get_logger

log = get_logger(__name__)

_DEFAULT_PATH: Path = DATA_DIR / "cache" / "market_snapshot.json"


def _snapshot_to_dict(snapshot: Any) -> dict[str, Any]:
    """Serializza MarketSnapshot in dict JSON-serializzabile."""
    return {
        "fetched_at": snapshot.fetched_at,
        "n_errors": snapshot.n_errors,
        "saved_at": time.time(),
        "kpis": [
            {
                "term": k.term,
                "yf_ticker": k.yf_ticker,
                "value": k.value,
                "delta_pct": k.delta_pct,
                "currency": k.currency,
                "format_spec": k.format_spec,
                "is_override": k.is_override,
                "error": k.error,
            }
            for k in snapshot.kpis
        ],
    }


def _dict_to_snapshot(data: dict[str, Any]) -> Any:
    """Deserializza dict JSON in MarketSnapshot con tutti i KPI marcati stale."""
    from engine.market_data.kpi_computer import MarketKpi, MarketSnapshot

    kpis = [
        MarketKpi(
            term=k["term"],
            yf_ticker=k["yf_ticker"],
            value=k.get("value"),
            delta_pct=k.get("delta_pct"),
            currency=k["currency"],
            format_spec=k["format_spec"],
            is_override=k.get("is_override", False),
            is_stale=True,
            error=k.get("error", ""),
        )
        for k in data.get("kpis", [])
    ]
    return MarketSnapshot(
        kpis=kpis,
        fetched_at=data.get("fetched_at", 0.0),
        is_stale=True,
        n_errors=0,
    )


class SnapshotDiskCache:
    """Gestisce la cache persistente su disco dello snapshot KPI."""

    def __init__(
        self,
        path: Path = _DEFAULT_PATH,
        max_age_s: float = 86400.0,
    ) -> None:
        self._path = path
        self._max_age_s = max_age_s

    def save(self, snapshot: Any) -> None:
        """Persiste snapshot su disco solo se contiene dati validi."""
        if not snapshot.kpis or snapshot.is_unavailable or snapshot.is_stale:
            return
        n_valid = sum(1 for k in snapshot.kpis if k.value is not None)
        if n_valid == 0:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(_snapshot_to_dict(snapshot), indent=2),
                encoding="utf-8",
            )
            log.debug(
                "snapshot_disk_cache.saved",
                n_kpis=len(snapshot.kpis),
                n_valid=n_valid,
                path=str(self._path),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("snapshot_disk_cache.save_failed", error=str(exc)[:200])

    def load(self) -> Any | None:
        """Carica snapshot da disco se il file esiste e non ha superato il TTL.

        Returns:
            MarketSnapshot con is_stale=True, o None se non disponibile/troppo vecchio.
        """
        if not self._path.exists():
            return None
        try:
            data: dict[str, Any] = json.loads(
                self._path.read_text(encoding="utf-8")
            )
            saved_at: float = data.get("saved_at", 0.0)
            age_s = time.time() - saved_at
            if age_s > self._max_age_s:
                log.info(
                    "snapshot_disk_cache.expired",
                    age_hours=round(age_s / 3600, 1),
                    max_age_hours=round(self._max_age_s / 3600, 1),
                )
                return None
            snapshot = _dict_to_snapshot(data)
            if not snapshot.kpis:
                return None
            log.info(
                "snapshot_disk_cache.loaded",
                age_minutes=round(age_s / 60, 1),
                n_kpis=len(snapshot.kpis),
            )
            return snapshot
        except Exception as exc:  # noqa: BLE001
            log.warning("snapshot_disk_cache.load_failed", error=str(exc)[:200])
            return None

    def age_seconds(self) -> float | None:
        """Età in secondi del file cache su disco. None se non esiste."""
        if not self._path.exists():
            return None
        try:
            data: dict[str, Any] = json.loads(
                self._path.read_text(encoding="utf-8")
            )
            saved_at = data.get("saved_at", 0.0)
            return time.time() - saved_at if saved_at else None
        except Exception:  # noqa: BLE001
            return None
