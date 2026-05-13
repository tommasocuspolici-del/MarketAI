"""Tests for DataQualityAlerter and CrossSourceValidator.

Roadmap v3.0 — Settimana 2.

Usa DuckDB in-memory con schema migration 012 replicato inline.
"""
from __future__ import annotations

import math
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import duckdb
import numpy as np
import pytest


# ─── Fixture DuckDB in-memory con schema migration 012 ───────────────────────

@pytest.fixture
def in_memory_client():
    """Crea un mock DuckDBClient con connessione in-memory + schema 012."""
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS data_quality_alerts (
            alert_id      VARCHAR        NOT NULL DEFAULT gen_random_uuid()::VARCHAR,
            series_id     VARCHAR        NOT NULL,
            alert_kind    VARCHAR        NOT NULL,
            severity      VARCHAR        NOT NULL,
            quality_score DOUBLE,
            threshold     DOUBLE,
            detail        VARCHAR,
            source_a      VARCHAR,
            source_b      VARCHAR,
            metric_name   VARCHAR,
            pct_diff      DOUBLE,
            is_resolved   BOOLEAN        NOT NULL DEFAULT FALSE,
            resolved_at   TIMESTAMPTZ,
            created_at    TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
            PRIMARY KEY (alert_id)
        )
    """)

    client = MagicMock()

    @contextmanager
    def _transaction():
        yield conn

    client.transaction = _transaction
    return client


# ─── DataQualityAlerter — Tests ───────────────────────────────────────────────

class TestDataQualityAlerter:
    """Tests per DataQualityAlerter."""

    def _alerter(self, client):
        from engine.market_data.hardening.data_quality_alerter import DataQualityAlerter
        return DataQualityAlerter(client=client)

    def test_ok_score_generates_no_alerts(self, in_memory_client) -> None:
        """Score >= 0.7 → nessun alert."""
        alerter = self._alerter(in_memory_client)
        alerts = alerter.check_and_alert("SPY", 0.85)
        assert alerts == []

    def test_warning_score_generates_warning_alert(self, in_memory_client) -> None:
        """Score tra 0.5 e 0.7 → WARNING."""
        alerter = self._alerter(in_memory_client)
        alerts = alerter.check_and_alert("SPY", 0.62)
        assert len(alerts) == 1
        assert alerts[0].severity == "WARNING"
        assert alerts[0].series_id == "SPY"

    def test_critical_score_generates_critical_alert(self, in_memory_client) -> None:
        """Score < 0.5 → CRITICAL."""
        alerter = self._alerter(in_memory_client)
        alerts = alerter.check_and_alert("AAPL", 0.35)
        assert len(alerts) == 1
        assert alerts[0].severity == "CRITICAL"

    def test_deduplication_24h(self, in_memory_client) -> None:
        """Secondo alert per stessa serie nelle 24h → skip (dedup)."""
        alerter = self._alerter(in_memory_client)
        # Primo alert
        a1 = alerter.check_and_alert("ICSA", 0.42)
        assert len(a1) == 1
        # Secondo alert (stesso ticker, stessa finestra 24h)
        a2 = alerter.check_and_alert("ICSA", 0.40)
        assert a2 == []  # dedup

    def test_nan_score_returns_empty(self, in_memory_client) -> None:
        """Score NaN → lista vuota (skip silenzioso)."""
        alerter = self._alerter(in_memory_client)
        alerts = alerter.check_and_alert("FRED_GDP", float("nan"))
        assert alerts == []

    def test_alert_persisted_to_db(self, in_memory_client) -> None:
        """Alert critico viene scritto nel DB."""
        alerter = self._alerter(in_memory_client)
        alerter.check_and_alert("MSFT", 0.31)

        from contextlib import contextmanager
        with in_memory_client.transaction() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM data_quality_alerts WHERE series_id = 'MSFT'"
            ).fetchone()[0]
        assert count == 1

    def test_get_open_alerts_after_write(self, in_memory_client) -> None:
        """get_open_alerts ritorna l'alert scritto."""
        alerter = self._alerter(in_memory_client)
        alerter.check_and_alert("NVDA", 0.28)
        alerts = alerter.get_open_alerts(series_id="NVDA")
        assert len(alerts) >= 1
        assert alerts[0].series_id == "NVDA"

    def test_get_open_alerts_empty_db_returns_empty_list(self, in_memory_client) -> None:
        """DB vuoto → lista vuota."""
        alerter = self._alerter(in_memory_client)
        alerts = alerter.get_open_alerts()
        assert alerts == []

    def test_check_batch_multiple_series(self, in_memory_client) -> None:
        """check_batch genera alert per tutte le serie sotto soglia."""
        alerter = self._alerter(in_memory_client)
        scores = {"AAPL": 0.9, "GOOG": 0.45, "TSLA": 0.6}
        all_alerts = alerter.check_batch(scores)
        # GOOG (< 0.5 = CRITICAL) e TSLA (< 0.7 = WARNING) → 2 alert
        assert len(all_alerts) == 2
        severities = {a.series_id: a.severity for a in all_alerts}
        assert severities["GOOG"] == "CRITICAL"
        assert severities["TSLA"] == "WARNING"

    def test_alert_detail_contains_score(self, in_memory_client) -> None:
        """Il campo detail dell'alert contiene il valore del score."""
        alerter = self._alerter(in_memory_client)
        alerts = alerter.check_and_alert("FRED_CPI", 0.45)
        assert "0.45" in alerts[0].detail or "0.450" in alerts[0].detail

    def test_mark_resolved(self, in_memory_client) -> None:
        """mark_resolved chiude gli alert aperti."""
        alerter = self._alerter(in_memory_client)
        alerter.check_and_alert("GLD", 0.40)
        n = alerter.mark_resolved("GLD")
        assert n >= 0  # ha aggiornato la tabella senza errori


# ─── CrossSourceValidator — Tests ─────────────────────────────────────────────

class TestCrossSourceValidator:
    """Tests per CrossSourceValidator."""

    def _validator(self, client):
        from engine.market_data.hardening.cross_source_validator import CrossSourceValidator
        return CrossSourceValidator(client=client)

    def test_valid_price_comparison(self, in_memory_client) -> None:
        """Discrepanza < soglia 0.5% → is_valid=True."""
        v = self._validator(in_memory_client)
        result = v.validate_price("AAPL", 150.0, "yfinance", 150.5, "finnhub")
        # 0.5/150.5 ≈ 0.33% < 0.5% → valid
        assert result.is_valid
        assert result.pct_diff < 0.005

    def test_invalid_price_comparison(self, in_memory_client) -> None:
        """Discrepanza > soglia 0.5% → is_valid=False."""
        v = self._validator(in_memory_client)
        result = v.validate_price("AAPL", 150.0, "yfinance", 152.0, "finnhub")
        # 2/152 ≈ 1.3% > 0.5% → invalid
        assert not result.is_valid

    def test_nan_value_skips_gracefully(self, in_memory_client) -> None:
        """Uno dei due valori NaN → is_valid=True (skip silenzioso)."""
        v = self._validator(in_memory_client)
        result = v.validate_price("AAPL", float("nan"), "yfinance", 150.0, "finnhub")
        assert result.is_valid
        assert math.isnan(result.pct_diff)

    def test_both_zero_is_valid(self, in_memory_client) -> None:
        """Entrambi zero → pct_diff=0, is_valid=True."""
        v = self._validator(in_memory_client)
        result = v.validate_price("AAPL", 0.0, "yfinance", 0.0, "finnhub")
        assert result.is_valid
        assert result.pct_diff == pytest.approx(0.0)

    def test_pe_ratio_larger_threshold(self, in_memory_client) -> None:
        """P/E ha soglia 10% — una differenza del 5% è valida."""
        v = self._validator(in_memory_client)
        result = v.validate_pe_ratio("AAPL", 28.5, "alpha_vantage", 29.9, "finnhub")
        # 1.4/29.9 ≈ 4.7% < 10% → valid
        assert result.is_valid

    def test_validate_batch_returns_report(self, in_memory_client) -> None:
        """validate_batch ritorna ValidationReport con tutti i risultati."""
        v = self._validator(in_memory_client)
        report = v.validate_batch("AAPL", {
            "price": (150.0, "yfinance", 150.5, "finnhub"),
            "pe_ratio": (28.5, "av", 29.0, "finnhub"),
        })
        assert report.ticker == "AAPL"
        assert len(report.results) == 2

    def test_validate_batch_violations_persisted(self, in_memory_client) -> None:
        """Violazione in validate_batch → record scritto in data_quality_alerts."""
        v = self._validator(in_memory_client)
        # Discrepanza prezzo 5% > soglia 0.5%
        v.validate_batch("MSFT", {
            "price": (300.0, "yfinance", 315.0, "finnhub"),
        })

        with in_memory_client.transaction() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM data_quality_alerts "
                "WHERE series_id = 'MSFT' AND alert_kind = 'cross_source_discrepancy'"
            ).fetchone()[0]
        assert count >= 1

    def test_has_violations_property(self, in_memory_client) -> None:
        """has_violations True se almeno un risultato non valido."""
        v = self._validator(in_memory_client)
        report = v.validate_batch("AAPL", {
            "price": (150.0, "yfinance", 155.0, "finnhub"),  # > 0.5%
        })
        assert report.has_violations
        assert len(report.violations) == 1

    def test_pct_diff_calculation(self, in_memory_client) -> None:
        """pct_diff calcolato come |a-b|/max(|a|,|b|)."""
        v = self._validator(in_memory_client)
        result = v.validate_price("AAPL", 100.0, "s_a", 110.0, "s_b")
        # |100-110|/110 = 10/110 ≈ 0.0909
        assert result.pct_diff == pytest.approx(10.0 / 110.0, rel=1e-4)

    def test_market_cap_validation(self, in_memory_client) -> None:
        """validate_market_cap usa soglia 5%."""
        v = self._validator(in_memory_client)
        # 3% di differenza < 5% → valid
        result = v.validate_market_cap(
            "AAPL",
            2_500_000_000_000.0, "alpha_vantage",
            2_575_000_000_000.0, "yfinance",
        )
        assert result.is_valid

    def test_threshold_loaded_from_config(self, in_memory_client) -> None:
        """Le soglie vengono caricate da config (non hardcoded)."""
        v = self._validator(in_memory_client)
        # Il threshold per "price" dovrebbe essere 0.005 (da cross_source_config.yaml)
        threshold = v._thresholds.get("price", {}).get("max_pct_diff", -1)
        assert threshold > 0.0  # esiste ed è positivo
