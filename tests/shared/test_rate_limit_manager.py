"""Tests for shared.rate_limit_manager."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import pytest

from shared.exceptions import RateLimitExceededError
from shared.rate_limit_manager import RateBudget, RateLimitManager

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def rate_limits_file(tmp_path: Path) -> Path:
    """Write a test rate_limits.yaml with permissive + restrictive sources."""
    path = tmp_path / "rate_limits.yaml"
    path.write_text(
        """
fast:
  requests_per_minute: 600
  requests_per_day: unlimited
  burst_size: 10

slow:
  requests_per_minute: 5
  requests_per_day: 100
  burst_size: 1

tight_daily:
  requests_per_minute: 60
  requests_per_day: 3
  burst_size: 1
""",
        encoding="utf-8",
    )
    return path


class TestRateBudget:
    def test_min_interval_secs_computation(self) -> None:
        budget = RateBudget("x", requests_per_minute=60, requests_per_day=None)
        assert budget.min_interval_secs == pytest.approx(1.0)

        budget2 = RateBudget("y", requests_per_minute=120, requests_per_day=None)
        assert budget2.min_interval_secs == pytest.approx(0.5)

    def test_zero_rpm_returns_zero_interval(self) -> None:
        budget = RateBudget("dead", requests_per_minute=0, requests_per_day=None)
        assert budget.min_interval_secs == 0.0


class TestRateLimitManager:
    def test_loads_config_from_yaml(self, rate_limits_file: Path) -> None:
        mgr = RateLimitManager(config_path=rate_limits_file)
        assert set(mgr.list_sources()) == {"fast", "slow", "tight_daily"}

    def test_unknown_source_is_permissive(self, rate_limits_file: Path) -> None:
        mgr = RateLimitManager(config_path=rate_limits_file)
        # Non deve sollevare: permissivo per sorgenti non configurate
        asyncio.run(mgr.acquire("never_configured"))

    def test_fast_source_does_not_throttle_visibly(self, rate_limits_file: Path) -> None:
        mgr = RateLimitManager(config_path=rate_limits_file)

        async def _run() -> float:
            t0 = time.monotonic()
            for _ in range(5):
                await mgr.acquire("fast")
            return time.monotonic() - t0

        elapsed = asyncio.run(_run())
        # 600 req/min = 10/s = 100ms per req. 5 req ≈ <1s in totale
        assert elapsed < 1.0

    def test_daily_budget_exhaustion_raises(self, rate_limits_file: Path) -> None:
        mgr = RateLimitManager(config_path=rate_limits_file)

        async def _run() -> None:
            # tight_daily ha budget giornaliero = 3
            for _ in range(3):
                await mgr.acquire("tight_daily")
            # La 4ª chiamata deve esaurire
            await mgr.acquire("tight_daily")

        with pytest.raises(RateLimitExceededError, match="tight_daily"):
            asyncio.run(_run())

    def test_get_status_reports_usage(self, rate_limits_file: Path) -> None:
        mgr = RateLimitManager(config_path=rate_limits_file)

        async def _run() -> None:
            await mgr.acquire("fast")
            await mgr.acquire("fast")

        asyncio.run(_run())
        status = mgr.get_status("fast")
        assert status["configured"] is True
        assert status["rpm_used"] == 2
        assert status["daily_used"] == 2
        assert status["rpm_limit"] == 600

    def test_get_status_for_unknown_source(self, rate_limits_file: Path) -> None:
        mgr = RateLimitManager(config_path=rate_limits_file)
        status = mgr.get_status("nope")
        assert status == {"source": "nope", "configured": False}

    def test_slow_source_throttles_to_min_interval(self, rate_limits_file: Path) -> None:
        mgr = RateLimitManager(config_path=rate_limits_file)

        async def _run() -> float:
            t0 = time.monotonic()
            # slow = 5 req/min → intervallo ~12s. Facciamo 2 chiamate:
            # la 2ª deve attendere. Budget rpm=5 consente 5 richieste prima
            # del throttling, quindi forziamo l'intervallo minimo riducendo RPM.
            await mgr.acquire("slow")
            await mgr.acquire("slow")
            return time.monotonic() - t0

        # 5 req/min = 12s min interval. 2 chiamate ≈ 12s minimo — troppo lento
        # per CI. Qui verifichiamo solo che non crashi in < 15s.
        elapsed = asyncio.run(_run())
        # Intervallo minimo = 60/5 = 12s. Con margine:
        assert elapsed >= 11.5, f"expected throttling, got {elapsed:.2f}s"

    def test_missing_config_file_is_tolerated(self, tmp_path: Path) -> None:
        """Manager must load without crashing if config file is absent."""
        missing = tmp_path / "not_there.yaml"
        mgr = RateLimitManager(config_path=missing)
        assert mgr.list_sources() == []
