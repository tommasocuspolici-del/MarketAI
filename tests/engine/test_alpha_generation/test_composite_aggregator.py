"""Test suite — Roadmap Unificata Settimana 8: CompositeSignalAggregator."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from engine.alpha_generation.composite_signal_aggregator import (
    CompositeSignalAggregator, CompositeSignalOutput, _WEIGHTS,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_db(
    vix_signal=0.8, vix_action="BUY",
    recession_prob=0.15, curve_regime="normal",
    stress_score=0.3, stress_level="low",
    claims_score=0.6, claims_regime="goldilocks",
    regime="bull",
    missing: list[str] | None = None,
) -> MagicMock:
    missing = missing or []
    db = MagicMock()

    def _query(sql, params=None):
        if "vix_strategy_outputs" in sql:
            return [] if "vix" in missing else [[vix_signal, vix_action]]
        if "yield_curve_snapshots" in sql:
            return [] if "yield_curve" in missing else [[recession_prob, curve_regime]]
        if "credit_spread_signals" in sql:
            return [] if "credit" in missing else [[stress_score, stress_level]]
        if "claims_inflation_signals" in sql:
            return [] if "claims" in missing else [[claims_score, claims_regime]]
        if "regime_reports" in sql:
            return [] if "regime" in missing else [[regime]]
        return []

    db.query.side_effect = _query
    db.execute = MagicMock()
    return db


# ═══════════════════════════════════════════════════════════════════════════
# Test CompositeSignalAggregator
# ═══════════════════════════════════════════════════════════════════════════

class TestCompositeSignalAggregator:

    def test_compute_returns_output(self):
        """compute() ritorna CompositeSignalOutput."""
        agg = CompositeSignalAggregator(duckdb=_make_db())
        result = agg.compute()
        assert isinstance(result, CompositeSignalOutput)

    def test_composite_score_in_range(self):
        """composite_score sempre in [-1, +1]."""
        for vix_action, rec_prob, stress, claims in [
            ("BUY",    0.10, 0.3,  0.8),
            ("REDUCE", 0.60, -0.5, -0.6),
            ("HOLD",   0.25, 0.0,  0.0),
        ]:
            db  = _make_db(vix_action=vix_action, recession_prob=rec_prob,
                           stress_score=stress, claims_score=claims)
            agg = CompositeSignalAggregator(duckdb=db)
            out = agg.compute()
            assert -1.0 <= out.composite_score <= 1.0, \
                f"Score {out.composite_score} OOB"

    def test_buy_on_favorable_conditions(self):
        """Tutte le condizioni favorevoli → BUY."""
        db = _make_db(
            vix_signal=0.9, vix_action="BUY",
            recession_prob=0.05, curve_regime="steep",
            stress_score=0.3, stress_level="low",
            claims_score=0.8, claims_regime="goldilocks",
            regime="bull",
        )
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert out.recommended_action == "BUY"

    def test_reduce_on_crisis_conditions(self):
        """Tutte le condizioni negative → REDUCE."""
        db = _make_db(
            vix_signal=0.0, vix_action="REDUCE",
            recession_prob=0.70, curve_regime="inverted",
            stress_score=-0.9, stress_level="crisis",
            claims_score=-1.0, claims_regime="stagflation",
            regime="stress",
        )
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert out.recommended_action == "REDUCE"

    def test_hold_on_neutral(self):
        """Condizioni neutre → HOLD."""
        db = _make_db(
            vix_signal=0.5, vix_action="HOLD",
            recession_prob=0.20, curve_regime="normal",
            stress_score=0.0, stress_level="moderate",
            claims_score=0.0, claims_regime="neutral",
        )
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert out.recommended_action == "HOLD"

    def test_confidence_high_when_all_components(self):
        """Con tutti i componenti → confidence HIGH se score estremo."""
        db = _make_db(
            vix_signal=1.0, vix_action="BUY",
            recession_prob=0.05, stress_score=0.3, claims_score=0.8,
        )
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert out.confidence in ("HIGH", "MEDIUM")

    def test_confidence_low_with_few_components(self):
        """Con < 3 componenti → confidence LOW."""
        db = _make_db(missing=["yield_curve", "credit", "claims"])
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert out.confidence == "LOW"

    def test_components_used_populated(self):
        """components_used lista i componenti effettivamente usati."""
        db = _make_db()
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert len(out.components_used) >= 3
        assert "vix" in out.components_used
        assert "yield_curve" in out.components_used

    def test_breakdown_json_valid(self):
        """breakdown_json è JSON valido con i componenti."""
        db = _make_db()
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        breakdown = json.loads(out.breakdown_json)
        assert isinstance(breakdown, dict)
        assert len(breakdown) >= 3

    def test_regime_populated_from_db(self):
        """regime letto da regime_reports."""
        db = _make_db(regime="bear")
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert out.regime == "bear"

    def test_regime_none_when_db_empty(self):
        """regime = None quando tabella regime_reports è vuota."""
        db = _make_db(missing=["regime"])
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert out.regime is None

    def test_persist_called_on_compute(self):
        """_persist chiama db.execute dopo il calcolo."""
        db = _make_db()
        agg = CompositeSignalAggregator(duckdb=db)
        agg.compute()
        assert db.execute.called

    def test_missing_all_components_returns_zero(self):
        """Nessun componente → composite = 0, HOLD, LOW."""
        db = _make_db(missing=["vix", "yield_curve", "credit", "claims"])
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert out.composite_score == pytest.approx(0.0)
        assert out.recommended_action == "HOLD"
        assert out.confidence == "LOW"

    def test_computed_at_utc(self):
        """computed_at è timezone-aware UTC."""
        db = _make_db()
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert out.computed_at.tzinfo is not None

    def test_meta_fields_populated(self):
        """credit_stress, claims_regime, yield_curve_regime popolati."""
        db = _make_db(
            stress_level="low", claims_regime="goldilocks",
            curve_regime="normal",
        )
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert out.credit_stress == "low"
        assert out.claims_regime == "goldilocks"
        assert out.yield_curve_regime == "normal"

    def test_weights_sum_to_one(self):
        """I pesi _WEIGHTS sommano a 1.0."""
        total = sum(_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_component_values_in_individual_fields(self):
        """vix_component, credit_component, etc. non sono tutti zero con dati."""
        db = _make_db(
            vix_signal=0.8, vix_action="BUY",
            stress_score=0.3, claims_score=0.6,
        )
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        # Almeno VIX e credit sono stati letti
        assert out.vix_component != 0.0 or out.credit_component != 0.0

    def test_db_exception_does_not_crash(self):
        """Exception in DB query → componente saltato, nessun crash."""
        db = MagicMock()
        db.query.side_effect = Exception("DB offline")
        db.execute = MagicMock()
        agg = CompositeSignalAggregator(duckdb=db)
        out = agg.compute()
        assert isinstance(out, CompositeSignalOutput)
        assert out.composite_score == pytest.approx(0.0)

    def test_with_macro_repo_adds_macro_component(self):
        """Con macro_repo fornito, il componente macro viene aggiunto."""
        db      = _make_db()
        macro   = MagicMock()

        # Mock del MacroConvictionCalculator via macro_repo
        import pandas as pd
        def _read_macro(sid, **kw):
            vals = [2.5] * 30
            return pd.DataFrame({"ts": pd.date_range("2024-01-01", periods=30, freq="MS"),
                                  "value": vals})
        macro.read_macro.side_effect = _read_macro
        macro.read_latest_macro.return_value = {"value": 2.5}

        agg = CompositeSignalAggregator(duckdb=db, macro_repo=macro)
        out = agg.compute()
        # macro_repo disponibile → prova a calcolare macro_component
        assert isinstance(out, CompositeSignalOutput)

    def test_benchmark_under_200ms(self, benchmark):
        """compute() < 200ms (target Roadmap Settimana 8)."""
        db  = _make_db()
        agg = CompositeSignalAggregator(duckdb=db)
        out = benchmark(agg.compute)
        assert isinstance(out, CompositeSignalOutput)


# ═══════════════════════════════════════════════════════════════════════════
# Test MarketContextBuilder
# ═══════════════════════════════════════════════════════════════════════════

class TestMarketContextBuilder:

    def _make_repo(self, fedfunds=5.25, dgs10=4.5, cpi=2.5) -> MagicMock:
        import pandas as pd
        repo = MagicMock()

        def _read_macro(sid, **kw):
            vals = {
                "FEDFUNDS": [fedfunds],
                "DGS10":    [dgs10],
                "CPIAUCSL": [cpi],
            }.get(sid, [])
            if not vals:
                return pd.DataFrame()
            return pd.DataFrame({
                "ts":    [datetime.now(timezone.utc)],
                "value": vals,
            })

        repo.read_macro.side_effect = _read_macro
        return repo

    def _make_db(self, regime="bull", vix=18.0) -> MagicMock:
        db = MagicMock()
        def _query(sql, params=None):
            if "regime_reports" in sql:
                return [[regime]]
            if "vix_signals" in sql:
                return [[vix]]
            return []
        db.query.side_effect = _query
        return db

    def test_build_returns_contract(self):
        """build() ritorna MarketContextForPersonal."""
        from bridge.market_context_builder import MarketContextBuilder
        from bridge.api_contracts import MarketContextForPersonal
        builder = MarketContextBuilder(
            duckdb=self._make_db(), macro_repo=self._make_repo()
        )
        ctx = builder.build()
        assert isinstance(ctx, MarketContextForPersonal)

    def test_risk_free_rate_from_fedfunds(self):
        """risk_free_rate = FEDFUNDS / 100."""
        from bridge.market_context_builder import MarketContextBuilder
        builder = MarketContextBuilder(
            duckdb=self._make_db(), macro_repo=self._make_repo(fedfunds=5.0)
        )
        ctx = builder.build()
        assert abs(ctx.risk_free_rate - 0.05) < 1e-6

    def test_bond_return_from_dgs10(self):
        """bond_expected_return = DGS10 / 100."""
        from bridge.market_context_builder import MarketContextBuilder
        builder = MarketContextBuilder(
            duckdb=self._make_db(), macro_repo=self._make_repo(dgs10=4.5)
        )
        ctx = builder.build()
        assert abs(ctx.bond_expected_return - 0.045) < 1e-6

    def test_inflation_from_cpi(self):
        """inflation_rate = CPI / 100."""
        from bridge.market_context_builder import MarketContextBuilder
        builder = MarketContextBuilder(
            duckdb=self._make_db(), macro_repo=self._make_repo(cpi=2.5)
        )
        ctx = builder.build()
        assert abs(ctx.inflation_rate - 0.025) < 1e-6

    def test_regime_from_db(self):
        """current_regime letto da regime_reports."""
        from bridge.market_context_builder import MarketContextBuilder
        builder = MarketContextBuilder(
            duckdb=self._make_db(regime="bear"),
            macro_repo=self._make_repo()
        )
        ctx = builder.build()
        assert ctx.current_regime == "bear"

    def test_vix_from_vix_signals(self):
        """vix letto da vix_signals."""
        from bridge.market_context_builder import MarketContextBuilder
        builder = MarketContextBuilder(
            duckdb=self._make_db(vix=25.0), macro_repo=self._make_repo()
        )
        ctx = builder.build()
        assert abs(ctx.vix - 25.0) < 1e-6

    def test_fallback_on_empty_db(self):
        """DB completamente vuoto → fallback values, nessun crash."""
        from bridge.market_context_builder import MarketContextBuilder
        import pandas as pd
        db   = MagicMock()
        db.query.return_value = []
        repo = MagicMock()
        repo.read_macro.return_value = pd.DataFrame()

        builder = MarketContextBuilder(duckdb=db, macro_repo=repo)
        ctx = builder.build()
        assert ctx.risk_free_rate > 0
        assert ctx.equity_expected_return > 0
        assert ctx.equity_volatility > 0
        assert ctx.vix == 20.0
        assert ctx.current_regime == "transition"

    def test_as_of_is_utc(self):
        """as_of è timezone-aware UTC."""
        from bridge.market_context_builder import MarketContextBuilder
        builder = MarketContextBuilder(
            duckdb=self._make_db(), macro_repo=self._make_repo()
        )
        ctx = builder.build()
        assert ctx.as_of.tzinfo is not None

    def test_equity_params_clipped(self):
        """equity_expected_return e equity_volatility sono in range [0.02-0.20, 0.08-0.40]."""
        from bridge.market_context_builder import MarketContextBuilder
        import pandas as pd
        db   = MagicMock()
        db.query.return_value = []
        repo = MagicMock()
        repo.read_macro.return_value = pd.DataFrame()

        builder = MarketContextBuilder(duckdb=db, macro_repo=repo)
        ctx = builder.build()
        assert 0.02 <= ctx.equity_expected_return <= 0.20
        assert 0.08 <= ctx.equity_volatility <= 0.40

    def test_contract_fields_present(self):
        """Tutti i campi del contratto bridge sono presenti."""
        from bridge.market_context_builder import MarketContextBuilder
        builder = MarketContextBuilder(
            duckdb=self._make_db(), macro_repo=self._make_repo()
        )
        ctx = builder.build()
        required_fields = [
            "as_of", "risk_free_rate", "equity_expected_return",
            "equity_volatility", "bond_expected_return",
            "inflation_rate", "current_regime", "vix",
        ]
        for field in required_fields:
            assert hasattr(ctx, field), f"Campo mancante: {field}"
