"""CompositeSignalAggregator — Settimana 8 Roadmap Unificata.

Aggrega tutti i segnali dell'engine in un unico score [-1, +1]
con azione raccomandata e confidence.

Pesi (da Roadmap Unificata §Settimana 8):
  vix:         0.30
  macro:       0.25
  yield_curve: 0.20
  credit:      0.15
  claims:      0.10

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

__version__ = "1.0.0"
__all__ = ["CompositeSignalAggregator", "CompositeSignalOutput"]

log = get_logger(__name__)

_WEIGHTS: dict[str, float] = {
    "vix":         0.30,
    "macro":       0.25,
    "yield_curve": 0.20,
    "credit":      0.15,
    "claims":      0.10,
}

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
        components_used:    Lista componenti effettivamente disponibili.
        regime:             Regime HMM corrente (può essere None).
        credit_stress:      Livello stress credito.
        claims_regime:      Regime claims/inflation.
        yield_curve_regime: Regime curva yield.
        breakdown_json:     JSON con dettaglio componenti per UI.
    """
    computed_at:          datetime
    composite_score:      float
    recommended_action:   str
    confidence:           str
    vix_component:        float
    macro_component:      float
    yield_curve_component:float
    credit_component:     float
    claims_component:     float
    components_used:      list[str]
    regime:               str | None
    credit_stress:        str | None
    claims_regime:        str | None
    yield_curve_regime:   str | None
    breakdown_json:       str


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

        # ── 4. Regime HMM corrente ────────────────────────────────────────
        meta["regime"] = self._read_current_regime()

        # ── 5. Aggregazione pesata ────────────────────────────────────────
        total_weight = sum(_WEIGHTS[k] for k in components if k in _WEIGHTS)
        if total_weight > 0:
            composite = float(
                sum(components[k] * _WEIGHTS[k]
                    for k in components if k in _WEIGHTS) / total_weight
            )
        else:
            composite = 0.0

        composite = float(np.clip(composite, -1.0, 1.0))

        # ── 6. Action e confidence ────────────────────────────────────────
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

        # ── 7. Breakdown JSON per UI ──────────────────────────────────────
        breakdown = {k: round(v, 4) for k, v in components.items()}
        breakdown_json = json.dumps(breakdown)

        # ── 8. Costruzione output ─────────────────────────────────────────
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
            components_used=list(components.keys()),
            regime=meta["regime"],
            credit_stress=meta["credit_stress"],
            claims_regime=meta["claims_regime"],
            yield_curve_regime=meta["yield_curve_regime"],
            breakdown_json=breakdown_json,
        )

        # ── 9. Persist ────────────────────────────────────────────────────
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
