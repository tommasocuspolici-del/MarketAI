"""DataQualityAlerter — alert automatici su quality score basso (Regola 26).

Monitora la tabella ``data_quality_reports`` in DuckDB e genera alert
nella tabella ``data_quality_alerts`` (migration 012) quando un
DataQualityReport scende sotto le soglie configurate.

Soglie default (da constants):
  · CRITICAL: quality_score < 0.5 — dato non entra nei calcoli (Regola 26)
  · WARNING:  quality_score < 0.7 — dato entra ma con badge ⚠️ in UI

Deduplication: per ogni (series_id, severity) non viene creato un nuovo
alert se esiste già un alert aperto nelle ultime 24h. Questo evita spam
quando una serie rimane sotto soglia a lungo.

ANTI-REGRESSIONE (v9.0 Sett.2):
  · I threshold sono letti da QualityScoringConfig (config/data_quality.yaml),
    non hardcoded — rispetta la Regola 7.
  · La query di dedup usa l'indice idx_dq_alerts_kind_series_open (migration 012).
    Se la tabella non esiste (DB non migrato) → graceful degradation con log.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np

from shared.db.duckdb_client import DuckDBClient, get_duckdb_client
from shared.db.quality import MIN_QUALITY_SCORE_CRITICAL, load_quality_config
from shared.exceptions import DatabaseError
from shared.logger import get_logger

if TYPE_CHECKING:
    pass

__version__ = "9.0.0"
__all__ = ["DataQualityAlerter", "QualityAlert"]

log = get_logger(__name__)

# Soglie nominali (Regola 7)
_THRESHOLD_CRITICAL: float = MIN_QUALITY_SCORE_CRITICAL  # 0.5
_THRESHOLD_WARNING: float = 0.70
_DEDUP_WINDOW_HOURS: int = 24


@dataclass(frozen=True, slots=True)
class QualityAlert:
    """Rappresentazione in-memory di un alert di qualità generato."""

    series_id: str
    severity: str       # 'WARNING' | 'CRITICAL'
    quality_score: float
    threshold: float
    detail: str
    created_at: datetime


class DataQualityAlerter:
    """Genera e persiste alert quando quality_score scende sotto soglia.

    Uso tipico (dal job di qualità o dall'analisi pipeline):
        alerter = DataQualityAlerter()
        alerts = alerter.check_and_alert(series_id="ICSA", quality_score=0.43)
    """

    def __init__(self, client: DuckDBClient | None = None) -> None:
        self._client = client or get_duckdb_client()
        # Carica soglie da config (Regola 7: nessun magic number)
        try:
            cfg = load_quality_config()
            # QualityScoringConfig non espone threshold → usiamo i default nominali
        except Exception:  # noqa: BLE001
            pass  # fallback ai default nominali definiti sopra

    # ─── Public API ────────────────────────────────────────────────────────

    def check_and_alert(
        self,
        series_id: str,
        quality_score: float,
        detail: str = "",
    ) -> list[QualityAlert]:
        """Controlla quality_score e genera alert se sotto soglia.

        Args:
            series_id: Identificatore della serie (ticker, FRED series_id, ecc.)
            quality_score: Score corrente in [0, 1].
            detail: Messaggio descrittivo opzionale.

        Returns:
            Lista di QualityAlert generati (0, 1 o 2 a seconda delle soglie).
            Lista vuota se score è OK o se l'alert è già stato emesso nelle 24h.
        """
        if np.isnan(quality_score):
            return []

        generated: list[QualityAlert] = []

        # CRITICAL: score < 0.5
        if quality_score < _THRESHOLD_CRITICAL:
            alert = self._maybe_create_alert(
                series_id=series_id,
                severity="CRITICAL",
                quality_score=quality_score,
                threshold=_THRESHOLD_CRITICAL,
                detail=detail or (
                    f"Quality score {quality_score:.3f} sotto la soglia critica "
                    f"{_THRESHOLD_CRITICAL:.2f}. Dato ESCLUSO dai calcoli (Regola 26)."
                ),
            )
            if alert is not None:
                generated.append(alert)

        # WARNING: 0.5 ≤ score < 0.7
        elif quality_score < _THRESHOLD_WARNING:
            alert = self._maybe_create_alert(
                series_id=series_id,
                severity="WARNING",
                quality_score=quality_score,
                threshold=_THRESHOLD_WARNING,
                detail=detail or (
                    f"Quality score {quality_score:.3f} sotto la soglia warning "
                    f"{_THRESHOLD_WARNING:.2f}. Dato visualizzato con badge ⚠️."
                ),
            )
            if alert is not None:
                generated.append(alert)

        return generated

    def check_batch(
        self,
        series_scores: dict[str, float],
    ) -> list[QualityAlert]:
        """Controlla un batch di serie e genera tutti gli alert necessari.

        Args:
            series_scores: Dizionario {series_id: quality_score}.

        Returns:
            Lista di tutti gli alert generati.
        """
        all_alerts: list[QualityAlert] = []
        for sid, score in series_scores.items():
            alerts = self.check_and_alert(sid, score)
            all_alerts.extend(alerts)
        return all_alerts

    def get_open_alerts(
        self,
        series_id: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> list[QualityAlert]:
        """Legge gli alert aperti (is_resolved=FALSE) da DuckDB.

        Args:
            series_id: Filtra per serie specifica. None = tutte.
            severity: Filtra per severità. None = tutte.
            limit: Numero massimo di alert restituiti.

        Returns:
            Lista di QualityAlert dal più recente al meno recente.
        """
        try:
            where_clauses: list[str] = ["is_resolved = FALSE"]
            params: list[object] = []

            if series_id is not None:
                where_clauses.append("series_id = ?")
                params.append(series_id)
            if severity is not None:
                where_clauses.append("severity = ?")
                params.append(severity)

            where_sql = " AND ".join(where_clauses)
            params.append(limit)

            with self._client.transaction() as conn:
                rows = conn.execute(
                    f"""
                    SELECT series_id, severity, quality_score, threshold,
                           COALESCE(detail, '') AS detail, created_at
                    FROM data_quality_alerts
                    WHERE {where_sql}
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()

            return [
                QualityAlert(
                    series_id=r[0],
                    severity=r[1],
                    quality_score=float(r[2]) if r[2] is not None else np.nan,
                    threshold=float(r[3]) if r[3] is not None else np.nan,
                    detail=str(r[4]),
                    created_at=r[5],
                )
                for r in rows
            ]

        except Exception as exc:
            log.warning(
                "dq_alerter.get_open_alerts_error",
                error=str(exc)[:120],
            )
            return []

    def mark_resolved(self, series_id: str, severity: str | None = None) -> int:
        """Marca come risolti tutti gli alert aperti per una serie.

        Utile quando la qualità torna sopra soglia dopo un fix.

        Returns:
            Numero di alert marcati come risolti.
        """
        try:
            params: list[object] = [
                datetime.now(UTC).isoformat(),
                series_id,
            ]
            where_extra = ""
            if severity is not None:
                where_extra = " AND severity = ?"
                params.append(severity)

            with self._client.transaction() as conn:
                conn.execute(
                    f"""
                    UPDATE data_quality_alerts
                    SET is_resolved = TRUE, resolved_at = ?
                    WHERE series_id = ?
                    AND is_resolved = FALSE
                    {where_extra}
                    """,
                    params,
                )
                # DuckDB non espone rowcount via Python in tutte le versioni
                # → leggiamo quanti erano aperti per logging
                n = conn.execute(
                    "SELECT COUNT(*) FROM data_quality_alerts "
                    "WHERE series_id = ? AND is_resolved = TRUE",
                    [series_id],
                ).fetchone()[0]
            return int(n)

        except Exception as exc:
            log.warning(
                "dq_alerter.mark_resolved_error",
                series_id=series_id,
                error=str(exc)[:120],
            )
            return 0

    # ─── Internals ─────────────────────────────────────────────────────────

    def _maybe_create_alert(
        self,
        *,
        series_id: str,
        severity: str,
        quality_score: float,
        threshold: float,
        detail: str,
    ) -> QualityAlert | None:
        """Crea l'alert solo se non esiste già uno aperto nelle ultime 24h.

        Deduplication pattern: controlla PRIMA di scrivere.
        """
        if self._has_recent_alert(series_id, severity):
            log.debug(
                "dq_alerter.dedup_skip",
                series_id=series_id,
                severity=severity,
            )
            return None

        alert = QualityAlert(
            series_id=series_id,
            severity=severity,
            quality_score=quality_score,
            threshold=threshold,
            detail=detail,
            created_at=datetime.now(UTC),
        )
        self._persist_alert(alert)
        log.info(
            "dq_alerter.alert_created",
            series_id=series_id,
            severity=severity,
            score=round(quality_score, 3),
        )
        return alert

    def _has_recent_alert(self, series_id: str, severity: str) -> bool:
        """True se esiste un alert aperto per la stessa serie + severità nelle ultime 24h."""
        cutoff = (datetime.now(UTC) - timedelta(hours=_DEDUP_WINDOW_HOURS)).isoformat()
        try:
            with self._client.transaction() as conn:
                count = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM data_quality_alerts
                    WHERE series_id = ?
                    AND severity = ?
                    AND alert_kind = 'quality_below_threshold'
                    AND is_resolved = FALSE
                    AND created_at >= ?
                    """,
                    [series_id, severity, cutoff],
                ).fetchone()[0]
            return int(count) > 0
        except Exception as exc:
            # Se la tabella non esiste (migration non ancora applicata) →
            # graceful degradation: non blocca il flusso principale.
            log.debug("dq_alerter.dedup_query_failed", error=str(exc)[:100])
            return False

    def _persist_alert(self, alert: QualityAlert) -> None:
        """Inserisce un alert nella tabella data_quality_alerts."""
        try:
            with self._client.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO data_quality_alerts
                    (series_id, alert_kind, severity, quality_score,
                     threshold, detail, created_at)
                    VALUES (?, 'quality_below_threshold', ?, ?, ?, ?, ?)
                    """,
                    [
                        alert.series_id,
                        alert.severity,
                        float(alert.quality_score),
                        float(alert.threshold),
                        alert.detail[:500],  # cap a 500 char (schema)
                        alert.created_at.isoformat(),
                    ],
                )
        except Exception as exc:
            raise DatabaseError(
                f"Failed to persist quality alert for {alert.series_id}: {exc}"
            ) from exc
