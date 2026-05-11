"""
LabourRegimeClassifier: classifica il regime aggregato del mercato del lavoro.

Combina i segnali di:
  · JOLTSAnalyzer  (Beveridge gap, quits momentum)
  · ClaimsCycleDetector (4wk MA, YoY claims)
  · Payroll (NFP growth, revisions) [placeholder in v1.0]

Produce un composite_score [-1, 1] e un regime categorico:
  tight       - mercato molto forte (bassa disoccupazione, alta mobilità)
  balanced    - mercato equilibrato
  slack       - eccesso di offerta di lavoro
  deteriorating - segnali di peggioramento in atto

Il composite_score viene usato dal CompositeSignalAggregator v2.
Persiste in labour_regime (DuckDB, migration 009).

Regola 8: numpy per tutti i calcoli.
Regola 13: persiste in labour_regime.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, UTC, datetime
from typing import Literal, TYPE_CHECKING

import numpy as np
import structlog

if TYPE_CHECKING:
    from engine.analytics.labour_market.jolts_analyzer import JOLTSSignal
    from engine.analytics.labour_market.claims_cycle_detector import ClaimsCycleSignal

__version__ = "1.0.0"
log = structlog.get_logger(__name__)

LabourRegime = Literal["tight", "balanced", "slack", "deteriorating"]

# Pesi per il composite score (somma = 1.0)
_WEIGHT_JOLTS   = 0.45   # JOLTS: strutturale, aggiornato mensilmente
_WEIGHT_CLAIMS  = 0.40   # Claims: high-frequency, aggiornato settimanalmente
_WEIGHT_PAYROLL = 0.15   # Payroll: placeholder, verrà aggiornato con PayrollDecomposer

# Soglie composite per regime
_TIGHT_SCORE_MIN        =  0.35
_DETERIORATING_SCORE_MAX= -0.25
_BALANCED_MIN           = -0.25
_BALANCED_MAX           =  0.35


@dataclass(frozen=True)
class LabourRegimeResult:
    """Risultato classificazione regime mercato del lavoro."""

    snapshot_date:   date
    regime:          LabourRegime
    composite_score: float    # [-1, 1]
    jolts_score:     float    # Contributo JOLTS
    claims_score:    float    # Contributo Claims
    payroll_score:   float    # Contributo Payroll (0.0 in v1.0)
    confidence:      float    # [0, 1] affidabilità


class LabourRegimeClassifier:
    """Classifica il regime del mercato del lavoro da segnali multipli.

    Aggrega JOLTSSignal + ClaimsCycleSignal in un composite score.
    """

    def __init__(self, duckdb=None) -> None:
        self._duckdb = duckdb

    def classify(
        self,
        jolts: JOLTSSignal,
        claims: ClaimsCycleSignal,
        payroll_score: float = 0.0,
    ) -> LabourRegimeResult:
        """Calcola il regime aggregato.

        Args:
            jolts:         Output di JOLTSAnalyzer.analyze()
            claims:        Output di ClaimsCycleDetector.detect()
            payroll_score: Score [-1,1] da PayrollDecomposer (0 in v1.0)

        Returns:
            LabourRegimeResult con regime categorico e composite_score.
        """
        jolts_s   = float(np.clip(jolts.labour_score, -1.0, 1.0))
        claims_s  = float(np.clip(claims.signal_strength, -1.0, 1.0))
        payroll_s = float(np.clip(payroll_score, -1.0, 1.0))

        # Composite score pesato
        composite = float(
            jolts_s   * _WEIGHT_JOLTS +
            claims_s  * _WEIGHT_CLAIMS +
            payroll_s * _WEIGHT_PAYROLL
        )
        composite = float(np.clip(composite, -1.0, 1.0))

        # Regime da composite score
        if composite >= _TIGHT_SCORE_MIN:
            regime: LabourRegime = "tight"
        elif composite <= _DETERIORATING_SCORE_MAX:
            regime = "deteriorating"
        elif _BALANCED_MIN <= composite < _BALANCED_MAX:
            regime = "balanced"
        else:
            regime = "slack"

        # Confidence: alta se tutti i segnali concordano
        scores_arr = np.array([jolts_s, claims_s, payroll_s], dtype=np.float64)
        signs      = np.sign(scores_arr)
        agreement  = float(np.mean(signs == signs[0]))  # % segnali concordi
        confidence = float(np.clip(agreement * 0.8 + abs(composite) * 0.2, 0.0, 1.0))

        result = LabourRegimeResult(
            snapshot_date=date.today(),
            regime=regime,
            composite_score=round(composite, 4),
            jolts_score=round(jolts_s, 4),
            claims_score=round(claims_s, 4),
            payroll_score=round(payroll_s, 4),
            confidence=round(confidence, 3),
        )

        if self._duckdb is not None:
            self._persist(result)

        log.info(
            "labour_regime.classified",
            regime=regime,
            composite=round(composite, 3),
            jolts=round(jolts_s, 3),
            claims=round(claims_s, 3),
            confidence=round(confidence, 3),
        )
        return result

    def _persist(self, r: LabourRegimeResult) -> None:
        """Persiste il regime in labour_regime DuckDB."""
        if self._duckdb is None:
            return
        try:
            self._duckdb.execute(
                """INSERT OR REPLACE INTO labour_regime
                   (snapshot_date, regime, composite_score, jolts_score,
                    claims_score, payroll_score, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    r.snapshot_date,
                    r.regime,
                    r.composite_score,
                    r.jolts_score,
                    r.claims_score,
                    r.payroll_score,
                    r.confidence,
                ],
            )
        except Exception as exc:  # noqa: BLE001
            log.error("labour_regime.persist_failed", error=str(exc))
