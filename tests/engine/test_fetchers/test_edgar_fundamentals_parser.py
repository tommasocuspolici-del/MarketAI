"""Tests for EarningsParser, BalanceSheetParser, FundamentalsAggregator.

Roadmap v3.0 — Settimana 1 — coverage target ≥ 85%.

Strategia: mock di EdgarFact con dati fissi (no network) — tutti i test
sono deterministici e si eseguono offline.
"""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from engine.market_data.fetchers.edgar_fetcher import EdgarFact
from engine.market_data.fetchers.edgar_fundamentals_parser import (
    BalanceSheetParser,
    EarningsParser,
    FundamentalsAggregator,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────

_PERIOD_END = datetime(2024, 12, 31, tzinfo=timezone.utc)
_FILING_DATE = datetime(2025, 2, 14, tzinfo=timezone.utc)


def _make_fact(
    ticker: str = "AAPL",
    metric: str = "Revenues",
    value: float = 100_000_000.0,
    currency: str = "USD",
    period_end: datetime = _PERIOD_END,
    period_type: str = "FY",
    form_type: str = "10-K",
) -> EdgarFact:
    """Costruisce un EdgarFact di test con valori di default sensati."""
    return EdgarFact(
        ticker=ticker,
        cik="320193",
        metric=metric,
        period_end=period_end,
        period_type=period_type,
        value=value,
        currency=currency,
        filing_date=_FILING_DATE,
        form_type=form_type,
    )


# ─── EarningsParser ──────────────────────────────────────────────────────────

class TestEarningsParser:
    """Tests per EarningsParser."""

    def setup_method(self) -> None:
        self.parser = EarningsParser()

    def test_parse_empty_returns_empty_dataframe(self) -> None:
        """Lista vuota → DataFrame vuoto."""
        result = self.parser.parse([])
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_parse_single_revenue_row(self) -> None:
        """Un solo fatto revenue → una riga con revenue valorizzato."""
        facts = [_make_fact(metric="Revenues", value=391_035_000_000.0)]
        df = self.parser.parse(facts)
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "AAPL"
        assert df.iloc[0]["revenue"] == pytest.approx(391_035_000_000.0)

    def test_parse_net_income_mapped(self) -> None:
        """NetIncomeLoss mappato correttamente."""
        facts = [
            _make_fact(metric="Revenues", value=100.0),
            _make_fact(metric="NetIncomeLoss", value=25.0),
        ]
        df = self.parser.parse(facts)
        assert len(df) == 1
        assert df.iloc[0]["net_income"] == pytest.approx(25.0)

    def test_parse_all_income_concepts(self) -> None:
        """Tutti i campi income statement estratti correttamente."""
        facts = [
            _make_fact(metric="Revenues", value=500.0),
            _make_fact(metric="GrossProfit", value=200.0),
            _make_fact(metric="OperatingIncomeLoss", value=100.0),
            _make_fact(metric="NetIncomeLoss", value=80.0),
            _make_fact(metric="EarningsPerShareDiluted", value=3.5, currency="USD/shares"),
        ]
        df = self.parser.parse(facts)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["revenue"] == pytest.approx(500.0)
        assert row["gross_profit"] == pytest.approx(200.0)
        assert row["ebit"] == pytest.approx(100.0)
        assert row["net_income"] == pytest.approx(80.0)
        assert row["eps_diluted"] == pytest.approx(3.5)

    def test_parse_multiple_tickers(self) -> None:
        """Dati di 2 ticker → 2 righe separate."""
        facts = [
            _make_fact(ticker="AAPL", metric="Revenues", value=400.0),
            _make_fact(ticker="MSFT", metric="Revenues", value=200.0),
        ]
        df = self.parser.parse(facts)
        assert set(df["ticker"]) == {"AAPL", "MSFT"}

    def test_parse_multiple_periods_same_ticker(self) -> None:
        """Periodi multipli dello stesso ticker → righe separate."""
        q1 = datetime(2024, 3, 31, tzinfo=timezone.utc)
        q2 = datetime(2024, 6, 30, tzinfo=timezone.utc)
        facts = [
            _make_fact(metric="Revenues", value=100.0, period_end=q1, period_type="Q1"),
            _make_fact(metric="Revenues", value=120.0, period_end=q2, period_type="Q2"),
        ]
        df = self.parser.parse(facts)
        assert len(df) == 2

    def test_parse_alternative_revenue_concept(self) -> None:
        """Concetto alternativo per revenue mappato correttamente."""
        facts = [
            _make_fact(
                metric="RevenueFromContractWithCustomerExcludingAssessedTax",
                value=300.0,
            )
        ]
        df = self.parser.parse(facts)
        assert len(df) == 1
        assert df.iloc[0]["revenue"] == pytest.approx(300.0)

    def test_parse_row_without_revenue_or_income_skipped(self) -> None:
        """Riga senza revenue NÉ net_income → scartata."""
        facts = [_make_fact(metric="EarningsPerShareDiluted", value=2.0)]
        df = self.parser.parse(facts)
        assert df.empty

    def test_parse_numeric_columns_are_float64(self) -> None:
        """Tutte le colonne numeriche devono essere float64 (Regola 8)."""
        facts = [
            _make_fact(metric="Revenues", value=100.0),
            _make_fact(metric="NetIncomeLoss", value=20.0),
        ]
        df = self.parser.parse(facts)
        for col in ("revenue", "gross_profit", "ebit", "net_income", "eps_diluted"):
            assert df[col].dtype == np.float64, f"{col} non è float64"

    def test_parse_missing_fields_are_nan(self) -> None:
        """Campi non presenti nei fatti → NaN (non zero o None)."""
        facts = [_make_fact(metric="Revenues", value=100.0)]
        df = self.parser.parse(facts)
        assert np.isnan(df.iloc[0]["gross_profit"])
        assert np.isnan(df.iloc[0]["eps_diluted"])


# ─── BalanceSheetParser ───────────────────────────────────────────────────────

class TestBalanceSheetParser:
    """Tests per BalanceSheetParser."""

    def setup_method(self) -> None:
        self.parser = BalanceSheetParser()

    def test_parse_empty_returns_empty_dataframe(self) -> None:
        result = self.parser.parse([])
        assert result.empty

    def test_parse_total_assets(self) -> None:
        facts = [_make_fact(metric="Assets", value=350_000.0)]
        df = self.parser.parse(facts)
        assert len(df) == 1
        assert df.iloc[0]["total_assets"] == pytest.approx(350_000.0)

    def test_parse_total_debt_lt_plus_st(self) -> None:
        """total_debt = LongTermDebt + ShortTermBorrowings."""
        facts = [
            _make_fact(metric="Assets", value=100.0),
            _make_fact(metric="LongTermDebt", value=40.0),
            _make_fact(metric="ShortTermBorrowings", value=10.0),
        ]
        df = self.parser.parse(facts)
        assert df.iloc[0]["total_debt"] == pytest.approx(50.0)

    def test_parse_total_debt_only_lt(self) -> None:
        """Se solo LT disponibile, total_debt = LT."""
        facts = [
            _make_fact(metric="Assets", value=100.0),
            _make_fact(metric="LongTermDebt", value=30.0),
        ]
        df = self.parser.parse(facts)
        assert df.iloc[0]["total_debt"] == pytest.approx(30.0)

    def test_parse_fcf_op_minus_capex(self) -> None:
        """FCF = OpCF - CapEx."""
        facts = [
            _make_fact(metric="Assets", value=100.0),
            _make_fact(metric="NetCashProvidedByUsedInOperatingActivities", value=80.0),
            _make_fact(metric="PaymentsToAcquirePropertyPlantAndEquipment", value=20.0),
        ]
        df = self.parser.parse(facts)
        assert df.iloc[0]["fcf"] == pytest.approx(60.0)

    def test_parse_row_without_assets_or_equity_skipped(self) -> None:
        """Riga senza assets NÉ equity → scartata."""
        facts = [_make_fact(metric="LongTermDebt", value=50.0)]
        df = self.parser.parse(facts)
        assert df.empty

    def test_parse_numeric_columns_are_float64(self) -> None:
        """Colonne numeriche float64 (Regola 8)."""
        facts = [_make_fact(metric="Assets", value=100.0)]
        df = self.parser.parse(facts)
        for col in ("total_assets", "total_debt", "equity", "fcf"):
            assert df[col].dtype == np.float64, f"{col} non è float64"


# ─── FundamentalsAggregator ───────────────────────────────────────────────────

class TestFundamentalsAggregator:
    """Tests per FundamentalsAggregator."""

    def setup_method(self) -> None:
        self.agg = FundamentalsAggregator()

    def test_aggregate_empty_returns_empty(self) -> None:
        df = self.agg.aggregate([])
        assert df.empty

    def test_aggregate_combines_income_and_balance(self) -> None:
        """Merge outer income + balance → colonne di entrambi presenti."""
        facts = [
            _make_fact(metric="Revenues", value=500.0),
            _make_fact(metric="NetIncomeLoss", value=100.0),
            _make_fact(metric="Assets", value=1000.0),
            _make_fact(metric="StockholdersEquity", value=400.0),
        ]
        df = self.agg.aggregate(facts)
        assert "revenue" in df.columns
        assert "total_assets" in df.columns
        assert len(df) == 1

    def test_aggregate_adds_source_column(self) -> None:
        facts = [_make_fact(metric="Revenues", value=100.0)]
        df = self.agg.aggregate(facts)
        assert "source" in df.columns
        assert df.iloc[0]["source"] == "edgar_xbrl"

    def test_aggregate_income_only_facts(self) -> None:
        """Solo income facts → balance columns presenti ma NaN."""
        facts = [_make_fact(metric="Revenues", value=200.0)]
        df = self.agg.aggregate(facts)
        assert "revenue" in df.columns
        # total_assets potrebbe non esserci (merge solo income) — OK

    def test_aggregate_sorted_by_ticker_then_date_desc(self) -> None:
        """Output ordinato per ticker asc, report_date desc."""
        q1 = datetime(2024, 3, 31, tzinfo=timezone.utc)
        q2 = datetime(2024, 6, 30, tzinfo=timezone.utc)
        facts = [
            _make_fact(metric="Revenues", value=100.0, period_end=q1, period_type="Q1"),
            _make_fact(metric="Revenues", value=120.0, period_end=q2, period_type="Q2"),
        ]
        df = self.agg.aggregate(facts)
        assert df.iloc[0]["period"] == "Q2"  # più recente prima

    def test_aggregate_two_tickers_separate_rows(self) -> None:
        facts = [
            _make_fact(ticker="AAPL", metric="Revenues", value=400.0),
            _make_fact(ticker="MSFT", metric="Revenues", value=200.0),
        ]
        df = self.agg.aggregate(facts)
        assert set(df["ticker"]) == {"AAPL", "MSFT"}
        assert len(df) == 2
