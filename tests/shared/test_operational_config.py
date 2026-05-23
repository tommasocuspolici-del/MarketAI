"""Test unitari per shared/config/operational_config.py.

Rif: ROADMAP_CODE_QUALITY_v1.0, Settimana 2 (P4).
     Debito tecnico Sprint 1 — nuove sezioni labour_market, sentiment, stress_test.
"""
from __future__ import annotations
import pathlib
from typing import Any
import pytest
import yaml
from shared.config.operational_config import (
    OP_CONFIG, OperationalConfig, _build_config_from_raw, _build_stress_test,
)


class TestOpConfigSingleton:
    def test_http_timeout(self) -> None:
        assert OP_CONFIG.http.default_timeout_s == 15.0

    def test_http_max_retries(self) -> None:
        assert OP_CONFIG.http.max_retries == 3

    def test_http_body_preview(self) -> None:
        assert OP_CONFIG.http.error_body_preview_bytes == 2048

    def test_cache_live_market_ttl(self) -> None:
        # 900s: deliberato per rate-limit Yahoo Finance (v9.0)
        assert OP_CONFIG.cache.live_market_ttl_s == 900

    def test_fx_gbp_usd(self) -> None:
        assert OP_CONFIG.fx_fallbacks.gbp_usd == 1.27

    def test_fx_eur_usd(self) -> None:
        assert OP_CONFIG.fx_fallbacks.eur_usd == 1.08

    def test_analytics_var_alpha(self) -> None:
        assert OP_CONFIG.analytics.var_alpha == 0.05


class TestBuildConfigFromRaw:
    def test_empty_uses_defaults(self) -> None:
        cfg = _build_config_from_raw({})
        assert cfg.http.default_timeout_s == 15.0
        assert cfg.cache.live_market_ttl_s == 900

    def test_partial_http_override(self) -> None:
        cfg = _build_config_from_raw({"http": {"default_timeout_s": 30.0}})
        assert cfg.http.default_timeout_s == 30.0
        assert cfg.http.max_retries == 3  # default invariato

    def test_partial_fx_override(self) -> None:
        cfg = _build_config_from_raw({"fx_fallbacks": {"gbp_usd": 1.30, "eur_usd": 1.12, "chf_usd": 1.15}})
        assert cfg.fx_fallbacks.gbp_usd == 1.30
        assert cfg.http.default_timeout_s == 15.0  # invariato

    def test_immutable(self) -> None:
        cfg = _build_config_from_raw({})
        with pytest.raises(Exception):
            cfg.http.default_timeout_s = 999.0  # type: ignore[misc]

    def test_returns_correct_type(self) -> None:
        assert isinstance(_build_config_from_raw({}), OperationalConfig)

    @pytest.mark.parametrize("section,field,value", [
        ("http", "default_timeout_s", 42.0),
        ("http", "max_retries", 7),
        ("cache", "live_market_ttl_s", 1800),
        ("fx_fallbacks", "gbp_usd", 1.40),
        ("alerts", "dedup_window_minutes", 120),
    ])
    def test_yaml_override(self, section: str, field: str, value: Any) -> None:
        cfg = _build_config_from_raw({section: {field: value}})
        assert getattr(getattr(cfg, section), field) == value

    def test_yaml_roundtrip(self, tmp_path: pathlib.Path) -> None:
        custom = {"http": {"default_timeout_s": 99.0}, "cache": {"live_market_ttl_s": 1800}}
        (tmp_path / "x.yaml").write_text(yaml.dump(custom))
        raw = yaml.safe_load((tmp_path / "x.yaml").read_text()) or {}
        cfg = _build_config_from_raw(raw)
        assert cfg.http.default_timeout_s == 99.0
        assert cfg.cache.live_market_ttl_s == 1800
        assert cfg.http.max_retries == 3  # default


class TestLabourMarketDefaults:
    def test_weights_sum_to_one(self) -> None:
        lm = OP_CONFIG.labour_market
        total = lm.weight_jolts + lm.weight_claims + lm.weight_payroll
        assert abs(total - 1.0) < 1e-9

    def test_weight_jolts(self) -> None:
        assert OP_CONFIG.labour_market.weight_jolts == 0.45

    def test_weight_claims(self) -> None:
        assert OP_CONFIG.labour_market.weight_claims == 0.40

    def test_weight_payroll(self) -> None:
        assert OP_CONFIG.labour_market.weight_payroll == 0.15

    def test_tight_score_min(self) -> None:
        assert OP_CONFIG.labour_market.tight_score_min == 0.35

    def test_balanced_range_consistent(self) -> None:
        lm = OP_CONFIG.labour_market
        assert lm.balanced_min < lm.balanced_max

    def test_override_via_raw(self) -> None:
        cfg = _build_config_from_raw({"labour_market": {"weight_jolts": 0.50, "weight_claims": 0.35, "weight_payroll": 0.15,
                                                         "tight_score_min": 0.35, "deteriorating_score_max": -0.25,
                                                         "balanced_min": -0.25, "balanced_max": 0.35}})
        assert cfg.labour_market.weight_jolts == 0.50

    def test_immutable(self) -> None:
        with pytest.raises(Exception):
            OP_CONFIG.labour_market.weight_jolts = 0.99  # type: ignore[misc]


class TestSentimentDefaults:
    def test_pc_bullish_thresh(self) -> None:
        assert OP_CONFIG.sentiment.pc_bullish_thresh == 0.70

    def test_pc_bearish_thresh(self) -> None:
        assert OP_CONFIG.sentiment.pc_bearish_thresh == 1.25

    def test_bullish_below_bearish(self) -> None:
        s = OP_CONFIG.sentiment
        assert s.pc_bullish_thresh < s.pc_bearish_thresh

    def test_cot_oi_spread(self) -> None:
        assert OP_CONFIG.sentiment.cot_oi_spread == 0.25

    def test_short_int_neutral(self) -> None:
        assert OP_CONFIG.sentiment.short_int_neutral == 0.01

    def test_short_int_spread(self) -> None:
        assert OP_CONFIG.sentiment.short_int_spread == 0.03

    def test_immutable(self) -> None:
        with pytest.raises(Exception):
            OP_CONFIG.sentiment.pc_bullish_thresh = 0.0  # type: ignore[misc]


class TestStressTestDefaults:
    def test_seed(self) -> None:
        assert OP_CONFIG.stress_test.seed == 42

    def test_recession_drift_negative(self) -> None:
        assert OP_CONFIG.stress_test.recession.drift_adj < 0

    def test_goldilocks_drift_positive(self) -> None:
        assert OP_CONFIG.stress_test.goldilocks.drift_adj > 0

    def test_base_drift_zero(self) -> None:
        assert OP_CONFIG.stress_test.base.drift_adj == 0.0

    def test_all_scenarios_present(self) -> None:
        st = OP_CONFIG.stress_test
        for attr in ("recession", "inflation_shock", "credit_crisis", "goldilocks", "base"):
            assert hasattr(st, attr), f"scenario {attr!r} mancante"

    def test_vol_mult_positive(self) -> None:
        for sc in ("recession", "inflation_shock", "credit_crisis", "goldilocks", "base"):
            assert getattr(OP_CONFIG.stress_test, sc).vol_mult > 0

    def test_override_seed(self) -> None:
        raw = {"stress_test": {"seed": 123}}
        cfg = _build_config_from_raw(raw)
        assert cfg.stress_test.seed == 123

    def test_override_scenario_param(self) -> None:
        raw = {"stress_test": {"recession": {"drift_adj": -0.005, "vol_mult": 2.0, "spike_days": 0, "spike_mult": 1.0}}}
        cfg = _build_config_from_raw(raw)
        assert cfg.stress_test.recession.drift_adj == -0.005

    def test_build_stress_test_defaults(self) -> None:
        st = _build_stress_test({})
        assert st.seed == 42
        assert st.recession.drift_adj == -0.0020

    def test_immutable(self) -> None:
        with pytest.raises(Exception):
            OP_CONFIG.stress_test.seed = 99  # type: ignore[misc]
