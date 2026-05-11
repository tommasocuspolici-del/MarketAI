"""Stress tester orchestrator.

Combines historical and forward-looking scenarios (Rule 24), applies
each to a portfolio / equity curve, and produces:

  · a list of ``ScenarioOutcome`` objects (one per scenario)
  · an aggregate ``StressTestReport`` with VaR / CVaR / probability of loss
  · alerts when the probability-weighted negative outcome exceeds a
    configurable threshold (DoD Fase 5)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from engine.stress_testing.historical_scenarios import build_historical_scenarios
from engine.stress_testing.scenario import (
    MarketContext,
    ScenarioOutcome,
    ScenarioType,
    StressScenario,
)
from engine.stress_testing.scenario_generator import ScenarioGenerator
from shared.exceptions import StressTestError
from shared.logger import get_logger
from shared.metrics import metrics

if TYPE_CHECKING:
    import pandas as pd

__version__ = "6.0.0"

__all__ = [
    "StressAlert",
    "StressTestReport",
    "StressTester",
]

log = get_logger(__name__)

# Default soglia per alert "P(scenario_negativo) > soglia"
_DEFAULT_NEG_PROB_THRESHOLD = 0.30


# ═══════════════════════════════════════════════════════════════════════════
# Reports
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class StressAlert:
    """Alert emitted when stress test results exceed thresholds."""

    severity: str           # "warning" | "critical"
    message: str
    metric_name: str
    metric_value: float
    threshold: float


@dataclass(frozen=True, slots=True)
class StressTestReport:
    """Aggregate stress test report.

    Combines outcomes from N scenarios into single risk metrics:
      · var_95: Worst-case max_loss across the bottom 5% scenarios
      · cvar_95: Mean max_loss across the bottom 5% scenarios
      · prob_negative: Sum of probabilities for scenarios with final loss
      · expected_loss: Probability-weighted final loss (synthetic only)
    """

    outcomes: list[ScenarioOutcome]
    var_95: float                # negative number
    cvar_95: float               # negative, ≤ var_95
    prob_negative: float          # [0, 1]
    expected_loss: float         # negative if expected to lose
    alerts: list[StressAlert] = field(default_factory=list)

    @property
    def has_critical_alerts(self) -> bool:
        return any(a.severity == "critical" for a in self.alerts)

    @property
    def n_scenarios(self) -> int:
        return len(self.outcomes)


# ═══════════════════════════════════════════════════════════════════════════
# Tester
# ═══════════════════════════════════════════════════════════════════════════
class StressTester:
    """Orchestrates application of historical + synthetic scenarios."""

    def __init__(
        self,
        neg_prob_threshold: float = _DEFAULT_NEG_PROB_THRESHOLD,
        critical_loss_threshold: float = -0.40,
    ) -> None:
        if not 0.0 < neg_prob_threshold < 1.0:
            raise StressTestError(
                f"neg_prob_threshold must be in (0, 1), got {neg_prob_threshold}"
            )
        if critical_loss_threshold > 0:
            raise StressTestError(
                f"critical_loss_threshold must be negative, got {critical_loss_threshold}"
            )
        self._neg_prob_threshold = neg_prob_threshold
        self._critical_loss_threshold = critical_loss_threshold

    # ─── Main entry point ──────────────────────────────────────────────
    def run(
        self,
        equity_curve: pd.Series,
        market_context: MarketContext,
        equity_weight: float = 1.0,
        bond_weight: float = 0.0,
        extra_scenarios: list[StressScenario] | None = None,
    ) -> StressTestReport:
        """Run all 4 historical + ≥5 synthetic scenarios on ``equity_curve``.

        Args:
            equity_curve: Pre-stress equity curve (e.g. backtest output).
            market_context: Current market snapshot for synthetic scenarios.
            equity_weight: Portfolio weight on equity (default 100%).
            bond_weight: Portfolio weight on bonds (default 0%).
            extra_scenarios: Optional additional scenarios to include.

        Returns:
            ``StressTestReport`` with outcomes + aggregate metrics + alerts.

        Raises:
            StressTestError: If equity_curve is too short or weights invalid.
        """
        if len(equity_curve) < 2:
            raise StressTestError("equity_curve must have at least 2 points")

        with metrics.timer("stress_test_run_ms"):
            # 1. Costruzione lista scenari (storici + sintetici, Rule 24)
            historical = build_historical_scenarios()
            synthetic = ScenarioGenerator.generate(market_context)
            all_scenarios = list(historical) + list(synthetic)
            if extra_scenarios:
                all_scenarios.extend(extra_scenarios)

            # 2. Applica ogni scenario alla curve (vettorizzato all'interno)
            outcomes = [
                s.apply_to_equity_curve(equity_curve, equity_weight, bond_weight)
                for s in all_scenarios
            ]

            # 3. Aggrega in metriche di rischio
            report = self._build_report(outcomes)

        log.info(
            "stress_test.completed",
            n_scenarios=report.n_scenarios,
            prob_negative=round(report.prob_negative, 3),
            var_95=round(report.var_95, 3),
            n_alerts=len(report.alerts),
        )
        return report

    # ─── Internals ──────────────────────────────────────────────────────
    def _build_report(self, outcomes: list[ScenarioOutcome]) -> StressTestReport:
        """Compute VaR, CVaR, prob_negative, alerts from outcomes."""
        if not outcomes:
            return StressTestReport(
                outcomes=[], var_95=0.0, cvar_95=0.0,
                prob_negative=0.0, expected_loss=0.0,
            )

        # numpy array of max_loss across all scenarios (Rule 8)
        max_losses = np.array([o.max_loss_pct for o in outcomes], dtype="float64")

        # VaR 95%: il 5° percentile dei max_loss (worst 5% scenarios)
        var_95 = float(np.percentile(max_losses, 5))
        # CVaR 95%: media dei valori sotto il VaR
        below_var = max_losses[max_losses <= var_95]
        cvar_95 = float(below_var.mean()) if len(below_var) > 0 else var_95

        # Probabilità negativa: somma probabilità degli scenari con loss
        # Storici non hanno probability → contano come 1/N_total per neutralità
        synthetic_outcomes = [
            o for o in outcomes if o.scenario.scenario_type == ScenarioType.SYNTHETIC
        ]
        if synthetic_outcomes:
            prob_negative = float(
                sum(
                    (o.scenario.probability or 0.0)
                    for o in synthetic_outcomes
                    if o.is_negative
                )
            )
            expected_loss = float(
                sum(
                    (o.scenario.probability or 0.0) * o.final_loss_pct
                    for o in synthetic_outcomes
                )
            )
        else:
            prob_negative = float(sum(o.is_negative for o in outcomes) / len(outcomes))
            expected_loss = float(np.mean([o.final_loss_pct for o in outcomes]))

        # Alerts (DoD Fase 5)
        alerts = self._generate_alerts(outcomes, var_95, prob_negative)

        return StressTestReport(
            outcomes=outcomes,
            var_95=var_95,
            cvar_95=cvar_95,
            prob_negative=prob_negative,
            expected_loss=expected_loss,
            alerts=alerts,
        )

    def _generate_alerts(
        self,
        outcomes: list[ScenarioOutcome],
        var_95: float,
        prob_negative: float,
    ) -> list[StressAlert]:
        """Build alerts from threshold crossings."""
        alerts: list[StressAlert] = []

        # Alert: probabilità negativa sopra soglia
        if prob_negative > self._neg_prob_threshold:
            alerts.append(
                StressAlert(
                    severity="warning",
                    message=(
                        f"Probabilità di scenario negativo ({prob_negative:.1%}) "
                        f"sopra la soglia ({self._neg_prob_threshold:.1%})"
                    ),
                    metric_name="prob_negative",
                    metric_value=prob_negative,
                    threshold=self._neg_prob_threshold,
                )
            )

        # Alert critico: VaR 95% peggiore della soglia critica
        if var_95 < self._critical_loss_threshold:
            alerts.append(
                StressAlert(
                    severity="critical",
                    message=(
                        f"VaR 95% pari a {var_95:.1%} oltre la soglia "
                        f"critica ({self._critical_loss_threshold:.1%})"
                    ),
                    metric_name="var_95",
                    metric_value=var_95,
                    threshold=self._critical_loss_threshold,
                )
            )

        # Alert critico: almeno uno scenario con perdita estrema
        extreme = [o for o in outcomes if o.severity == "extreme"]
        if extreme:
            alerts.append(
                StressAlert(
                    severity="critical",
                    message=(
                        f"{len(extreme)} scenari con perdita estrema "
                        f"(>50%): {', '.join(o.scenario.name for o in extreme[:3])}"
                    ),
                    metric_name="extreme_scenario_count",
                    metric_value=float(len(extreme)),
                    threshold=0.0,
                )
            )

        return alerts
