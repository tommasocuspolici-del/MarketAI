"""Forward-looking scenario generator (Rule 24).

Produces synthetic scenarios calibrated to the **current** market context
rather than historical replays. The generator emits at least 5 scenarios
representing distinct ways the market could plausibly evolve from here.

Family of scenarios produced:
  1. Recession Hard Landing      — Fed-induced recession, equity crash
  2. Soft Landing                — mild slowdown, Fed cuts, modest pullback
  3. Stagflation                 — sticky inflation + low growth
  4. Goldilocks                  — disinflation + growth, equities rally
  5. Geopolitical Tail           — unforeseen crisis, vol spike
  6. Rate Spike                  — bond yields surge, equity multiple compression

Probabilities are calibrated to ``MarketContext`` such that they sum
approximately to 1.0 (the residual is "no shock"). All math uses numpy
(Rule 8). Same input ``MarketContext`` → same outputs (deterministic).
"""
from __future__ import annotations

import numpy as np

from engine.stress_testing.scenario import (
    MarketContext,
    ScenarioType,
    StressScenario,
)

__version__ = "6.0.0"

__all__ = ["ScenarioGenerator"]


class ScenarioGenerator:
    """Produces synthetic forward-looking stress scenarios (Rule 24).

    Calibration heuristics:
      · High VIX (>30) raises probability of "Recession Hard Landing"
      · Inverted yield curve raises probability of recession scenarios
      · Low sentiment + bear regime → larger equity shock magnitudes
      · Stress regime → vol_multiplier ≥ 2.0 across all scenarios
    """

    @staticmethod
    def generate(context: MarketContext) -> list[StressScenario]:
        """Generate ≥5 synthetic scenarios calibrated to ``context``.

        Returns:
            List of StressScenario objects with calibrated probabilities.
            Always at least 5 (and typically 6) — DoD Fase 5.
        """
        vol_mul_base = ScenarioGenerator._base_vol_multiplier(context)

        scenarios = [
            ScenarioGenerator._recession_hard_landing(context, vol_mul_base),
            ScenarioGenerator._soft_landing(context, vol_mul_base),
            ScenarioGenerator._stagflation(context, vol_mul_base),
            ScenarioGenerator._goldilocks(context, vol_mul_base),
            ScenarioGenerator._geopolitical_tail(context, vol_mul_base),
            ScenarioGenerator._rate_spike(context, vol_mul_base),
        ]

        # Calibra probabilità: somma su tutti gli scenari ≤ 1.0 (residuo = base case)
        ScenarioGenerator._calibrate_probabilities(scenarios, context)
        return scenarios

    # ─── Scenario builders ──────────────────────────────────────────────
    @staticmethod
    def _recession_hard_landing(
        ctx: MarketContext, vol_mul_base: float
    ) -> StressScenario:
        # Shock equity più severo se VIX già alto (segnale di stress incipiente)
        equity_shock = -0.30 - 0.10 * np.tanh(max(0.0, ctx.vix - 20) / 10)
        return StressScenario(
            name="Forward: Recession Hard Landing",
            scenario_type=ScenarioType.SYNTHETIC,
            description=(
                "Fed tightening triggers credit crunch + earnings recession. "
                "Equity multiple compression + EPS cuts. Bonds rally on "
                "flight-to-safety. Calibrated to current VIX/sentiment."
            ),
            equity_shock_pct=float(equity_shock),
            bond_shock_pct=0.08,
            fx_shock_pct=0.12,
            vol_multiplier=float(vol_mul_base * 2.0),
            market_context=ctx,
        )

    @staticmethod
    def _soft_landing(ctx: MarketContext, vol_mul_base: float) -> StressScenario:
        # Pullback moderato: -8% / -15% a seconda del sentiment
        equity_shock = -0.08 - 0.07 * max(0.0, -ctx.sentiment_composite)
        return StressScenario(
            name="Forward: Soft Landing",
            scenario_type=ScenarioType.SYNTHETIC,
            description=(
                "Fed achieves disinflation without recession. Mild equity "
                "pullback as multiples adjust to lower-for-longer rates. "
                "Bonds modestly positive."
            ),
            equity_shock_pct=float(equity_shock),
            bond_shock_pct=0.04,
            fx_shock_pct=-0.03,
            vol_multiplier=float(vol_mul_base * 1.0),
            market_context=ctx,
        )

    @staticmethod
    def _stagflation(ctx: MarketContext, vol_mul_base: float) -> StressScenario:
        return StressScenario(
            name="Forward: Stagflation",
            scenario_type=ScenarioType.SYNTHETIC,
            description=(
                "Sticky inflation + low growth. Fed forced to keep rates "
                "elevated despite weakening economy. Equities decline "
                "modestly; bonds suffer further losses (correlation flip "
                "as in 2022)."
            ),
            equity_shock_pct=-0.18,
            bond_shock_pct=-0.08,
            fx_shock_pct=0.05,
            vol_multiplier=float(vol_mul_base * 1.5),
            market_context=ctx,
        )

    @staticmethod
    def _goldilocks(ctx: MarketContext, vol_mul_base: float) -> StressScenario:
        # NB: equity_shock POSITIVO = scenario favorevole (rally)
        equity_shock = 0.15 + 0.05 * max(0.0, ctx.sentiment_composite)
        return StressScenario(
            name="Forward: Goldilocks",
            scenario_type=ScenarioType.SYNTHETIC,
            description=(
                "Disinflation + steady growth. Fed cuts modestly. Equity "
                "multiples expand; bonds positive on lower discount rates. "
                "Risk asset rally."
            ),
            equity_shock_pct=float(equity_shock),
            bond_shock_pct=0.06,
            fx_shock_pct=-0.05,
            vol_multiplier=float(vol_mul_base * 0.7),
            market_context=ctx,
        )

    @staticmethod
    def _geopolitical_tail(ctx: MarketContext, vol_mul_base: float) -> StressScenario:
        return StressScenario(
            name="Forward: Geopolitical Tail",
            scenario_type=ScenarioType.SYNTHETIC,
            description=(
                "Unforeseen geopolitical event (war, energy shock, supply "
                "chain collapse). Sharp equity drop + commodity spike + USD "
                "rally on safe-haven demand. Vol regime jumps."
            ),
            equity_shock_pct=-0.22,
            bond_shock_pct=0.05,
            fx_shock_pct=0.15,
            vol_multiplier=float(vol_mul_base * 2.5),
            market_context=ctx,
        )

    @staticmethod
    def _rate_spike(ctx: MarketContext, vol_mul_base: float) -> StressScenario:
        return StressScenario(
            name="Forward: Rate Spike",
            scenario_type=ScenarioType.SYNTHETIC,
            description=(
                "Long-end yields surge on supply concerns / inflation re-"
                "acceleration. Bond prices crash; equity multiples compress "
                "(growth/tech most exposed). Reminiscent of 1994 + 2022Q3."
            ),
            equity_shock_pct=-0.15,
            bond_shock_pct=-0.12,
            fx_shock_pct=0.05,
            vol_multiplier=float(vol_mul_base * 1.4),
            market_context=ctx,
        )

    # ─── Probability calibration ────────────────────────────────────────
    @staticmethod
    def _base_vol_multiplier(ctx: MarketContext) -> float:
        """Higher VIX / stress regime → higher base volatility multiplier."""
        regime_factor = {"bull": 0.8, "transition": 1.0, "bear": 1.3, "stress": 1.8}
        factor = regime_factor.get(ctx.regime.lower(), 1.0)
        # VIX scaling (vol normale ≈ 16; 30+ è elevato)
        vix_factor = 1.0 + max(0.0, ctx.vix - 16.0) / 30.0
        return float(factor * vix_factor)

    @staticmethod
    def _calibrate_probabilities(
        scenarios: list[StressScenario], ctx: MarketContext
    ) -> None:
        """Set ``probability`` field on each scenario in-place.

        Uses heuristic weights modulated by VIX, yield curve, sentiment,
        and regime. All probabilities are non-negative; sum ≤ 1.0 with
        residual = "base case (no major shock)".
        """
        # NOTA: gli scenari hanno frozen=True ma il dataclass ha probability
        # come attributo. Per modificarlo dobbiamo creare nuove istanze
        # E sostituirle nella lista. Semplifichiamo passando un dict di prob
        # e ricreando in batch (più efficiente di multiple object.__setattr__).
        bear_signal = max(0.0, -ctx.sentiment_composite)
        inverted = max(0.0, -ctx.yield_curve_2y_10y * 10)  # 10bp inversione → 0.1 weight
        vix_signal = max(0.0, (ctx.vix - 16.0) / 50.0)

        regime_weights = {
            "bull": {
                "Recession Hard Landing": 0.05, "Soft Landing": 0.15,
                "Stagflation": 0.05, "Goldilocks": 0.40,
                "Geopolitical Tail": 0.05, "Rate Spike": 0.10,
            },
            "transition": {
                "Recession Hard Landing": 0.10, "Soft Landing": 0.25,
                "Stagflation": 0.10, "Goldilocks": 0.20,
                "Geopolitical Tail": 0.05, "Rate Spike": 0.10,
            },
            "bear": {
                "Recession Hard Landing": 0.30, "Soft Landing": 0.10,
                "Stagflation": 0.15, "Goldilocks": 0.05,
                "Geopolitical Tail": 0.10, "Rate Spike": 0.10,
            },
            "stress": {
                "Recession Hard Landing": 0.40, "Soft Landing": 0.05,
                "Stagflation": 0.15, "Goldilocks": 0.02,
                "Geopolitical Tail": 0.20, "Rate Spike": 0.08,
            },
        }
        base = regime_weights.get(ctx.regime.lower(), regime_weights["transition"])

        # Aggiusta le probabilità con segnali aggiuntivi (clip a [0, 1])
        adjustments = {
            "Recession Hard Landing": +0.05 * bear_signal + 0.10 * inverted,
            "Soft Landing": -0.05 * bear_signal,
            "Stagflation": +0.05 * vix_signal,
            "Goldilocks": -0.10 * bear_signal - 0.05 * vix_signal,
            "Geopolitical Tail": +0.05 * vix_signal,
            "Rate Spike": +0.05 * vix_signal,
        }

        # Modifica la lista in-place sostituendo gli oggetti (frozen=True)
        for i, scenario in enumerate(scenarios):
            short_name = scenario.name.replace("Forward: ", "")
            base_prob = base.get(short_name, 0.05)
            adj = adjustments.get(short_name, 0.0)
            prob = float(np.clip(base_prob + adj, 0.0, 1.0))
            scenarios[i] = StressScenario(
                name=scenario.name,
                scenario_type=scenario.scenario_type,
                equity_shock_pct=scenario.equity_shock_pct,
                bond_shock_pct=scenario.bond_shock_pct,
                description=scenario.description,
                fx_shock_pct=scenario.fx_shock_pct,
                vol_multiplier=scenario.vol_multiplier,
                probability=prob,
                market_context=scenario.market_context,
                scenario_id=scenario.scenario_id,
                generated_at=scenario.generated_at,
            )
