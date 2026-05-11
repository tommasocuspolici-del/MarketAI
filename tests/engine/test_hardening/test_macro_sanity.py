"""Test del bugfix v7.1.1 sulle macro rules in SanityChecker.

Verifica:
  1. Le regole "macro" definite in sanity_rules.yaml sono caricate.
  2. check_macro_data() applica correttamente min/max per indicator type.
  3. _infer_macro_indicator_type() funziona per i series_id FRED noti.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from engine.market_data.hardening.sanity_checker import (
    SanityChecker,
    Severity,
    _infer_macro_indicator_type,
)


@pytest.fixture()
def yaml_config(tmp_path: Path) -> Path:
    """Crea un YAML temporaneo che ridefinisce le soglie macro."""
    cfg = {
        "macro": {
            "unemployment_rate": {"min_value": 0.0, "max_value": 50.0},
            "inflation_rate": {"min_value": -5.0, "max_value": 100.0},
            "gdp_growth": {"min_value": -30.0, "max_value": 30.0},
        },
    }
    path = tmp_path / "sanity_rules.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


# =================================================== caricamento YAML
def test_macro_rules_loaded_from_yaml(yaml_config: Path) -> None:
    """Verifica che le soglie macro nel YAML vengano effettivamente caricate."""
    checker = SanityChecker(config_path=yaml_config)
    macro_rules = checker._rules.get("macro", {})
    assert "unemployment_rate" in macro_rules
    assert macro_rules["unemployment_rate"]["max_value"] == 50.0
    assert macro_rules["inflation_rate"]["min_value"] == -5.0


def test_macro_rules_default_when_yaml_missing() -> None:
    """Senza YAML, le soglie macro di default sono applicate."""
    checker = SanityChecker(config_path=None)
    macro_rules = checker._rules.get("macro", {})
    assert "unemployment_rate" in macro_rules
    assert "inflation_rate" in macro_rules
    assert "gdp_growth" in macro_rules


# =================================================== check_macro_data
def test_unemployment_above_max_is_critical() -> None:
    """Disoccupazione 150% e' impossibile."""
    checker = SanityChecker()
    violations = checker.check_macro_data(
        "UNRATE", value=150.0, indicator_type="unemployment_rate"
    )
    assert len(violations) == 1
    assert violations[0].severity == Severity.CRITICAL
    assert violations[0].field == "unemployment_rate"


def test_unemployment_negative_is_critical() -> None:
    """Disoccupazione negativa e' impossibile."""
    checker = SanityChecker()
    violations = checker.check_macro_data(
        "UNRATE", value=-1.0, indicator_type="unemployment_rate"
    )
    assert len(violations) == 1
    assert violations[0].severity == Severity.CRITICAL


def test_unemployment_normal_passes() -> None:
    """Disoccupazione 4% = nessuna violazione."""
    checker = SanityChecker()
    violations = checker.check_macro_data(
        "UNRATE", value=4.0, indicator_type="unemployment_rate"
    )
    assert violations == []


def test_inflation_extreme_negative_is_critical() -> None:
    """Inflazione -20% (oltre la soglia -10%) e' implausibile."""
    checker = SanityChecker()
    violations = checker.check_macro_data(
        "CPIAUCSL", value=-20.0, indicator_type="inflation_rate"
    )
    assert len(violations) == 1
    assert violations[0].severity == Severity.CRITICAL


def test_inflation_high_but_plausible_passes() -> None:
    """Inflazione 50% (es. Argentina/Turchia) e' alta ma plausibile (< 100)."""
    checker = SanityChecker()
    violations = checker.check_macro_data(
        "CPIAUCSL", value=50.0, indicator_type="inflation_rate"
    )
    assert violations == []


def test_gdp_growth_extreme_is_critical() -> None:
    """GDP growth +60% e' implausibile (> 50% soglia)."""
    checker = SanityChecker()
    violations = checker.check_macro_data(
        "GDPC1", value=60.0, indicator_type="gdp_growth"
    )
    assert len(violations) == 1
    assert violations[0].severity == Severity.CRITICAL


def test_gdp_growth_recession_passes() -> None:
    """GDP growth -10% (recessione severa) e' plausibile (> -50%)."""
    checker = SanityChecker()
    violations = checker.check_macro_data(
        "GDPC1", value=-10.0, indicator_type="gdp_growth"
    )
    assert violations == []


def test_macro_data_none_value_no_violations() -> None:
    """Value=None non genera violazioni (e' accettabile per dato mancante)."""
    checker = SanityChecker()
    violations = checker.check_macro_data(
        "UNRATE", value=None, indicator_type="unemployment_rate"
    )
    assert violations == []


# =================================================== inferenza tipo
def test_infer_unemployment_from_unrate() -> None:
    """UNRATE -> unemployment_rate."""
    assert _infer_macro_indicator_type("UNRATE") == "unemployment_rate"
    assert _infer_macro_indicator_type("unrate") == "unemployment_rate"


def test_infer_inflation_from_fred_codes() -> None:
    """CPIAUCSL, CPILFESL, PCEPI -> inflation_rate."""
    assert _infer_macro_indicator_type("CPIAUCSL") == "inflation_rate"
    assert _infer_macro_indicator_type("CPILFESL") == "inflation_rate"
    assert _infer_macro_indicator_type("PCEPI") == "inflation_rate"


def test_infer_gdp_from_codes() -> None:
    """GDPC1, GDP -> gdp_growth."""
    assert _infer_macro_indicator_type("GDPC1") == "gdp_growth"
    assert _infer_macro_indicator_type("GDP") == "gdp_growth"


def test_infer_unknown_returns_none() -> None:
    """Series_id non in mappa ritorna None."""
    assert _infer_macro_indicator_type("UNKNOWN_SERIES") is None
    assert _infer_macro_indicator_type("") is None


def test_check_macro_data_auto_inferred_type() -> None:
    """check_macro_data senza indicator_type lo deduce dal series_id."""
    checker = SanityChecker()
    violations = checker.check_macro_data("UNRATE", value=150.0)
    assert len(violations) == 1
    assert violations[0].severity == Severity.CRITICAL


def test_check_macro_data_unknown_series_no_check() -> None:
    """Series_id non riconosciuto + indicator_type None -> no check."""
    checker = SanityChecker()
    violations = checker.check_macro_data("UNKNOWN_THING", value=999_999.0)
    assert violations == []


# =================================================== merge ricorsivo
def test_yaml_overrides_only_specified_macro_keys(tmp_path: Path) -> None:
    """YAML che ridefinisce solo unemployment_rate non azzera gli altri."""
    cfg = {
        "macro": {
            "unemployment_rate": {"max_value": 25.0},  # solo questa
        },
    }
    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    checker = SanityChecker(config_path=path)
    macro = checker._rules["macro"]
    # unemployment_rate.max_value e' stato sovrascritto
    assert macro["unemployment_rate"]["max_value"] == 25.0
    # Inflation e gdp_growth restano dai default
    assert "inflation_rate" in macro
    assert "gdp_growth" in macro
    assert macro["gdp_growth"]["max_value"] == 50.0  # da default


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
