"""CompositeSignalAggregatorV3 — Roadmap v3.0 Settimana 7.

Estende CompositeSignalAggregator v2 con il componente di Pattern Recognition
(da pattern_signals, migration 013).

Nuovi pesi v3 (somma = 1.00 ✓):
  vix:            0.20  (ridotto da 0.22)
  macro:          0.18  (ridotto da 0.20)
  yield_curve:    0.18  (invariato)
  credit:         0.13  (invariato)
  claims:         0.07  (ridotto da 0.08)
  labour_market:  0.12  (invariato)
  surprise:       0.07  (invariato)
  pattern:        0.05  ★ NUOVO — da pattern_signals (migration 013)
  ──────────────────────────────────────────────
  Totale:         1.00 ✓

Il segnale pattern è calcolato come media pesata per confidence dei pattern
attivi nelle ultime 7 giorni:
  BULLISH pattern → +confidence  (es. H&S Inverse: +0.78)
  BEARISH pattern → -confidence  (es. Double Top: -0.82)
  NEUTRAL pattern →  0.0         (es. Symmetric Triangle)

Regola 2 (SRP): aggrega segnali esistenti — non li calcola.
Regola 8: numpy per tutti i calcoli numerici.
Regola 27: persiste in engine_composite_signal (migration 007, tabella esistente).

ANTI-REGRESSIONE:
  · I pesi DEVONO sommare a 1.00 — verificato con assert all'import.
  · _read_pattern_component() usa lookback 7 giorni per evitare pattern stale.
    Pattern più vecchi di 7 giorni hanno status='EXPIRED' (set da expire_old()).
  · La logica di action/confidence è identica alla v2 — non cambiare soglie
    senza aggiornare anche test_composite_signal_v2.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np

from engine.alpha_generation.composite_signal_aggregator import (
    CompositeSignalAggregator,
    CompositeSignalOutput,
    _BUY_THRESHOLD,
    _REDUCE_THRESHOLD,
)
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient
    from shared.db.macro_repo import MacroRepository

__version__ = "3.1.0"
__all__ = ["CompositeSignalAggregatorV3", "CompositeSignalOutputV3"]

log = get_logger(__name__)

# Pesi v3.1: somma = 1.00 (Regola 8 — verifica numerica)
# Rispetto a v2.1: distribuisce peso tra i 10 componenti
# includendo valuation e correlation dai Blocchi 3/4.
_WEIGHTS_V3: dict[str, float] = {
    "vix":           0.16,
    "macro":         0.16,
    "yield_curve":   0.15,
    "credit":        0.11,
    "claims":        0.06,
    "labour_market": 0.11,
    "surprise":      0.06,
    "valuation":     0.09,   # da v2.1 Blocco 3 — ValuationSignalGenerator
    "correlation":   0.04,   # da v2.1 Blocco 4 — CrossAssetMatrix
    "pattern":       0.06,   # ★ v3.0 — Pattern Recognition
}
# ANTI-REGRESSIONE: se la somma non è 1.0, il file non si importa
assert abs(sum(_WEIGHTS_V3.values()) - 1.0) < 1e-9, (
    f"_WEIGHTS_V3 deve sommare a 1.0, attuale: {sum(_WEIGHTS_V3.values())}"
)

# Finestra per pattern attivi (giorni)
_PATTERN_LOOKBACK_DAYS: int = 7


@dataclass(frozen=True)
class CompositeSignalOutputV3:
    """Output del CompositeSignalAggregatorV3 — estende v2 con pattern."""

    # Eredita tutti i campi dalla v2 come attributo
    v2_output:             CompositeSignalOutput

    # Componente aggiuntivo v3
    pattern_component:     float                    # contributo Pattern Recognition
    pattern_count:         int                      # n. pattern attivi usati
    pattern_breakdown:     dict[str, float] = field(default_factory=dict)

    # Ricalcolato con pesi v3
    composite_score_v3:    float = 0.0
    recommended_action_v3: str   = "HOLD"
    confidence_v3:         str   = "LOW"
    breakdown_json_v3:     str   = "{}"

    @property
    def computed_at(self) -> datetime:
        return self.v2_output.computed_at

    @property
    def components_used(self) -> list[str]:
        return self.v2_output.components_used + (
            ["pattern"] if self.pattern_component != 0.0 else []
        )


class CompositeSignalAggregatorV3(CompositeSignalAggregator):
    """Aggrega segnali v2 + pattern recognition in composite score [-1, +1].

    Eredita tutti i lettori di componenti dalla v2; sovrascrive compute()
    per aggiungere il pattern component e usare _WEIGHTS_V3.

    Non ricalcola i segnali — li legge dal DB (come la v2).
    """

    def __init__(
        self,
        duckdb:     DuckDBClient,
        macro_repo: MacroRepository | None = None,
    ) -> None:
        super().__init__(duckdb=duckdb, macro_repo=macro_repo)

    def compute(self) -> CompositeSignalOutputV3:  # type: ignore[override]
        """Calcola il composite score v3 con pattern component.

        Returns:
            CompositeSignalOutputV3 con score aggiornato, breakdown v3
            e tutti i campi della v2 nel campo v2_output.
        """
        # Step 1: calcola tutti i componenti v2 (riusa la v2)
        v2 = super().compute()

        # Ricostruisce il dict components dalla v2
        components: dict[str, float] = {}
        if v2.vix_component != 0.0 or "vix" in v2.components_used:
            components["vix"] = v2.vix_component
        if v2.macro_component != 0.0 or "macro" in v2.components_used:
            components["macro"] = v2.macro_component
        if v2.yield_curve_component != 0.0 or "yield_curve" in v2.components_used:
            components["yield_curve"] = v2.yield_curve_component
        if v2.credit_component != 0.0 or "credit" in v2.components_used:
            components["credit"] = v2.credit_component
        if v2.claims_component != 0.0 or "claims" in v2.components_used:
            components["claims"] = v2.claims_component
        if v2.labour_market_component != 0.0 or "labour_market" in v2.components_used:
            components["labour_market"] = v2.labour_market_component
        if v2.surprise_component != 0.0 or "surprise" in v2.components_used:
            components["surprise"] = v2.surprise_component
        # v2.1 Blocco 3/4 — valuation e correlation
        if v2.valuation_component != 0.0 or "valuation" in v2.components_used:
            components["valuation"] = v2.valuation_component
        if v2.correlation_component != 0.0 or "correlation" in v2.components_used:
            components["correlation"] = v2.correlation_component

        # Step 2: legge pattern component
        pat_score, pat_count, pat_breakdown = self._read_pattern_component()
        if pat_score is not None:
            components["pattern"] = pat_score

        # Step 3: ricalcola con _WEIGHTS_V3
        total_weight = sum(_WEIGHTS_V3[k] for k in components if k in _WEIGHTS_V3)
        if total_weight > 0:
            composite = float(
                sum(components[k] * _WEIGHTS_V3[k]
                    for k in components if k in _WEIGHTS_V3) / total_weight
            )
        else:
            composite = 0.0

        composite = float(np.clip(composite, -1.0, 1.0))

        # Step 4: action e confidence (stesse soglie v2)
        if composite >= _BUY_THRESHOLD:
            action = "BUY"
            confidence = "HIGH" if composite >= 0.50 else "MEDIUM"
        elif composite <= _REDUCE_THRESHOLD:
            action = "REDUCE"
            confidence = "HIGH" if composite <= -0.50 else "MEDIUM"
        else:
            action = "HOLD"
            confidence = "LOW"

        if len(components) < 3:
            confidence = "LOW"
        elif len(components) < 4 and confidence == "HIGH":
            confidence = "MEDIUM"

        # Step 5: breakdown v3
        breakdown_v3 = {k: round(v, 4) for k, v in components.items()}
        breakdown_json_v3 = json.dumps(breakdown_v3)

        # Step 6: persisti con pattern_component
        self._persist_v3(
            computed_at=v2.computed_at,
            composite=composite,
            action=action,
            confidence=confidence,
            components=breakdown_v3,
            v2=v2,
        )

        log.info(
            "composite_v3.done",
            composite=round(composite, 3),
            action=action,
            pattern_count=pat_count,
            pattern_score=round(pat_score, 3) if pat_score is not None else None,
            delta_from_v2=round(composite - v2.composite_score, 3),
        )

        return CompositeSignalOutputV3(
            v2_output=v2,
            pattern_component=pat_score or 0.0,
            pattern_count=pat_count,
            pattern_breakdown=pat_breakdown,
            composite_score_v3=composite,
            recommended_action_v3=action,
            confidence_v3=confidence,
            breakdown_json_v3=breakdown_json_v3,
        )

    # ─── Pattern Component ───────────────────────────────────────────────────

    def _read_pattern_component(
        self,
    ) -> tuple[float | None, int, dict[str, float]]:
        """Legge i pattern attivi dagli ultimi 7 giorni e calcola il segnale.

        Formula:
          score_i = +confidence  se signal_dir = 'bullish'
          score_i = -confidence  se signal_dir = 'bearish'
          score_i =  0.0         se signal_dir = 'neutral'
          pattern_component = clip(mean(score_i), -1, 1)

        Returns:
            (score, n_patterns_used, {pattern_type: score_i})
        """
        try:
            # ANTI-REGRESSIONE: DuckDB non accetta '?' dentro INTERVAL().
            # _PATTERN_LOOKBACK_DAYS è una costante Python (int) — non input utente
            # → f-string è sicura (nessun rischio SQL injection da input esterno).
            rows = self._db.query(
                f"""
                SELECT pattern_type, signal_dir, confidence
                FROM pattern_signals
                WHERE status = 'ACTIVE'
                AND detected_at >= NOW() - INTERVAL '{_PATTERN_LOOKBACK_DAYS} days'
                ORDER BY confidence DESC
                LIMIT 20
                """
            )
        except Exception as exc:
            log.debug("composite_v3.pattern_read_failed", error=str(exc)[:80])
            return None, 0, {}

        if not rows:
            return None, 0, {}

        scores: list[float] = []
        breakdown: dict[str, float] = {}

        for pat_type, signal_dir, confidence in rows:
            c = float(confidence)
            if signal_dir == "bullish":
                s = c
            elif signal_dir == "bearish":
                s = -c
            else:
                s = 0.0
            scores.append(s)
            # Se più pattern dello stesso tipo → teniamo la media
            breakdown[str(pat_type)] = breakdown.get(str(pat_type), s)

        if not scores:
            return None, 0, {}

        score_arr = np.array(scores, dtype=np.float64)
        final = float(np.clip(np.mean(score_arr), -1.0, 1.0))
        return final, len(scores), breakdown

    # ─── Persist v3 ──────────────────────────────────────────────────────────

    def _persist_v3(
        self,
        computed_at: datetime,
        composite: float,
        action: str,
        confidence: str,
        components: dict[str, float],
        v2: CompositeSignalOutput,
    ) -> None:
        """Persiste il segnale v3 sovrascrivendo la riga v2 con il composite aggiornato.

        Usa la stessa tabella engine_composite_signal (migration 007) per
        compatibilità con la UI esistente. Il breakdown_json include il pattern.
        """
        try:
            self._db.execute(
                """
                INSERT OR REPLACE INTO engine_composite_signal
                (computed_at, composite_score, recommended_action, confidence,
                 regime, credit_stress, claims_regime, yield_curve_regime,
                 component_breakdown_json, vix_component, macro_component,
                 yield_curve_component, credit_component, claims_component)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    computed_at, composite, action, confidence,
                    v2.regime, v2.credit_stress, v2.claims_regime,
                    v2.yield_curve_regime, json.dumps(components),
                    components.get("vix", 0.0),
                    components.get("macro", 0.0),
                    components.get("yield_curve", 0.0),
                    components.get("credit", 0.0),
                    components.get("claims", 0.0),
                ],
            )
        except Exception as exc:
            log.warning("composite_v3.persist_failed", error=str(exc)[:100])
