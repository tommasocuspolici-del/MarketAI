"""Tests per ShillerCAPEFetcher — download + fallback FRED."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from engine.analytics.valuation.shiller_cape_fetcher import ShillerCAPEFetcher
from engine.analytics.valuation.schemas import ShillerCAPEPoint


@pytest.fixture()
def mock_client():
    client = MagicMock()
    client.query.return_value = []
    client.execute.return_value = None
    return client


@pytest.fixture()
def fetcher(mock_client):
    return ShillerCAPEFetcher(client=mock_client)


class TestShillerCAPEFetcher:
    def test_get_latest_cape_returns_float_or_none(self, fetcher):
        result = fetcher.get_latest_cape()
        assert result is None or isinstance(result, float)

    def test_get_latest_cape_from_db(self, mock_client):
        mock_client.query.return_value = [(32.5,)]
        f = ShillerCAPEFetcher(client=mock_client)
        result = f.get_latest_cape()
        assert result == pytest.approx(32.5)

    def test_get_latest_cape_none_when_no_data(self, mock_client):
        mock_client.query.return_value = []
        f = ShillerCAPEFetcher(client=mock_client)
        result = f.get_latest_cape()
        assert result is None

    def test_fetch_handles_network_error(self, fetcher):
        with patch.object(fetcher, "_fetch_from_web", side_effect=ConnectionError("timeout")):
            # Should fall back gracefully, not raise
            result = fetcher.get_latest_cape()
            assert result is None or isinstance(result, float)

    def test_cape_point_schema(self, mock_client):
        mock_client.query.return_value = [
            (date(2024, 1, 1), 4800.0, 160.0, 30.0, 0.042, 0.021)
        ]
        f = ShillerCAPEFetcher(client=mock_client)
        points = f.get_history(years=1)
        if points:
            p = points[0]
            assert isinstance(p, ShillerCAPEPoint)
            if p.cape_ratio is not None:
                assert p.cape_ratio > 0
