"""Test unitari per shared/config/operational_config.py.

Rif: ROADMAP_CODE_QUALITY_v1.0, Settimana 2 (P4).
"""
from __future__ import annotations
import pathlib
from typing import Any
import pytest
import yaml
from shared.config.operational_config import (
    OP_CONFIG, OperationalConfig, _build_config_from_raw,
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
