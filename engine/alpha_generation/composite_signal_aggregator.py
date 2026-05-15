"""CompositeSignalAggregator v2.1 — ROADMAP_ANALISI_MERCATO_v4.

Aggrega tutti i segnali dell'engine in un unico score [-1, +1]
con azione raccomandata e confidence.

Pesi v2.1 (aggiornati per includere valuation e correlation — Blocco 3/4):
  vix:            0.18   (era 0.22)
  macro:          0.17   (era 0.20)
  yield_curve:    0.15   (era 0.18)
  credit:         0.11   (era 0.13)
  claims:         0.07   (era 0.08)
  labour_market:  0.10   (era 0.12)
  surprise:       0.05   (era 0.07)
  valuation:      0.12   ★ NUOVO v2.1 — da ValuationSignalGenerator
  correlation:    0.05   ★ NUOVO v2.1 — da CrossAssetMatrix

Somma pesi: 1.00 ✓

Azione finale:
  composite > +0.3 → BUY  (HIGH se > 0.5)
  composite < -0.3 → REDUCE (HIGH se < -0.5)
  altrimenti       → HOLD (LOW)

Regola 2 (SRP): aggrega, non calcola singoli segnali.
Regola 8: numpy per tutti i calcoli numerici.
Regola 27: persiste in engine_composite_signal (migration 007).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np

from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient
    from shared.db.macro_repo import MacroRepository

__version__ = "2.1.0"  # Blocco 3/4: + valuation + correlation
__all__ = ["CompositeSignalAggregator", "CompositeSignalOutput"]

log = get_logger(__name__)

_WEIGHTS: dict[str, float] = {
    "vix":           0.18,
    "macro":         0.17,
    "yield_curve":   0.15,
    "credit":        0.11,
    "claims":        0.07,
    "labour_market": 0.10,   # Blocco D: da LabourRegimeClassifier
    "surprise":      0.05,   # Blocco D: da SurpriseSignalGenerator
    "valuation":     0.12,   # ★ v2.1 Blocco 3: da ValuationSignalGenerator
    "correlation":   0.05,   # ★ v2.1 Blocco 4: da CrossAssetMatrix
}
# Sanity check: pesi sommano a 1.0 (testato in test_composite_signal_v2.py)
assert abs(sum(_WEIGHTS.values()) - 1.0) < 1e-9, "WEIGHTS must sum to 1.0"

_BUY_THRESHOLD    =  0.30
_REDUCE_THRESHOLD = -0.30


@dataclass(frozen=True)
class CompositeSignalOutput:
    """Output aggregato del CompositeSignalAggregator.

    Attributes:
        computed_at:        Timestamp UTC.
        composite_score:    Score [-1, +1].
        recommended_action: 'BUY' | 'HOLD' | 'REDUCE'.
        confidence:         'HIGH' | 'MEDIUM' | 'LOW'.
        vix_component:      Contributo VIX pesato.
        macro_component:    Contributo Macro pesato.
        yield_curve_component: Contributo Yield Curve pesato.
        credit_component:   Contributo Credit pesato.
        claims_component:   Contributo Claims pesato.
        labour_market_component: Contributo Labour Market (v2.0).
        surprise_component: Contributo Economic Surprise (v2.0).
        components_used:    Lista componenti effettivamente disponibili.
        regime:             Regime HMM corrente (può essere None).
        credit_stress:      Livello stress credito.
        claims_regime:      Regime claims/inflation.
        yield_curve_regime: Regime curva yield.
        breakdown_json:     JSON con dettaglio componenti per UI.
    """
    computed_at:             datetime
    composite_score:         float
    recommended_action:      str
    confidence:              str
    vix_component:           float
    macro_component:         float
    yield_curve_component:   float
    credit_component:        float
    claims_component:        float
    labour_market_component: float           # ★ v2.0
    surprise_component:      float           # ★ v2.0
    components_used:         list[str]
    regime:                  str | None
    credit_stress:           str | None
    claims_regime:           str | None
    yield_curve_regime:      str | None
    breakdown_json:          str
    valuation_component:     float = 0.0    # ★ v2.1 Blocco 3
    correlation_component:   float = 0.0    # ★ v2.1 Blocco 4
    is_degraded:             bool  = False

    @classmethod
    def degraded(cls, error_reason: str = "unavailable") -> CompositeSignalOutput:
        """Costruisce un output sentinel quando il calcolo non è possibile."""
        from datetime import datetime, timezone
        return cls(
            computed_at=datetime.now(timezone.utc),
            composite_score=0.0,
            recommended_action="HOLD",
            confidence="LOW",
            vix_component=0.0,
            macro_component=0.0,
            yield_curve_component=0.0,
            credit_component=0.0,
            claims_component=0.0,
            labour_market_component=0.0,
            surprise_component=0.0,
            valuation_component=0.0,
            correlation_component=0.0,
            components_used=[],
            regime=None,
            credit_stress=None,
            claims_regime=None,
            yield_curve_regime=None,
            breakdown_json=f'{{"error": "{error_reason}"}}',
            is_degraded=True,
        )


class CompositeSignalAggregator:
    """Aggrega tutti i segnali engine in composite_score [-1, +1].

    Legge i segnali già calcolati e persistiti in DuckDB dallo scheduler
    (vix_strategy_outputs, claims_inflation_signals, yield_curve_snapshots,
    credit_spread_signals, regime_reports).

    Non ricalcola i segnali — li legge e li aggrega.
    Benchmark target: compute() < 200ms (Rule 30).

    Usage::

        agg = CompositeSignalAggregator(duckdb=get_duckdb_client())
        output = agg.compute()
    """

    def __init__(
        self,
        duckdb:     DuckDBClient,
        macro_repo: MacroRepository | None = None,
    ) -> None:
        self._db        = duckdb
        self._macro_repo = macro_repo

    def compute(self) -> CompositeSignalOutput:
        """Legge tutti i segnali dal DB e calcola il composite score.

        Returns:
            CompositeSignalOutput con score, action, confidence e breakdown.
        """
        components: dict[str, float] = {}
        meta: dict[str, str | None] = {
            "regime": None,
            "credit_stress": None,
            "claims_regime": None,
            "yield_curve_regime": None,
        }

        # ── 1. VIX component ──────────────────────────────────────────────
        vix_comp = self._read_vix_component()
        if vix_comp is not None:
            components["vix"] = vix_comp

        # ── 2. Macro (yield + claims) components ──────────────────────────
        yc_comp, yc_regime = self._read_yield_curve_component()
        if yc_comp is not None:
            components["yield_curve"] = yc_comp
            meta["yield_curve_regime"] = yc_regime

        cr_comp, cr_stress = self._read_credit_component()
        if cr_comp is not None:
            components["credit"] = cr_comp
            meta["credit_stress"] = cr_stress

        cl_comp, cl_regime = self._read_claims_component()
        if cl_comp is not None:
            components["claims"] = cl_comp
            meta["claims_regime"] = cl_regime

        # ── 3. Macro conviction (se MacroRepository disponibile) ──────────
        macro_comp = self._read_macro_conviction_component()
        if macro_comp is not None:
            components["macro"] = macro_comp

        # ── 4. Labour Market component (v2.0) ─────────────────────────────
        labour_comp = self._read_labour_component()
        if labour_comp is not None:
            components["labour_market"] = labour_comp

        # ── 5. Economic Surprise component (v2.0) ─────────────────────────
        surprise_comp = self._read_surprise_component()
        if surprise_comp is not None:
            components["surprise"] = surprise_comp

        # ── 6. Valuation component (v2.1) ─────────────────────────────────
        val_comp = self._read_valuation_component()
        if val_comp is not None:
            components["valuation"] = val_comp

        # ── 7. Correlation component (v2.1) ───────────────────────────────
        corr_comp = self._read_correlation_component()
        if corr_comp is not None:
            components["correlation"] = corr_comp

        # ── 8. Regime HMM corrente ────────────────────────────────────────
        meta["regime"] = self._read_current_regime()

        # ── 9. Aggregazione pesata ────────────────────────────────────────
        total_weight = sum(_WEIGHTS[k] for k in components if k in _WEIGHTS)
        if total_weight > 0:
            composite = float(
                sum(components[k] * _WEIGHTS[k]
                    for k in components if k in _WEIGHTS) / total_weight
            )
        else:
            composite = 0.0

        composite = float(np.clip(composite, -1.0, 1.0))

        # ── 10. Action e confidence ───────────────────────────────────────
        if composite >= _BUY_THRESHOLD:
            action = "BUY"
            confidence = "HIGH" if composite >= 0.50 else "MEDIUM"
        elif composite <= _REDUCE_THRESHOLD:
            action = "REDUCE"
            confidence = "HIGH" if composite <= -0.50 else "MEDIUM"
        else:
            action = "HOLD"
            confidence = "LOW"

        # Degradiamo confidence se pochi componenti
        if len(components) < 3:
            confidence = "LOW"
        elif len(components) < 4 and confidence == "HIGH":
            confidence = "MEDIUM"

        # ── 11. Breakdown JSON per UI ─────────────────────────────────────
        breakdown = {k: round(v, 4) for k, v in components.items()}
        breakdown_json = json.dumps(breakdown)

        # ── 12. Costruzione output ─────────────────────────────────────────
        output = CompositeSignalOutput(
            computed_at=datetime.now(UTC),
            composite_score=composite,
            recommended_action=action,
            confidence=confidence,
            vix_component=components.get("vix", 0.0),
            macro_component=components.get("macro", 0.0),
            yield_curve_component=components.get("yield_curve", 0.0),
            credit_component=components.get("credit", 0.0),
            claims_component=components.get("claims", 0.0),
            labour_market_component=components.get("labour_market", 0.0),
            surprise_component=components.get("surprise", 0.0),
            valuation_component=components.get("valuation", 0.0),
            correlation_component=components.get("correlation", 0.0),
            components_used=list(components.keys()),
            regime=meta["regime"],
            credit_stress=meta["credit_stress"],
            claims_regime=meta["claims_regime"],
            yield_curve_regime=meta["yield_curve_regime"],
            breakdown_json=breakdown_json,
        )

        # ── 13. Persist ───────────────────────────────────────────────────
        self._persist(output)

        log.info(
            "composite_aggregator.done",
            composite=round(composite, 3),
            action=action,
            confidence=confidence,
            components=list(components.keys()),
            regime=meta["regime"],
        )
        return output

    # ─── Lettura componenti ───────────────────────────────────────────────

    def _read_vix_component(self) -> float | None:
        """Legge l'ultimo VIX signal e lo converte in [-1, +1]."""
        try:
            rows = self._db.query(
                "SELECT vix_signal, action FROM vix_strategy_outputs "
                "ORDER BY computed_at DESC LIMIT 1"
            )
            if not rows:
                return None
            vix_score = float(rows[0][0]) if rows[0][0] is not None else 0.5
            action    = str(rows[0][1])
            direction = {"BUY": 1.0, "HOLD": 0.0, "REDUCE": -1.0}.get(action, 0.0)
            # vix_signal [0,1] → [-1,+1] con segno dall'action
            if action == "BUY":
                return float(np.clip((vix_score * 2 - 1) * direction, -1, 1))
            elif action == "REDUCE":
                return float(np.clip(-vix_score, -1, 0))
            return 0.0
        except Exception as exc:
            log.debug("composite.vix_read_failed", error=str(exc)[:60])
            return None

    def _read_yield_curve_component(self) -> tuple[float | None, str | None]:
        """Legge recession_prob e curva regime → score [-1,+1]."""
        try:
            rows = self._db.query(
                "SELECT recession_prob_12m, curve_regime "
                "FROM yield_curve_snapshots ORDER BY snapshot_date DESC LIMIT 1"
            )
            if not rows or rows[0][0] is None:
                return None, None
            prob   = float(rows[0][0])
            regime = str(rows[0][1]) if rows[0][1] else None
            # P=0 → score +1 (no recessione), P=1 → score -1
            score  = float(1.0 - 2.0 * prob)
            return float(np.clip(score, -1, 1)), regime
        except Exception as exc:
            log.debug("composite.yield_curve_read_failed", error=str(exc)[:60])
            return None, None

    def _read_credit_component(self) -> tuple[float | None, str | None]:
        """Legge stress_score e stress_level."""
        try:
            rows = self._db.query(
                "SELECT stress_score, stress_level FROM credit_spread_signals "
                "ORDER BY computed_at DESC LIMIT 1"
            )
            if not rows:
                return None, None
            score = float(rows[0][0]) if rows[0][0] is not None else 0.0
            level = str(rows[0][1]) if rows[0][1] else None
            return float(np.clip(score, -1, 1)), level
        except Exception as exc:
            log.debug("composite.credit_read_failed", error=str(exc)[:60])
            return None, None

    def _read_claims_component(self) -> tuple[float | None, str | None]:
        """Legge regime_score e regime_label dalla tabella claims."""
        try:
            rows = self._db.query(
                "SELECT regime_score, regime_label FROM claims_inflation_signals "
                "ORDER BY computed_at DESC LIMIT 1"
            )
            if not rows:
                return None, None
            score  = float(rows[0][0]) if rows[0][0] is not None else 0.0
            regime = str(rows[0][1]) if rows[0][1] else None
            return float(np.clip(score, -1, 1)), regime
        except Exception as exc:
            log.debug("composite.claims_read_failed", error=str(exc)[:60])
            return None, None

    def _read_macro_conviction_component(self) -> float | None:
        """Legge macro_score dal MacroRepository se disponibile."""
        if self._macro_repo is None:
            return None
        try:
            from engine.alpha_generation.macro_conviction import MacroConvictionCalculator
            calc   = MacroConvictionCalculator(macro_repo=self._macro_repo)
            result = calc.compute()
            return float(np.clip(result.macro_score, -1, 1))
        except Exception as exc:
            log.debug("composite.macro_calc_failed", error=str(exc)[:60])
            return None

    def _read_labour_component(self) -> float | None:
        """Legge il composite_score da labour_regime (migration 009).

        v2.0: usa il LabourRegimeClassifier score come componente.
        """
        try:
            rows = self._db.query(
                "SELECT composite_score FROM labour_regime "
                "ORDER BY snapshot_date DESC LIMIT 1"
            )
            if not rows or rows[0][0] is None:
                return None
            return float(np.clip(rows[0][0], -1.0, 1.0))
        except Exception as exc:
            log.debug("composite.labour_read_failed", error=str(exc)[:60])
            return None

    def _read_surprise_component(self) -> float | None:
        """Legge signal_value da surprise_signal (migration 010).

        v2.0: Economic Surprise Engine segnale aggregato.
        """
        try:
            rows = self._db.query(
                "SELECT signal_value FROM surprise_signal "
                "ORDER BY generated_at DESC LIMIT 1"
            )
            if not rows or rows[0][0] is None:
                return None
            return float(np.clip(rows[0][0], -1.0, 1.0))
        except Exception as exc:
            log.debug("composite.surprise_read_failed", error=str(exc)[:60])
            return None

    def _read_valuation_component(self) -> float | None:
        """Legge valuation_score da valuation_signal (migration 018).

        v2.1: score già normalizzato [-1,+1] da ValuationSignalGenerator.
        """
        try:
            rows = self._db.query(
                "SELECT valuation_score FROM valuation_signal "
                "ORDER BY signal_date DESC LIMIT 1"
            )
            if not rows or rows[0][0] is None:
                return None
            return float(np.clip(rows[0][0], -1.0, 1.0))
        except Exception as exc:
            log.debug("composite.valuation_read_failed", error=str(exc)[:60])
            return None

    def _read_correlation_component(self) -> float | None:
        """Legge correlation_signal da cross_asset_regime (migration 019).

        v2.1: score già normalizzato [-1,+1] da CrossAssetMatrix.
        """
        try:
            rows = self._db.query(
                "SELECT correlation_signal FROM cross_asset_regime "
                "ORDER BY regime_date DESC LIMIT 1"
            )
            if not rows or rows[0][0] is None:
                return None
            return float(np.clip(rows[0][0], -1.0, 1.0))
        except Exception as exc:
            log.debug("composite.correlation_read_failed", error=str(exc)[:60])
            return None

    def _read_current_regime(self) -> str | None:
        """Legge il regime HMM più recente."""
        try:
            rows = self._db.query(
                "SELECT regime FROM regime_reports "
                "ORDER BY computed_at DESC LIMIT 1"
            )
            return str(rows[0][0]) if rows and rows[0][0] else None
        except Exception:
            return None

    def _persist(self, output: CompositeSignalOutput) -> None:
        """Persiste in engine_composite_signal (migration 007)."""
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO engine_composite_signal "
                "(computed_at, composite_score, recommended_action, confidence, "
                "regime, credit_stress, claims_regime, yield_curve_regime, "
                "component_breakdown_json, vix_component, macro_component, "
                "yield_curve_component, credit_component, claims_component) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [output.computed_at, output.composite_score, output.recommended_action,
                 output.confidence, output.regime, output.credit_stress,
                 output.claims_regime, output.yield_curve_regime, output.breakdown_json,
                 output.vix_component, output.macro_component,
                 output.yield_curve_component, output.credit_component,
                 output.claims_component],
            )
        except Exception as exc:
            log.warning("composite.persist_failed", error=str(exc)[:100])
