"""Tests for bridge.engine_client + bridge.personal_client."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from bridge import (
    EngineClient,
    PersonalClient,
    PortfolioSnapshotForEngine,
    SuitabilityCheckRequest,
)
from shared.exceptions import ContractViolationError


# ═══════════════════════════════════════════════════════════════════════════
# EngineClient
# ═══════════════════════════════════════════════════════════════════════════
class TestEngineClient:
    def _good_producer(self, **kwargs: object) -> dict[str, object]:
        return {
            "as_of": datetime.now(UTC),
            "risk_free_rate": 0.045,
            "equity_expected_return": 0.07,
            "equity_volatility": 0.15,
            "bond_expected_return": 0.04,
            "bond_volatility": 0.05,
            "inflation_rate": 0.025,
            "current_regime": "bull",
            "vix": 16.5,
        }

    def test_get_market_context_valid(self) -> None:
        client = EngineClient(self._good_producer)
        ctx = client.get_market_context()
        assert ctx.current_regime == "bull"
        assert ctx.vix == 16.5

    def test_producer_raises_wraps_in_contract_violation(self) -> None:
        def bad_producer(**kwargs: object) -> dict[str, object]:
            raise RuntimeError("upstream down")

        client = EngineClient(bad_producer)
        with pytest.raises(ContractViolationError, match="producer failed"):
            client.get_market_context()

    def test_non_dict_response_raises(self) -> None:
        def bad_producer(**kwargs: object) -> str:
            return "not a dict"

        client = EngineClient(bad_producer)
        with pytest.raises(ContractViolationError, match="expected dict"):
            client.get_market_context()

    def test_invalid_schema_raises(self) -> None:
        def bad_producer(**kwargs: object) -> dict[str, object]:
            # Missing required fields
            return {"vix": 16.5}

        client = EngineClient(bad_producer)
        with pytest.raises(ContractViolationError, match="schema violation"):
            client.get_market_context()


# ═══════════════════════════════════════════════════════════════════════════
# PersonalClient
# ═══════════════════════════════════════════════════════════════════════════
class TestPersonalClient:
    def _good_portfolio(self, **kwargs: object) -> dict[str, object]:
        return {
            "profile_id": "p_test",
            "captured_at": datetime.now(UTC),
            "base_currency": "EUR",
            "positions": [
                {
                    "ticker": "AAPL",
                    "asset_class": "equity",
                    "quantity": Decimal("10"),
                    "avg_cost": Decimal("150.00"),
                    "currency": "USD",
                    "opened_at": datetime.now(UTC),
                },
            ],
        }

    def _good_suitability(self, **kwargs: object) -> dict[str, object]:
        return {
            "is_suitable": True,
            "reasons": [],
            "recommended_max_weight_pct": 0.30,
        }

    def test_portfolio_snapshot_valid(self) -> None:
        client = PersonalClient(
            portfolio_producer=self._good_portfolio,
            suitability_evaluator=self._good_suitability,
        )
        snap = client.get_portfolio_snapshot("p_test")
        assert isinstance(snap, PortfolioSnapshotForEngine)
        assert len(snap.positions) == 1

    def test_suitability_check_valid(self) -> None:
        client = PersonalClient(
            portfolio_producer=self._good_portfolio,
            suitability_evaluator=self._good_suitability,
        )
        request = SuitabilityCheckRequest(
            profile_id="p_test",
            instrument_ticker="AAPL",
            asset_class="equity",
            expected_max_drawdown_pct=0.15,
            annualized_volatility=0.20,
        )
        response = client.check_suitability(request)
        assert response.is_suitable

    def test_portfolio_producer_failure_wrapped(self) -> None:
        def bad_pf(**kwargs: object) -> dict[str, object]:
            raise RuntimeError("db unreachable")

        client = PersonalClient(
            portfolio_producer=bad_pf,
            suitability_evaluator=self._good_suitability,
        )
        with pytest.raises(ContractViolationError):
            client.get_portfolio_snapshot("p_test")
