"""Staleness Detector — flagga segnali basati su dati stale."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

log = get_logger(__name__)

STALE_THRESHOLD_DAYS: int = 5   # business days


@dataclass
class StalenessReport:
    signal_id: str
    last_updated: date | None
    staleness_days: int
    is_stale: bool
    reason: str


class StalenessDetector:
    """Detecta segnali stale confrontando la data dell'ultimo aggiornamento.

    Un segnale è considerato stale se non è stato aggiornato entro
    `stale_threshold_days` giorni lavorativi dalla data corrente.
    """

    def __init__(self, stale_threshold_days: int = STALE_THRESHOLD_DAYS) -> None:
        self._threshold = stale_threshold_days

    def _count_business_days(self, from_date: date, to_date: date) -> int:
        """Conta i giorni lavorativi (Mon-Fri) tra due date."""
        if from_date >= to_date:
            return 0
        total = 0
        current = from_date + timedelta(days=1)
        while current <= to_date:
            if current.weekday() < 5:  # Mon=0 ... Fri=4
                total += 1
            current += timedelta(days=1)
        return total

    def check_signal(self, signal_id: str, last_updated: date) -> StalenessReport:
        """Verifica se un singolo segnale è stale.

        Args:
            signal_id: Identificatore del segnale.
            last_updated: Data dell'ultimo aggiornamento del segnale.

        Returns:
            StalenessReport con dettagli sulla freschezza.
        """
        today = datetime.now(UTC).date()
        staleness_days = self._count_business_days(last_updated, today)
        is_stale = staleness_days >= self._threshold

        if is_stale:
            reason = (
                f"Signal '{signal_id}' not updated for {staleness_days} business days "
                f"(threshold: {self._threshold}). Last update: {last_updated}"
            )
        else:
            reason = (
                f"Signal '{signal_id}' is fresh: {staleness_days} business days "
                f"since last update on {last_updated}"
            )

        log.debug(
            "staleness_detector.checked",
            signal_id=signal_id,
            staleness_days=staleness_days,
            is_stale=is_stale,
        )

        return StalenessReport(
            signal_id=signal_id,
            last_updated=last_updated,
            staleness_days=staleness_days,
            is_stale=is_stale,
            reason=reason,
        )

    def check_all(self, signals: dict[str, date]) -> list[StalenessReport]:
        """Verifica la freschezza di tutti i segnali forniti.

        Args:
            signals: Dizionario {signal_id: last_updated}.

        Returns:
            Lista di StalenessReport, uno per segnale.
        """
        reports: list[StalenessReport] = []
        for signal_id, last_updated in signals.items():
            report = self.check_signal(signal_id, last_updated)
            reports.append(report)

        stale_count = sum(1 for r in reports if r.is_stale)
        log.info(
            "staleness_detector.check_all",
            total=len(reports),
            stale_count=stale_count,
        )
        return reports
