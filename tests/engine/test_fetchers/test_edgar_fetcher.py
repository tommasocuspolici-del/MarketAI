"""Tests for engine.market_data.fetchers.edgar_fetcher."""
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from engine.market_data.fetchers.edgar_fetcher import EdgarFact, SECEdgarFetcher
from shared.exceptions import ConfigurationError, FeatureDisabledError
from shared.rate_limit_manager import RateLimitManager

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def edgar_rate_limiter(tmp_path: Path) -> RateLimitManager:
    rate_limits = tmp_path / "rate_limits.yaml"
    rate_limits.write_text(
        "sec_edgar:\n"
        "  requests_per_minute: 600\n"
        "  requests_per_day: unlimited\n"
        "  burst_size: 5\n",
        encoding="utf-8",
    )
    return RateLimitManager(config_path=rate_limits)


@pytest.fixture
def edgar_fetcher(edgar_rate_limiter: RateLimitManager) -> SECEdgarFetcher:
    return SECEdgarFetcher(
        rate_limiter=edgar_rate_limiter,
        user_agent="TestSuite test@example.com",
    )


def _sample_facts_payload() -> dict[str, object]:
    """Stand-in for the SEC companyfacts JSON response."""
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "units": {
                        "USD": [
                            {
                                "end": "2023-12-31",
                                "val": 119_000_000_000,
                                "fy": 2023,
                                "fp": "Q1",
                                "form": "10-Q",
                                "filed": "2024-02-02",
                            },
                            {
                                "end": "2024-09-30",
                                "val": 391_000_000_000,
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-11-01",
                            },
                        ],
                    },
                },
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {
                                "end": "2024-09-30",
                                "val": 96_995_000_000,
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-11-01",
                            },
                        ],
                    },
                },
            }
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# Construction & configuration
# ═══════════════════════════════════════════════════════════════════════════
class TestConstruction:
    def test_missing_user_agent_raises(
        self, edgar_rate_limiter: RateLimitManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Regola 15: User-Agent obbligatorio (SEC ban senza)
        monkeypatch.delenv("SEC_EDGAR_USER_AGENT", raising=False)
        with pytest.raises(ConfigurationError, match="SEC_EDGAR_USER_AGENT"):
            SECEdgarFetcher(rate_limiter=edgar_rate_limiter)

    def test_user_agent_from_env(
        self, edgar_rate_limiter: RateLimitManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "Env Agent env@example.com")
        fetcher = SECEdgarFetcher(rate_limiter=edgar_rate_limiter)
        assert fetcher._user_agent == "Env Agent env@example.com"


# ═══════════════════════════════════════════════════════════════════════════
# Fact parsing
# ═══════════════════════════════════════════════════════════════════════════
class TestParseFacts:
    def test_extracts_all_facts(self, edgar_fetcher: SECEdgarFetcher) -> None:
        facts = edgar_fetcher._parse_facts(
            ticker="AAPL",
            cik=320193,
            payload=_sample_facts_payload(),
            metrics_filter=None,
        )
        assert len(facts) == 3  # 2 Revenues + 1 NetIncomeLoss

    def test_filter_by_metric(self, edgar_fetcher: SECEdgarFetcher) -> None:
        facts = edgar_fetcher._parse_facts(
            ticker="AAPL",
            cik=320193,
            payload=_sample_facts_payload(),
            metrics_filter=["Revenues"],
        )
        assert len(facts) == 2
        for f in facts:
            assert f.metric == "Revenues"

    def test_facts_have_correct_types(self, edgar_fetcher: SECEdgarFetcher) -> None:
        facts = edgar_fetcher._parse_facts(
            ticker="AAPL",
            cik=320193,
            payload=_sample_facts_payload(),
            metrics_filter=None,
        )
        f = facts[0]
        assert isinstance(f, EdgarFact)
        assert f.ticker == "AAPL"
        # period_end deve essere datetime tz-aware
        assert f.period_end.tzinfo is not None

    def test_malformed_observations_skipped(
        self, edgar_fetcher: SECEdgarFetcher
    ) -> None:
        bad_payload = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"end": "2023-12-31"},  # manca "val" → skip
                                {
                                    "end": "2024-12-31",
                                    "val": 100,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2025-01-01",
                                },
                            ]
                        }
                    }
                }
            }
        }
        facts = edgar_fetcher._parse_facts(
            ticker="X", cik=1, payload=bad_payload, metrics_filter=None
        )
        assert len(facts) == 1


class TestToDataframe:
    def test_facts_to_dataframe(self) -> None:
        from datetime import UTC, datetime

        facts = [
            EdgarFact(
                ticker="AAPL",
                cik="320193",
                metric="Revenues",
                period_end=datetime(2024, 12, 31, tzinfo=UTC),
                period_type="FY",
                value=391_000_000_000,
                currency="USD",
                filing_date=datetime(2025, 2, 1, tzinfo=UTC),
                form_type="10-K",
            )
        ]
        df = SECEdgarFetcher.to_dataframe(facts)
        assert len(df) == 1
        for col in (
            "ticker",
            "cik",
            "metric",
            "period_end",
            "period_type",
            "value",
            "currency",
            "filing_date",
            "form_type",
            "source",
        ):
            assert col in df.columns
        assert df["source"].iloc[0] == "sec_edgar"

    def test_empty_returns_empty_df(self) -> None:
        assert SECEdgarFetcher.to_dataframe([]).empty


# ═══════════════════════════════════════════════════════════════════════════
# Async fetch with mocked aiohttp
# ═══════════════════════════════════════════════════════════════════════════
class TestFetchCompanyFacts:
    @pytest.mark.asyncio
    async def test_full_fetch_with_mocked_http(
        self, edgar_fetcher: SECEdgarFetcher
    ) -> None:
        # Patchiamo direttamente il metodo HTTP per evitare la rete
        async def _fake_get_json(_url: str) -> dict[str, object]:
            return _sample_facts_payload()

        with patch.object(edgar_fetcher, "_get_json", new=AsyncMock(side_effect=_fake_get_json)):
            facts = await edgar_fetcher.fetch_company_facts(
                ticker="AAPL", cik="0000320193"
            )
        assert len(facts) == 3
        assert all(f.ticker == "AAPL" for f in facts)


# ═══════════════════════════════════════════════════════════════════════════
# Bulk download — feature flag (Rule 29)
# ═══════════════════════════════════════════════════════════════════════════
class TestBulkDownload:
    @pytest.mark.asyncio
    async def test_bulk_disabled_raises_feature_error(
        self, edgar_fetcher: SECEdgarFetcher, tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Crea un feature_flags.yaml con edgar_bulk_download=false
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("edgar_bulk_download: false\n", encoding="utf-8")
        monkeypatch.setattr("shared.feature_flags.FEATURE_FLAGS_PATH", flags_file)

        from shared.feature_flags import reload_flags

        reload_flags()

        with pytest.raises(FeatureDisabledError):
            await edgar_fetcher.bulk_download({"AAPL": "0000320193"})

    @pytest.mark.asyncio
    async def test_bulk_enabled_runs(
        self,
        edgar_fetcher: SECEdgarFetcher,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        flags_file = tmp_path / "feature_flags.yaml"
        flags_file.write_text("edgar_bulk_download: true\n", encoding="utf-8")
        monkeypatch.setattr("shared.feature_flags.FEATURE_FLAGS_PATH", flags_file)

        from shared.feature_flags import reload_flags

        reload_flags()

        async def _fake_get_json(_url: str) -> dict[str, object]:
            return _sample_facts_payload()

        with patch.object(
            edgar_fetcher, "_get_json", new=AsyncMock(side_effect=_fake_get_json)
        ):
            results = await edgar_fetcher.bulk_download({"AAPL": "0000320193"})
        assert "AAPL" in results
        assert len(results["AAPL"]) == 3
