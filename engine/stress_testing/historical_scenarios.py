"""Historical stress scenarios — calibrated to actual market events.

Source data for the shock magnitudes:
  · GFC (2007-2009):    S&P500 -57% peak-to-trough; Treasuries +10%; USD +25%
  · COVID Crash (2020): S&P500 -34% in 33 trading days; bonds +8%; USD +8%
  · Rate Hike 2022:     S&P500 -25%; bonds **-13%** (the rare both-down year);
                          USD +18%
  · Dot-Com (2000-02):  S&P500 -49%; tech NASDAQ -78%; USD relatively flat

These shocks represent end-of-horizon moves; volatility multipliers are
calibrated to the realized vol regime during each event.
"""
from __future__ import annotations

from engine.stress_testing.scenario import ScenarioType, StressScenario

__version__ = "6.0.0"

__all__ = [
    "build_covid_2020",
    "build_dot_com_2000_2002",
    "build_global_financial_crisis_2008",
    "build_historical_scenarios",
    "build_rate_hike_2022",
]


def build_global_financial_crisis_2008() -> StressScenario:
    """The 2008 Global Financial Crisis — equity collapse, flight to bonds."""
    return StressScenario(
        name="Global Financial Crisis 2008",
        scenario_type=ScenarioType.HISTORICAL,
        description=(
            "Lehman collapse Sept 2008 + credit crunch. S&P500 -57% peak-to-"
            "trough Oct 2007 → Mar 2009. Treasuries rallied (+10%) on flight "
            "to safety; USD strengthened ~25% on global dollar shortage."
        ),
        equity_shock_pct=-0.57,
        bond_shock_pct=0.10,
        fx_shock_pct=0.25,
        vol_multiplier=3.0,         # VIX spiked to 80
    )


def build_covid_2020() -> StressScenario:
    """COVID-19 crash, March 2020 — fastest bear market in history."""
    return StressScenario(
        name="COVID Crash 2020",
        scenario_type=ScenarioType.HISTORICAL,
        description=(
            "Fastest 30%+ drawdown in S&P500 history (Feb 19 → Mar 23, 2020). "
            "S&P500 -34%; Treasuries +8% on flight-to-safety; USD +8% on "
            "global dollar squeeze. Recovery began with Fed unlimited QE."
        ),
        equity_shock_pct=-0.34,
        bond_shock_pct=0.08,
        fx_shock_pct=0.08,
        vol_multiplier=3.5,         # VIX peaked at 82.69
    )


def build_rate_hike_2022() -> StressScenario:
    """2022 hiking cycle — rare year where equities AND bonds both lost."""
    return StressScenario(
        name="Rate Hike Cycle 2022",
        scenario_type=ScenarioType.HISTORICAL,
        description=(
            "Fed pivoted to aggressive hikes against post-COVID inflation. "
            "S&P500 -25% peak-to-trough; **Bloomberg US Agg Bond -13%** "
            "(worst year on record); USD +18% (DXY up). Negative correlation "
            "between stocks and bonds broke down — diversification failed."
        ),
        equity_shock_pct=-0.25,
        bond_shock_pct=-0.13,       # Insolitamente negativo (Rule 24 raison d'être)
        fx_shock_pct=0.18,
        vol_multiplier=1.6,
    )


def build_dot_com_2000_2002() -> StressScenario:
    """The dot-com bust — slow-motion 2.5-year tech-led bear market."""
    return StressScenario(
        name="Dot-Com Bust 2000-2002",
        scenario_type=ScenarioType.HISTORICAL,
        description=(
            "S&P500 -49% peak-to-trough (Mar 2000 → Oct 2002); NASDAQ -78%. "
            "Treasuries rallied as Fed cut rates aggressively; USD relatively "
            "flat. Sector rotation from growth to value benefited diversified "
            "portfolios."
        ),
        equity_shock_pct=-0.49,
        bond_shock_pct=0.15,
        fx_shock_pct=0.0,
        vol_multiplier=2.0,
    )


def build_historical_scenarios() -> list[StressScenario]:
    """Return the 4 mandated historical scenarios (Phase 5 DoD)."""
    return [
        build_global_financial_crisis_2008(),
        build_covid_2020(),
        build_rate_hike_2022(),
        build_dot_com_2000_2002(),
    ]
