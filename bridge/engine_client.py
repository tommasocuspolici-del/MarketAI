"""EngineClient — personal-layer wrapper for engine analytics access (Rule 21).

This client is the SINGLE entry point through which `personal/` reads
market context from `engine/`. It enforces:
  · Pydantic schema validation on every response
  · UTC timestamps on every payload
  · No direct engine imports leaking into personal/
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bridge.api_contracts import MarketContextForPersonal
from shared.exceptions import ContractViolationError
from shared.logger import get_logger
from shared.types import now_utc

if TYPE_CHECKING:
    from datetime import datetime

__version__ = "6.0.0"

__all__ = ["EngineClient"]

log = get_logger(__name__)


class EngineClient:
    """Read-side client used by the personal layer.

    Concrete dependency injection: the caller passes a producer callable
    that returns the raw context dict (typically from engine.analytics).

    This indirection is what enforces Rule 21 — personal/ never knows about
    engine/ internals; it only knows the EngineClient interface and the
    bridge contract.
    """

    def __init__(self, context_producer: Any) -> None:
        """
        Args:
            context_producer: Callable returning a dict with the keys defined
                in MarketContextForPersonal. Typically wired in the app
                composition root (main.py) to point at the real engine.
        """
        self._producer = context_producer

    def get_market_context(self, as_of: datetime | None = None) -> MarketContextForPersonal:
        """Fetch the latest market context.

        Validates against the Pydantic contract; raises on schema mismatch.
        """
        as_of_ts = as_of or now_utc()
        try:
            raw = self._producer(as_of=as_of_ts)
        except Exception as e:
            raise ContractViolationError(
                f"engine producer failed: {e}"
            ) from e

        if not isinstance(raw, dict):
            raise ContractViolationError(
                f"expected dict from producer, got {type(raw).__name__}"
            )

        # Inject as_of if missing (engine producers may omit it)
        raw.setdefault("as_of", as_of_ts)

        try:
            ctx = MarketContextForPersonal.model_validate(raw)
        except Exception as e:
            raise ContractViolationError(
                f"market context schema violation: {e}"
            ) from e

        log.info(
            "engine_client.context_fetched",
            regime=ctx.current_regime,
            vix=ctx.vix,
        )
        return ctx
