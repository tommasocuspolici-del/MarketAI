"""Tests for MockOptionsChain."""
from __future__ import annotations

import pytest

from engine.options.mock_chain import MockOptionsChain, OptionContract

_CHAIN = MockOptionsChain()


class TestMockChainGenerate:
    def test_default_count(self):
        contracts = _CHAIN.generate(ticker="SPY", spot=500.0, iv=0.18)
        # 9 strikes × 5 expiries × 2 types = 90
        assert len(contracts) == 90

    def test_all_fields_populated(self):
        contracts = _CHAIN.generate(ticker="SPY", spot=500.0, iv=0.18)
        for c in contracts:
            assert c.ticker == "SPY"
            assert c.option_type in ("call", "put")
            assert c.price >= 0
            assert c.strike > 0
            assert c.expiry_days > 0

    def test_custom_strikes(self):
        contracts = _CHAIN.generate(ticker="AAPL", spot=200.0, iv=0.25,
                                     strikes_pct=[0.95, 1.00, 1.05])
        # 3 strikes × 5 expiries × 2 types = 30
        assert len(contracts) == 30

    def test_custom_expiries(self):
        contracts = _CHAIN.generate(ticker="AAPL", spot=200.0, iv=0.25,
                                     expiry_days=[30, 60])
        # 9 strikes × 2 expiries × 2 types = 36
        assert len(contracts) == 36

    def test_call_delta_positive(self):
        contracts = [c for c in _CHAIN.generate("X", 100.0, 0.20)
                     if c.option_type == "call"]
        assert all(c.delta > 0 for c in contracts)

    def test_put_delta_negative(self):
        contracts = [c for c in _CHAIN.generate("X", 100.0, 0.20)
                     if c.option_type == "put"]
        assert all(c.delta < 0 for c in contracts)

    def test_itm_call_correct(self):
        contracts = _CHAIN.generate("X", 100.0, 0.20,
                                     strikes_pct=[0.90])
        calls = [c for c in contracts if c.option_type == "call"]
        assert all(c.is_itm for c in calls)

    def test_otm_call_correct(self):
        contracts = _CHAIN.generate("X", 100.0, 0.20,
                                     strikes_pct=[1.10])
        calls = [c for c in contracts if c.option_type == "call"]
        assert all(not c.is_itm for c in calls)


class TestATMContracts:
    def test_atm_returns_two_per_expiry(self):
        contracts = _CHAIN.atm_contracts("SPY", spot=500.0, iv=0.18)
        # 1 strike × 5 expiries × 2 types = 10
        assert len(contracts) == 10

    def test_atm_strike_equals_spot(self):
        contracts = _CHAIN.atm_contracts("SPY", spot=500.0, iv=0.18)
        for c in contracts:
            assert c.strike == pytest.approx(500.0, rel=0.01)

    def test_atm_custom_expiries(self):
        contracts = _CHAIN.atm_contracts("SPY", spot=500.0, iv=0.18,
                                          expiry_days=[30])
        assert len(contracts) == 2    # call + put for 30 days
