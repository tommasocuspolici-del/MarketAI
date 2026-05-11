"""Stress testing core types — scenarios + market context.

A ``StressScenario`` describes a hypothetical market shock with three
shock components (equity, bond, fx) plus a volatility multiplier. The
``apply_to_equity_curve`` helper produces a stressed PnL trajectory.

A ``MarketContext`` snapshot is the input for ``ScenarioGenerator`` and
captures the current state of the market so that synthetic scenarios are
calibrated to "what could plausibly happen NEXT" rather than just
historical replays (Rule 24).
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from shared.exceptions import StressTestError
from shared.types import now_utc

if TYPE_CHECKING:
    from datetime import datetime

__version__ = "6.0.0"

__all__ = [
    "MarketContext",
    "ScenarioOutcome",
    "ScenarioType",
    "StressScenario",
]


class ScenarioType(StrEnum):
    """Provenance of a stress scenario."""

    HISTORICAL = "historical"
    SYNTHETIC = "synthetic"


# ═══════════════════════════════════════════════════════════════════════════
# Market context — input for ScenarioGenerator
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class MarketContext:
    """Snapshot of current market conditions used to calibrate synthetic scenarios.

    All values are point-in-time observations that ``ScenarioGenerator``
    converts into shock parameters proportional to risk regime.
    """

    vix: float                          # CBOE VIX index
    yield_curve_2y_10y: float           # 10Y-2Y spread (negative = inverted)
    sentiment_composite: float          # [-1, 1]; negative = bearish
    regime: str                         # "bull" | "bear" | "transition" | "stress"
    equity_volatility: float = 0.15     # annualized realized vol
    risk_free_rate: float = 0.04        # 10Y treasury yield
    timestamp: datetime = field(default_factory=now_utc)

    def to_dict(self) -> dict[str, float | str]:
        """Plain dict for JSON serialization (used in scenario persistence)."""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


# ═══════════════════════════════════════════════════════════════════════════
# StressScenario — a single shock specification
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class StressScenario:
    """A hypothetical market shock.

    Attributes:
        scenario_id: Unique identifier (UUID generated if omitted).
        scenario_type: ``HISTORICAL`` or ``SYNTHETIC`` (Rule 24).
        name: Human-readable label.
        description: Free-text explanation.
        equity_shock_pct: Cumulative equity drawdown over the scenario
            horizon, e.g. -0.50 = -50%.
        bond_shock_pct: Bond move over horizon (positive = bonds rally).
        fx_shock_pct: USD vs base-currency basket move.
        vol_multiplier: Volatility regime multiplier (1.0 = normal).
        probability: Calibrated probability (None for historical).
        market_context: Input snapshot (None for historical scenarios).
        generated_at: When the scenario was produced.
    """

    name: str
    scenario_type: ScenarioType
    equity_shock_pct: float
    bond_shock_pct: float
    description: str = ""
    fx_shock_pct: float | None = None
    vol_multiplier: float = 1.0
    probability: float | None = None
    market_context: MarketContext | None = None
    scenario_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: datetime = field(default_factory=now_utc)

    def __post_init__(self) -> None:
        # Validazioni di sanità: shock deve essere realistico
        if not -1.0 <= self.equity_shock_pct <= 1.0:
            raise StressTestError(
                f"equity_shock_pct must be in [-1.0, 1.0], got {self.equity_shock_pct}"
            )
        if not -1.0 <= self.bond_shock_pct <= 1.0:
            raise StressTestError(
                f"bond_shock_pct must be in [-1.0, 1.0], got {self.bond_shock_pct}"
            )
        if self.vol_multiplier <= 0:
            raise StressTestError(
                f"vol_multiplier must be > 0, got {self.vol_multiplier}"
            )
        if self.probability is not None and not 0.0 <= self.probability <= 1.0:
            raise StressTestError(
                f"probability must be in [0, 1], got {self.probability}"
            )

    # ─── Application to a portfolio / equity curve ──────────────────────
    def apply_to_equity_curve(
        self,
        equity: pd.Series,
        equity_weight: float = 1.0,
        bond_weight: float = 0.0,
    ) -> ScenarioOutcome:
        """Apply the scenario shock to an equity curve.

        The shock is distributed linearly across the curve length to
        produce a deterministic stressed trajectory. Vol multiplier
        increases the noise around the deterministic path (Rule 8: numpy).

        Args:
            equity: Original equity curve (pre-stress).
            equity_weight: Portfolio weight on equity (default 100%).
            bond_weight: Portfolio weight on bonds (default 0%).
        """
        if len(equity) < 2:
            raise StressTestError("equity curve must have at least 2 points")
        if not 0.0 <= equity_weight + bond_weight <= 1.0 + 1e-9:
            raise StressTestError(
                f"weights sum {equity_weight + bond_weight} must be in [0, 1]"
            )

        n = len(equity)
        eq_arr = equity.astype("float64").to_numpy()

        # Combined portfolio shock weighted by exposure
        portfolio_shock = (
            equity_weight * self.equity_shock_pct
            + bond_weight * self.bond_shock_pct
        )

        # Path lineare: distribuiamo lo shock sui giorni
        # daily_shock_pct = portfolio_shock / n
        # Equity curve stressed: eq[t] * cumprod(1 + daily_shock + noise)
        daily_shock = portfolio_shock / n
        # Generatore con seed determinstico per riproducibilità (Rule 8)
        rng = np.random.default_rng(seed=hash(self.scenario_id) % (2**32))
        # Volatility noise scalata da vol_multiplier
        base_daily_vol = 0.01  # 1% giornaliero baseline
        noise = rng.normal(0.0, base_daily_vol * self.vol_multiplier, size=n)
        # Daily returns sul path stressato
        daily_returns = daily_shock + noise
        # Cumulative effect
        stressed_factor = np.cumprod(1.0 + daily_returns)
        stressed = eq_arr[0] * stressed_factor

        return ScenarioOutcome(
            scenario=self,
            stressed_equity=pd.Series(stressed, index=equity.index, dtype="float64"),
            max_loss_pct=float(stressed.min() / eq_arr[0] - 1.0),
            final_loss_pct=float(stressed[-1] / eq_arr[0] - 1.0),
        )

    def to_persistence_dict(self) -> dict[str, object]:
        """Format for DuckDB persistence (matches ``stress_scenarios`` schema)."""
        ctx_json = (
            json.dumps(self.market_context.to_dict(), default=str)
            if self.market_context is not None
            else None
        )
        return {
            "scenario_id": self.scenario_id,
            "scenario_type": self.scenario_type.value,
            "name": self.name,
            "description": self.description,
            "equity_shock_pct": self.equity_shock_pct,
            "bond_shock_pct": self.bond_shock_pct,
            "fx_shock_pct": self.fx_shock_pct,
            "vol_multiplier": self.vol_multiplier,
            "probability": self.probability,
            "generated_at": self.generated_at,
            "market_context": ctx_json,
        }


# ═══════════════════════════════════════════════════════════════════════════
# ScenarioOutcome — result of applying a scenario
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True, slots=True)
class ScenarioOutcome:
    """Outcome of applying a stress scenario to a portfolio."""

    scenario: StressScenario
    stressed_equity: pd.Series       # Stressed equity curve
    max_loss_pct: float              # Worst drawdown (negative)
    final_loss_pct: float            # End-of-horizon return (negative if loss)

    @property
    def is_negative(self) -> bool:
        """True if the scenario produced a net loss."""
        return self.final_loss_pct < 0.0

    @property
    def severity(self) -> str:
        """Categorical severity from max_loss_pct."""
        if self.max_loss_pct >= -0.10:
            return "mild"
        if self.max_loss_pct >= -0.25:
            return "moderate"
        if self.max_loss_pct >= -0.50:
            return "severe"
        return "extreme"
