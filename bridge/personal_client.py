"""PersonalClient — engine-layer wrapper for personal layer access (Rule 21).

Reverse of EngineClient: this client is used by `engine/` (e.g. for
suitability checks during stress testing) to read the InvestorProfile
from the personal layer without importing personal/ directly.
"""
from __future__ import annotations

from typing import Any

from bridge.api_contracts import (
    PortfolioSnapshotForEngine,
    SuitabilityCheckRequest,
    SuitabilityCheckResponse,
)
from shared.exceptions import ContractViolationError
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["PersonalClient"]

log = get_logger(__name__)


class PersonalClient:
    """Read-side client used by the engine layer."""

    def __init__(
        self,
        portfolio_producer: Any,
        suitability_evaluator: Any,
    ) -> None:
        """
        Args:
            portfolio_producer: Callable returning a portfolio snapshot dict.
            suitability_evaluator: Callable that takes a SuitabilityCheckRequest
                and returns a dict matching SuitabilityCheckResponse.
        """
        self._portfolio_producer = portfolio_producer
        self._suitability_evaluator = suitability_evaluator

    def get_portfolio_snapshot(self, profile_id: str) -> PortfolioSnapshotForEngine:
        """Fetch the latest portfolio snapshot for a profile."""
        try:
            raw = self._portfolio_producer(profile_id=profile_id)
        except Exception as e:
            raise ContractViolationError(f"portfolio producer failed: {e}") from e

        if not isinstance(raw, dict):
            raise ContractViolationError(
                f"expected dict, got {type(raw).__name__}"
            )

        try:
            snap = PortfolioSnapshotForEngine.model_validate(raw)
        except Exception as e:
            raise ContractViolationError(
                f"portfolio snapshot schema violation: {e}"
            ) from e

        log.info(
            "personal_client.portfolio_fetched",
            profile_id=profile_id,
            n_positions=len(snap.positions),
        )
        return snap

    def check_suitability(
        self, request: SuitabilityCheckRequest
    ) -> SuitabilityCheckResponse:
        """Check whether an instrument is suitable for a profile."""
        try:
            raw = self._suitability_evaluator(request=request)
        except Exception as e:
            raise ContractViolationError(
                f"suitability evaluator failed: {e}"
            ) from e

        if not isinstance(raw, dict):
            raise ContractViolationError(
                f"expected dict from evaluator, got {type(raw).__name__}"
            )

        try:
            response = SuitabilityCheckResponse.model_validate(raw)
        except Exception as e:
            raise ContractViolationError(
                f"suitability response schema violation: {e}"
            ) from e

        log.info(
            "personal_client.suitability_checked",
            ticker=request.instrument_ticker,
            is_suitable=response.is_suitable,
        )
        return response
