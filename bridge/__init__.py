"""Bridge layer — single boundary between engine/ and personal/ (Rule 21)."""
from __future__ import annotations

from bridge.api_contracts import (
    ForecastRequest,
    ForecastScenario,
    MarketContextForPersonal,
    PortfolioSnapshotForEngine,
    PositionContract,
    StressTestRequest,
    SuitabilityCheckRequest,
    SuitabilityCheckResponse,
)
from bridge.engine_client import EngineClient
from bridge.personal_client import PersonalClient

__version__ = "6.0.0"

__all__ = [
    "EngineClient",
    "ForecastRequest",
    "ForecastScenario",
    "MarketContextForPersonal",
    "PersonalClient",
    "PortfolioSnapshotForEngine",
    "PositionContract",
    "StressTestRequest",
    "SuitabilityCheckRequest",
    "SuitabilityCheckResponse",
]
