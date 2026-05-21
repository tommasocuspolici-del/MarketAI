"""SignalPersistenceService — cache su disco per il composite signal (Fase B).

Garantisce che ogni calcolo del CompositeSignalAggregator sopravviva al
riavvio di Streamlit scrivendo il risultato su DuckDB (engine_composite_signal
+ signal_snapshots). Al riavvio, l'UI legge da DuckDB senza ricalcolare.

Pattern:

    svc = SignalPersistenceService(duckdb=get_duckdb_client())
    result = svc.load_latest(max_age_hours=1)
    if result is None:
        result = CompositeSignalAggregator(duckdb=...).compute()
        svc.persist(result)

Regola 12: nessuna API call qui — solo DB read/write.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from shared.logger import get_logger
from shared.resilience.error_policy import apply_error_policy

if TYPE_CHECKING:
    from engine.alpha_generation.composite_signal_aggregator import CompositeSignalOutput
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["SignalPersistenceService"]

log = get_logger(__name__)

_TABLE_COMPOSITE = "engine_composite_signal"
_TABLE_SNAPSHOTS = "signal_snapshots"

# Default TTL per caricamento dal disco (1 ora)
_DEFAULT_MAX_AGE_HOURS = 1


class SignalPersistenceService:
    """Persiste e ricarica il composite signal da DuckDB.

    Args:
        duckdb: DuckDBClient (singleton di progetto).
    """

    def __init__(self, duckdb: DuckDBClient) -> None:
        self._db = duckdb

    # ─── Public API ───────────────────────────────────────────────────────────

    def load_latest(
        self,
        max_age_hours: float = _DEFAULT_MAX_AGE_HOURS,
    ) -> CompositeSignalOutput | None:
        """Carica l'ultimo composite signal dal DB se ancora fresco.

        Args:
            max_age_hours: Massima età accettabile in ore. Se il record è più
                vecchio (o assente) restituisce None → ricalcolare.

        Returns:
            CompositeSignalOutput se esiste e fresco, None altrimenti.
        """
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        try:
            rows = self._db.query(
                f"SELECT computed_at, vix_component, macro_component, "
                f"yield_curve_component, credit_component, claims_component, "
                f"composite_score, recommended_action, confidence, "
                f"component_breakdown_json, weights_used_json, "
                f"regime, credit_stress, claims_regime, yield_curve_regime "
                f"FROM {_TABLE_COMPOSITE} "
                f"WHERE computed_at >= ? "
                f"ORDER BY computed_at DESC LIMIT 1",
                [cutoff],
            )
        except Exception as exc:
            log.warning("signal_persistence.load_failed: %s", str(exc)[:120])
            return None

        if not rows:
            log.debug("signal_persistence.cache_miss max_age_hours=%.1f", max_age_hours)
            return None

        r = rows[0]
        log.info("signal_persistence.cache_hit computed_at=%s", r[0])
        return self._deserialize(r)

    @apply_error_policy(level="RECOVER", fallback=None, context="SignalPersistenceService.persist")
    def persist(self, result: CompositeSignalOutput) -> None:
        """Scrive il composite signal su DuckDB.

        Popola engine_composite_signal (per K1/H1) e signal_snapshots
        (per S0 Health e registry generale).

        Args:
            result: Output del CompositeSignalAggregator.compute().
        """
        self._write_composite(result)
        self._write_snapshots(result)
        log.info(
            "signal_persistence.persisted composite_score=%.3f action=%s",
            result.composite_score,
            result.recommended_action,
        )

    # ─── Internal writers ─────────────────────────────────────────────────────

    def _write_composite(self, r: CompositeSignalOutput) -> None:
        weights_json = json.dumps({
            "vix": 0.18, "macro": 0.17, "yield_curve": 0.15,
            "credit": 0.11, "claims": 0.07, "labour_market": 0.10,
            "surprise": 0.05, "valuation": 0.12, "correlation": 0.05,
        })
        self._db.execute(
            f"""
            INSERT INTO {_TABLE_COMPOSITE}
                (computed_at, vix_component, macro_component,
                 yield_curve_component, credit_component, claims_component,
                 composite_score, recommended_action, confidence,
                 component_breakdown_json, weights_used_json,
                 regime, credit_stress, claims_regime, yield_curve_regime)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (computed_at) DO UPDATE SET
                composite_score=excluded.composite_score,
                recommended_action=excluded.recommended_action,
                confidence=excluded.confidence,
                component_breakdown_json=excluded.component_breakdown_json,
                regime=excluded.regime,
                credit_stress=excluded.credit_stress,
                claims_regime=excluded.claims_regime,
                yield_curve_regime=excluded.yield_curve_regime
            """,
            [
                r.computed_at,
                r.vix_component,
                r.macro_component,
                r.yield_curve_component,
                r.credit_component,
                r.claims_component,
                r.composite_score,
                r.recommended_action,
                r.confidence,
                r.breakdown_json,
                weights_json,
                r.regime,
                r.credit_stress,
                r.claims_regime,
                r.yield_curve_regime,
            ],
        )

    def _write_snapshots(self, r: CompositeSignalOutput) -> None:
        """Scrive ogni componente in signal_snapshots per il registry."""
        component_map = {
            "composite_signal":  (r.composite_score,            r.confidence),
            "vix_component":     (r.vix_component,              "MEDIUM"),
            "macro_component":   (r.macro_component,            "MEDIUM"),
            "yield_curve_component": (r.yield_curve_component,  "MEDIUM"),
            "credit_component":  (r.credit_component,           "MEDIUM"),
            "claims_component":  (r.claims_component,           "MEDIUM"),
        }
        for signal_name, (value, confidence) in component_map.items():
            try:
                self._db.execute(
                    f"""
                    INSERT INTO {_TABLE_SNAPSHOTS}
                        (snapshot_ts, signal_name, signal_value, confidence,
                         source_module, regime_label, quality_flag)
                    VALUES (?,?,?,?,'CompositeSignalAggregator',?,?)
                    ON CONFLICT (snapshot_ts, signal_name) DO UPDATE SET
                        signal_value=excluded.signal_value,
                        confidence=excluded.confidence,
                        regime_label=excluded.regime_label
                    """,
                    [
                        r.computed_at,
                        signal_name,
                        value,
                        confidence,
                        r.regime,
                        "ok" if not r.is_degraded else "degraded",
                    ],
                )
            except Exception as exc:
                log.debug(
                    "signal_persistence.snapshot_write_failed signal=%s: %s",
                    signal_name, str(exc)[:80],
                )

    # ─── Deserialization ──────────────────────────────────────────────────────

    @staticmethod
    def _deserialize(row: tuple) -> CompositeSignalOutput:
        from engine.alpha_generation.composite_signal_aggregator import CompositeSignalOutput

        (computed_at, vix, macro, yc, credit, claims,
         score, action, confidence,
         breakdown_json, _weights_json,
         regime, credit_stress, claims_regime, yc_regime) = row

        if isinstance(computed_at, str):
            computed_at = datetime.fromisoformat(computed_at)
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=UTC)

        return CompositeSignalOutput(
            computed_at=computed_at,
            composite_score=float(score),
            recommended_action=str(action),
            confidence=str(confidence),
            vix_component=float(vix or 0.0),
            macro_component=float(macro or 0.0),
            yield_curve_component=float(yc or 0.0),
            credit_component=float(credit or 0.0),
            claims_component=float(claims or 0.0),
            labour_market_component=0.0,
            surprise_component=0.0,
            components_used=[],
            regime=regime,
            credit_stress=credit_stress,
            claims_regime=claims_regime,
            yield_curve_regime=yc_regime,
            breakdown_json=breakdown_json or "{}",
        )
