"""CompositeSignalAggregatorV3 — regime-adaptive composite (v10, Blocco B).

Improvements over v2 (Roadmap v4):
  1. Reads signals from SignalRegistry in-memory (not DuckDB directly) — < 1 ms
  2. Weights from config/regime_weights.yaml (not hardcoded)
  3. Multiplies each weight by AlphaDecayMonitor.get_weight_multiplier() (QC-2)
  4. Signals with quality_flag "low_ic" get reduced weight automatically
  5. ConsensusValidator before any critical BUY/SELL signal (QC-3)

Invariant: weights * multipliers are normalised to 1.0 before summing.
"""
from __future__ import annotations

import yaml
from pathlib import Path

import numpy as np

from shared.alpha_decay_monitor import AlphaDecayMonitor
from shared.consensus_validator import ConsensusValidator
from shared.logger import get_logger
from shared.signal_registry import get_signal_registry

__version__ = "10.0.0"

__all__ = ["CompositeSignalAggregatorV3"]

log = get_logger(__name__)

_REGIME_WEIGHTS_PATH = Path(__file__).resolve().parents[2] / "config" / "regime_weights.yaml"

_COMPONENT_SIGNAL_MAP: dict[str, str] = {
    "technical":  "technical_composite",
    "macro":      "macro_conviction",
    "labour":     "labour_regime_signal",
    "sentiment":  "sentiment_composite",
    "valuation":  "valuation_signal",
    "surprise":   "economic_surprise_index",
    "volatility": "vix_signal",
}

_CONSENSUS_SIGNALS = list(_COMPONENT_SIGNAL_MAP.values())


class CompositeSignalAggregatorV3:
    """Composite signal with regime-weighting and IC decay correction.

    Args:
        decay_monitor: AlphaDecayMonitor instance shared across the process.
        consensus_min_agreeing: number of signals that must agree before a
                                BUY/SELL alert is emitted (default 3 of 7).
    """

    def __init__(
        self,
        decay_monitor: AlphaDecayMonitor,
        consensus_min_agreeing: int = 3,
    ) -> None:
        self._monitor   = decay_monitor
        self._validator = ConsensusValidator(min_agreeing=consensus_min_agreeing)
        self._weights_config: dict = yaml.safe_load(_REGIME_WEIGHTS_PATH.read_text())

    # ── Public API ─────────────────────────────────────────────────────────

    def compute(self, current_regime: str) -> float:
        """Compute composite signal for *current_regime*.

        Pipeline:
          1. Read signals from SignalRegistry (no DuckDB I/O)
          2. Load regime weights from YAML
          3. Multiply by IC decay weight multiplier (QC-2)
          4. Normalise weights to 1.0
          5. Weighted sum → composite ∈ [-1, 1]

        Returns:
            float in [-1, 1]
        """
        registry = get_signal_registry()
        snapshot = registry.snapshot()     # dict[name → value], stale excluded

        weights_raw: dict[str, float] = (
            self._weights_config["regime_signal_weights"]
            .get(current_regime, self._weights_config["regime_signal_weights"]["transition"])
        )

        breakdown: dict[str, float] = {}
        weighted_sum = np.float64(0.0)
        total_weight  = np.float64(0.0)

        for component, base_weight in weights_raw.items():
            signal_name = _COMPONENT_SIGNAL_MAP.get(component, component)
            value = snapshot.get(signal_name)
            if value is None:
                log.debug("composite_v3.signal_missing", component=component)
                continue

            multiplier     = self._monitor.get_weight_multiplier(signal_name)
            eff_weight     = np.float64(base_weight) * np.float64(multiplier)
            breakdown[component] = float(np.float64(value) * eff_weight)
            weighted_sum  += np.float64(value) * eff_weight
            total_weight  += eff_weight

        if total_weight < 1e-9:
            log.warning("composite_v3.no_signals_available")
            return 0.0

        composite = float(weighted_sum / total_weight)

        log.info(
            "composite_v3.computed",
            composite=round(composite, 4),
            regime=current_regime,
            n_signals=len(breakdown),
            breakdown={k: round(v, 4) for k, v in breakdown.items()},
        )
        return float(np.clip(composite, -1.0, 1.0))

    def check_consensus(self, alert_type: str, threshold: float = 0.2) -> bool:
        """Return True only if ≥ min_agreeing signals agree for *alert_type* (QC-3)."""
        result = self._validator.check(
            alert_type   = alert_type,
            signal_names = _CONSENSUS_SIGNALS,
            threshold    = threshold,
        )
        return result.consensus_met

    @property
    def component_names(self) -> list[str]:
        return list(_COMPONENT_SIGNAL_MAP.keys())

    @staticmethod
    def resolve_signal_name(component: str) -> str:
        return _COMPONENT_SIGNAL_MAP.get(component, component)
