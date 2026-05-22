"""Scenario Tree Builder — 3 rami (bear/base/bull) con probabilità stimate."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np

from shared.logger import get_logger

log = get_logger(__name__)

DEFAULT_HORIZONS: list[int] = [30, 60, 90, 180]  # giorni

# Moltiplicatori sigma per ogni scenario
_SIGMA_MULTIPLIERS: dict[str, float] = {
    "bear": -1.28,   # ~10° percentile
    "base": 0.0,     # mediana
    "bull": 1.28,    # ~90° percentile
}

# Aggiustamenti di probabilità per regime macro
_REGIME_PROB_ADJUSTMENTS: dict[str, dict[str, float]] = {
    "expansion":   {"bear": 0.20, "base": 0.55, "bull": 0.25},
    "slowdown":    {"bear": 0.35, "base": 0.45, "bull": 0.20},
    "contraction": {"bear": 0.50, "base": 0.35, "bull": 0.15},
    "recovery":    {"bear": 0.15, "base": 0.50, "bull": 0.35},
    "stagflation": {"bear": 0.45, "base": 0.40, "bull": 0.15},
}


@dataclass
class Scenario:
    name: str          # bear|base|bull
    probability: float
    forecasts: dict[int, float]   # horizon_days → forecast value
    description: str


@dataclass
class ScenarioTree:
    asset: str
    base_value: float
    scenarios: list[Scenario]
    generated_at: str   # ISO datetime


class ScenarioTreeBuilder:
    """Costruisce albero scenari bear/base/bull da distribuzioni previsionali."""

    SCENARIO_PROBS: dict[str, float] = {
        "bear": 0.25,
        "base": 0.50,
        "bull": 0.25,
    }

    def build(
        self,
        asset: str,
        base_value: float,
        point_forecast: dict[int, float],
        volatility: dict[int, float],
        current_regime: str = "expansion",
    ) -> ScenarioTree:
        """Costruisce albero con 3 scenari su tutti gli orizzonti.

        Args:
            asset:           Ticker / nome asset.
            base_value:      Valore corrente dell'asset.
            point_forecast:  Previsioni puntuali per ogni orizzonte (giorni → valore).
            volatility:      Sigma della distribuzione prevista per orizzonte.
            current_regime:  Regime macro corrente per aggiustare le probabilità.

        Returns:
            ScenarioTree con 3 scenari (bear/base/bull).
        """
        adjusted_probs = self._adjust_probs_for_regime(current_regime)
        horizons = sorted(set(point_forecast.keys()) | set(volatility.keys()))

        scenarios: list[Scenario] = []
        for scenario_name, multiplier in _SIGMA_MULTIPLIERS.items():
            forecasts_by_horizon: dict[int, float] = {}
            for h in horizons:
                mu = point_forecast.get(h, base_value)
                sigma = volatility.get(h, 0.0)
                forecasts_by_horizon[h] = mu + multiplier * sigma

            description = self._build_description(scenario_name, current_regime)
            scenarios.append(
                Scenario(
                    name=scenario_name,
                    probability=adjusted_probs.get(scenario_name, self.SCENARIO_PROBS[scenario_name]),
                    forecasts=forecasts_by_horizon,
                    description=description,
                )
            )

        log.info(
            "scenario_tree.built",
            asset=asset,
            regime=current_regime,
            n_horizons=len(horizons),
        )

        return ScenarioTree(
            asset=asset,
            base_value=base_value,
            scenarios=scenarios,
            generated_at=datetime.now(UTC).isoformat(),
        )

    def _adjust_probs_for_regime(self, regime: str) -> dict[str, float]:
        """Aggiusta probabilità scenario in base al regime macro.

        Regimi supportati: expansion, slowdown, contraction, recovery, stagflation.
        Default (regime sconosciuto): probabilità standard 25/50/25.
        """
        adjusted = _REGIME_PROB_ADJUSTMENTS.get(regime.lower())
        if adjusted is None:
            log.warning("scenario_tree.unknown_regime", regime=regime)
            return dict(self.SCENARIO_PROBS)
        # Verifica che la somma sia ~1.0
        total = sum(adjusted.values())
        if abs(total - 1.0) > 1e-6:
            log.warning("scenario_tree.probs_not_normalized", regime=regime, total=total)
            return {k: v / total for k, v in adjusted.items()}
        return dict(adjusted)

    @staticmethod
    def _build_description(scenario_name: str, regime: str) -> str:
        base_descriptions: dict[str, str] = {
            "bear": "Scenario avverso: realizzo del rischio al ribasso.",
            "base": "Scenario base: evoluzione in linea con le aspettative.",
            "bull": "Scenario favorevole: accelerazione al rialzo.",
        }
        desc = base_descriptions.get(scenario_name, "")
        if regime in ("contraction", "stagflation") and scenario_name == "bull":
            desc += " (probabilità ridotta per regime avverso)"
        elif regime in ("recovery", "expansion") and scenario_name == "bear":
            desc += " (probabilità ridotta per regime favorevole)"
        return desc
