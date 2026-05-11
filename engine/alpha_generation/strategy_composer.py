"""StrategyComposer — Settimana 4 Roadmap Unificata.

Combina il segnale VIX (timing) con MacroConviction (bias direzionale)
in un output aggregato con action e position_size.

Pesi default:
  vix_signal:  0.60  (timing — più reattivo)
  macro_score: 0.40  (bias — più stabile)

Logica position sizing:
  composite_score → position_size_pct via funzione sigmoide smussata.
  composite_score = 0.5 → size 50% (neutro)
  composite_score = 1.0 → size 80% (massimo per profilo moderato)
  composite_score = 0.0 → size 20% (minimo difensivo)

Lettura regime HMM:
  StrategyComposer._get_current_regime() legge da regime_reports DuckDB.
  Se DB vuoto → regime = None (nessun aggiustamento VIX threshold).
  Con DB vuoto non crasha (Rule 5 — eccezioni custom).

Regola 2 (SRP): aggrega VIX + Macro — non implementa nessuno dei due.
Regola 22: InvestorProfile filtra il position_size_pct massimo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np

from shared.logger import get_logger

if TYPE_CHECKING:
    from engine.alpha_generation.macro_conviction import MacroConvictionCalculator
    from engine.alpha_generation.schemas import MacroConvictionResult
    from engine.alpha_generation.vix_signal_calculator import VixSignal, VixSignalCalculator
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["StrategyComposer", "StrategyOutput"]

log = get_logger(__name__)

# Pesi per la composizione VIX + Macro
_VIX_WEIGHT   = 0.60
_MACRO_WEIGHT = 0.40

# Soglie action
_BUY_THRESHOLD    =  0.25
_REDUCE_THRESHOLD = -0.25

# Limiti position sizing per profilo di rischio
_MAX_SIZE_BY_PROFILE: dict[str, float] = {
    "conservative":    0.50,
    "moderate":        0.70,
    "aggressive":      0.85,
    "very_aggressive": 1.00,
}


@dataclass(frozen=True)
class StrategyOutput:
    """Output del StrategyComposer.

    Attributes:
        computed_at:       Timestamp UTC.
        action:            'BUY' | 'HOLD' | 'REDUCE'.
        composite_score:   Score composito [-1, +1] (VIX*0.6 + Macro*0.4).
        confidence:        'HIGH' | 'MEDIUM' | 'LOW'.
        position_size_pct: Frazione del portafoglio consigliata [0, 1].
        vix_signal:        VixSignal di input.
        macro_score:       macro_score del MacroConvictionResult (None se non disponibile).
        regime_used:       Regime HMM usato.
        vix_component:     Contributo VIX al composite (già pesato).
        macro_component:   Contributo Macro al composite (già pesato).
        notes:             Testo esplicativo per UI.
    """
    computed_at:       datetime
    action:            str
    composite_score:   float
    confidence:        str
    position_size_pct: float
    vix_signal:        VixSignal
    macro_score:       float | None
    regime_used:       str | None
    vix_component:     float
    macro_component:   float
    notes:             str


class StrategyComposer:
    """Aggrega VIX timing signal + MacroConviction bias in un output di trading.

    Usage::

        composer = StrategyComposer(
            vix_calculator=VixSignalCalculator(prices_repo),
            macro_calculator=MacroConvictionCalculator(macro_repo),
            duckdb=get_duckdb_client(),
            profile_risk="moderate",
        )
        output = composer.run()
    """

    def __init__(
        self,
        vix_calculator:   VixSignalCalculator,
        macro_calculator: MacroConvictionCalculator | None = None,
        duckdb:           DuckDBClient | None = None,
        profile_risk:     str = "moderate",
    ) -> None:
        self._vix    = vix_calculator
        self._macro  = macro_calculator
        self._duckdb = duckdb
        self._profile = profile_risk

    def run(self) -> StrategyOutput:
        """Esegue il calcolo completo VIX + Macro → StrategyOutput.

        Passi:
          1. Legge regime HMM corrente dal DB.
          2. Calcola VixSignal (regime-aware).
          3. Calcola MacroConvictionResult (se calculator disponibile).
          4. Aggrega in composite_score.
          5. Calcola position_size_pct.
          6. Persiste in vix_strategy_outputs.

        Returns:
            StrategyOutput completo.
        """
        # 1. Regime HMM corrente
        current_regime = self._get_current_regime()

        # 2. VIX signal
        vix_signal = self._vix.compute(current_regime=current_regime)

        # 3. MacroConviction (opzionale)
        macro_result: MacroConvictionResult | None = None
        macro_score_val: float | None = None
        if self._macro is not None:
            try:
                macro_result = self._macro.compute()
                macro_score_val = macro_result.macro_score
            except Exception as exc:
                log.warning("strategy_composer.macro_failed", error=str(exc)[:100])

        # 4. Composite score
        #    VIX signal score: [0, 1] → normalizza in [-1, +1]
        #    VIX action: BUY→+1 | HOLD→0 | REDUCE→-1
        vix_direction = {"BUY": 1.0, "HOLD": 0.0, "REDUCE": -1.0}[vix_signal.action]
        vix_intensity = float(vix_signal.vix_signal_score)
        vix_component_raw = float(vix_direction * vix_intensity)

        # VIX/VXV ratio modifica il segnale (backwardation conferma BUY)
        if vix_signal.vix_vxv_ratio is not None:
            if vix_signal.vix_vxv_ratio < 0.90:  # forte backwardation
                vix_component_raw = float(np.clip(vix_component_raw + 0.15, -1.0, 1.0))
            elif vix_signal.vix_vxv_ratio > 1.10:  # forte contango → attenua
                vix_component_raw = float(np.clip(vix_component_raw - 0.10, -1.0, 1.0))

        vix_component   = float(vix_component_raw * _VIX_WEIGHT)
        macro_component = float((macro_score_val or 0.0) * _MACRO_WEIGHT)

        if macro_score_val is not None:
            composite = float(np.clip(vix_component + macro_component, -1.0, 1.0))
            # Normalizza: la somma dei pesi = 1.0 solo se entrambi disponibili
        else:
            # Solo VIX: normalizza a peso intero
            composite = float(np.clip(vix_component_raw, -1.0, 1.0))

        # 5. Action finale
        if composite >= _BUY_THRESHOLD:
            action = "BUY"
        elif composite <= _REDUCE_THRESHOLD:
            action = "REDUCE"
        else:
            action = "HOLD"

        # 6. Position sizing (funzione lineare smussata)
        max_size = _MAX_SIZE_BY_PROFILE.get(self._profile, 0.70)
        if action == "BUY":
            # composite in [0.25, 1.0] → size in [40%, max_size]
            size_raw = 0.40 + (composite - 0.25) / 0.75 * (max_size - 0.40)
            position_size = float(np.clip(size_raw, 0.20, max_size))
        elif action == "REDUCE":
            # composite in [-1.0, -0.25] → size in [0%, 30%]
            size_raw = 0.30 + (composite + 0.25) / 0.75 * 0.30
            position_size = float(np.clip(size_raw, 0.0, 0.30))
        else:
            position_size = 0.50  # neutro

        # 7. Confidence combinata
        confidence = _combine_confidence(
            vix_signal.confidence,
            macro_result.confidence if macro_result else None,
        )

        notes = _build_notes(
            vix_signal, macro_score_val, composite, action, current_regime
        )

        now = datetime.now(UTC)

        # 8. Persisti in DB
        self._persist(
            computed_at=now,
            vix_signal=vix_signal,
            macro_score=macro_score_val,
            composite=composite,
            action=action,
            confidence=confidence,
            position_size=position_size,
            regime=current_regime,
        )

        log.info(
            "strategy_composer.done",
            action=action, composite=round(composite, 3),
            position_size_pct=round(position_size * 100, 1),
            regime=current_regime, confidence=confidence,
        )

        return StrategyOutput(
            computed_at=now,
            action=action,
            composite_score=composite,
            confidence=confidence,
            position_size_pct=position_size,
            vix_signal=vix_signal,
            macro_score=macro_score_val,
            regime_used=current_regime,
            vix_component=vix_component,
            macro_component=macro_component,
            notes=notes,
        )

    def _get_current_regime(self) -> str | None:
        """Legge il regime HMM più recente da regime_reports in DuckDB.

        Returns None se DuckDB non disponibile o tabella vuota.
        Non crasha mai (Rule 5).
        """
        if self._duckdb is None:
            return None
        try:
            rows = self._duckdb.query(
                "SELECT regime FROM regime_reports "
                "ORDER BY computed_at DESC LIMIT 1"
            )
            if rows and rows[0][0]:
                return str(rows[0][0])
            return None
        except Exception as exc:
            log.debug("strategy_composer.regime_read_failed", error=str(exc)[:80])
            return None

    def _persist(
        self,
        computed_at:   datetime,
        vix_signal:    VixSignal,
        macro_score:   float | None,
        composite:     float,
        action:        str,
        confidence:    str,
        position_size: float,
        regime:        str | None,
    ) -> None:
        """Persiste l'output in vix_strategy_outputs (migration 007)."""
        if self._duckdb is None:
            return
        try:
            self._duckdb.execute(
                "INSERT OR REPLACE INTO vix_strategy_outputs "
                "(computed_at, vix_signal, action, position_size_pct, "
                "macro_score, composite_score, confidence, "
                "regime_used, threshold_adjusted) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [computed_at, vix_signal.vix_signal_score, action,
                 position_size, macro_score, composite, confidence,
                 regime, vix_signal.threshold_used],
            )
        except Exception as exc:
            log.warning("strategy_composer.persist_failed", error=str(exc)[:100])


# ─── Helpers puri ────────────────────────────────────────────────────────────

def _combine_confidence(
    vix_conf: str, macro_conf: str | None
) -> str:
    """Confidence combinata: il minimo tra VIX e Macro."""
    order = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
    vix_level   = order.get(vix_conf, 0)
    macro_level = order.get(macro_conf or "MEDIUM", 1)
    combined    = min(vix_level, macro_level)
    return {2: "HIGH", 1: "MEDIUM", 0: "LOW"}[combined]


def _build_notes(
    vix_signal:  VixSignal,
    macro_score: float | None,
    composite:   float,
    action:      str,
    regime:      str | None,
) -> str:
    """Costruisce il testo esplicativo per la UI."""
    vix_desc = (
        f"VIX {vix_signal.vix_level:.1f} (Z={vix_signal.vix_zscore:+.2f}, "
        f"regime={vix_signal.vix_regime})"
    )
    macro_desc = (
        f"macro={macro_score:+.3f}" if macro_score is not None
        else "macro=N/D"
    )
    regime_desc = f"HMM={regime}" if regime else "HMM=N/D"
    return (
        f"{action}: composite={composite:+.3f} | "
        f"{vix_desc} | {macro_desc} | {regime_desc}"
    )
