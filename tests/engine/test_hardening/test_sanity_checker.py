"""Test del SanityChecker."""
from __future__ import annotations

import pytest

from engine.market_data.hardening.sanity_checker import (
    SanityChecker,
    Severity,
)


def test_negative_price_is_critical() -> None:
    """Prezzo negativo o zero deve essere CRITICAL."""
    checker = SanityChecker()
    violations = checker.check_price_data("AAPL", price=-5.0)
    assert any(v.severity == Severity.CRITICAL for v in violations)
    assert not checker.is_safe_to_store(violations)


def test_zero_price_is_critical() -> None:
    """price = 0 e' impossibile."""
    checker = SanityChecker()
    violations = checker.check_price_data("AAPL", price=0.0)
    assert any(v.severity == Severity.CRITICAL for v in violations)


def test_positive_price_is_safe() -> None:
    """Prezzo positivo normale = nessuna violazione."""
    checker = SanityChecker()
    violations = checker.check_price_data("AAPL", price=187.42, prev_close=185.10)
    assert checker.is_safe_to_store(violations)


def test_extreme_daily_change_is_warn() -> None:
    """Variazione > 50% genera WARN, non blocca."""
    checker = SanityChecker()
    # +60% giornaliero
    violations = checker.check_price_data("AAPL", price=160.0, prev_close=100.0)
    assert any(v.severity == Severity.WARN for v in violations)
    assert checker.is_safe_to_store(violations)  # non bloccante


def test_negative_volume_is_critical() -> None:
    """Volume negativo e' impossibile."""
    checker = SanityChecker()
    violations = checker.check_price_data("AAPL", price=100.0, volume=-1.0)
    assert any(v.severity == Severity.CRITICAL for v in violations)


def test_pe_ratio_extremely_negative() -> None:
    """P/E < -500 e' CRITICAL."""
    checker = SanityChecker()
    violations = checker.check_fundamental_data("AAPL", pe_ratio=-9999.0)
    assert any(v.severity == Severity.CRITICAL for v in violations)


def test_pe_ratio_too_high() -> None:
    """P/E > 5000 e' WARN ma non blocca."""
    checker = SanityChecker()
    violations = checker.check_fundamental_data("AAPL", pe_ratio=10_000.0)
    assert any(v.severity == Severity.WARN for v in violations)
    assert checker.is_safe_to_store(violations)


def test_pe_ratio_zero_is_unavailable_warn() -> None:
    """P/E = 0 e' WARN (Finnhub bug noto)."""
    checker = SanityChecker()
    violations = checker.check_fundamental_data("XYZ", pe_ratio=0.0)
    assert any(
        v.severity == Severity.WARN and v.field == "pe_ratio"
        for v in violations
    )


def test_negative_market_cap_is_critical() -> None:
    """Market cap negativo e' impossibile."""
    checker = SanityChecker()
    violations = checker.check_fundamental_data("AAPL", market_cap=-1.0)
    assert any(v.severity == Severity.CRITICAL for v in violations)


def test_dividend_greater_than_price_is_critical() -> None:
    """Dividendo annuo > prezzo significa yield > 100%."""
    checker = SanityChecker()
    violations = checker.check_fundamental_data(
        "XYZ", dividend=120.0, price=100.0
    )
    assert any(v.severity == Severity.CRITICAL for v in violations)


def test_normal_fundamentals_are_safe() -> None:
    """Valori plausibili = nessuna violazione."""
    checker = SanityChecker()
    violations = checker.check_fundamental_data(
        "AAPL",
        pe_ratio=28.5,
        market_cap=3_000_000_000_000,  # 3T
        dividend=0.96,
        price=180.0,
        eps=6.30,
    )
    assert checker.is_safe_to_store(violations)


def test_severity_emoji() -> None:
    """severity_emoji ritorna le icone giuste."""
    assert SanityChecker.severity_emoji(Severity.CRITICAL) == "❌"
    assert SanityChecker.severity_emoji(Severity.WARN) == "⚠️"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
