"""Unit tests for P2 currency normalisation logic (pure functions, no Streamlit).

Validates that _build_grouped_portfolio converts all costs to USD before
aggregating, regardless of the original currency of each PositionInput.
"""
from __future__ import annotations

import math
from datetime import date
from unittest import mock

import pytest

from personal.data_entry.position_form import PositionInput


def _make_pos(
    ticker: str,
    qty: float,
    avg_cost: float,
    currency: str = "USD",
    current_price: float | None = None,
    notes: str = "",
) -> PositionInput:
    return PositionInput(
        ticker=ticker,
        exchange="ALTRO",
        quantity=qty,
        avg_cost=avg_cost,
        open_date=date(2024, 1, 1),
        direction="LONG",
        currency=currency,
        current_price=current_price,
        notes=notes,
    )


def _import_build_grouped(fx_rates: dict[str, float], live_prices: dict[str, float | None]):
    """Import and patch _build_grouped_portfolio with fixed FX and live prices."""
    import presentation.dashboard_personal.pages.P2_Portafoglio_eToro as p2

    def _fake_fx():
        return fx_rates

    def _fake_price(ticker: str) -> float | None:
        return live_prices.get(ticker)

    with (
        mock.patch(
            "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._get_current_price_yf",
            side_effect=_fake_price,
        ),
        mock.patch(
            "personal.data_entry.etoro_position_builder._build_fx_cache",
            side_effect=_fake_fx,
        ),
        mock.patch(
            "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._resolve_canonical_ticker",
            side_effect=lambda t: t,  # passthrough — no DB needed
        ),
    ):
        return p2._build_grouped_portfolio


class TestBuildGroupedPortfolioCurrencyNormalisation:
    """_build_grouped_portfolio deve convertire tutti i costi in USD."""

    _FX = {"GBP_USD": 1.25, "EUR_USD": 1.10}
    _LIVE = {"SWDA.L": 130.0, "AAPL": 200.0, "EUN5.DE": 120.0}

    def _get_fn(self):
        return _import_build_grouped(self._FX, self._LIVE)

    def test_usd_position_unchanged(self) -> None:
        fn = self._get_fn()
        pos = _make_pos("AAPL", qty=10.0, avg_cost=190.0, currency="USD")
        with (
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._get_current_price_yf",
                side_effect=lambda t: self._LIVE.get(t),
            ),
            mock.patch(
                "personal.data_entry.etoro_position_builder._build_fx_cache",
                return_value=self._FX,
            ),
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._resolve_canonical_ticker",
                side_effect=lambda t: t,
            ),
        ):
            import presentation.dashboard_personal.pages.P2_Portafoglio_eToro as p2
            df = p2._build_grouped_portfolio([pos])

        assert "Investito (USD)" in df.columns
        invested = float(df["Investito (USD)"].iloc[0])
        assert math.isclose(invested, 10.0 * 190.0, rel_tol=1e-6)

    def test_eur_position_converted_to_usd(self) -> None:
        """avg_cost in EUR deve essere moltiplicato per EUR/USD."""
        with (
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._get_current_price_yf",
                side_effect=lambda t: self._LIVE.get(t),
            ),
            mock.patch(
                "personal.data_entry.etoro_position_builder._build_fx_cache",
                return_value=self._FX,
            ),
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._resolve_canonical_ticker",
                side_effect=lambda t: t,
            ),
        ):
            import presentation.dashboard_personal.pages.P2_Portafoglio_eToro as p2
            pos = _make_pos("EUN5.DE", qty=5.0, avg_cost=100.0, currency="EUR")
            df = p2._build_grouped_portfolio([pos])

        expected_invested = 5.0 * 100.0 * self._FX["EUR_USD"]  # 550 USD
        invested = float(df["Investito (USD)"].iloc[0])
        assert math.isclose(invested, expected_invested, rel_tol=1e-6)

    def test_gbx_position_converted_to_usd(self) -> None:
        """avg_cost in GBX (pence) deve essere / 100 * GBP/USD."""
        with (
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._get_current_price_yf",
                side_effect=lambda t: self._LIVE.get(t),
            ),
            mock.patch(
                "personal.data_entry.etoro_position_builder._build_fx_cache",
                return_value=self._FX,
            ),
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._resolve_canonical_ticker",
                side_effect=lambda t: t,
            ),
        ):
            import presentation.dashboard_personal.pages.P2_Portafoglio_eToro as p2
            pos = _make_pos("SWDA.L", qty=2.0, avg_cost=10000.0, currency="GBX")
            df = p2._build_grouped_portfolio([pos])

        expected_invested = 2.0 * (10000.0 / 100.0 * self._FX["GBP_USD"])  # 250 USD
        invested = float(df["Investito (USD)"].iloc[0])
        assert math.isclose(invested, expected_invested, rel_tol=1e-6)

    def test_mixed_eur_and_usd_same_ticker_aggregated(self) -> None:
        """EUR+USD posizioni sullo stesso ticker: investito totale normalizzato in USD."""
        with (
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._get_current_price_yf",
                side_effect=lambda t: self._LIVE.get(t),
            ),
            mock.patch(
                "personal.data_entry.etoro_position_builder._build_fx_cache",
                return_value=self._FX,
            ),
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._resolve_canonical_ticker",
                side_effect=lambda t: t,
            ),
        ):
            import presentation.dashboard_personal.pages.P2_Portafoglio_eToro as p2
            pos_eur = _make_pos("AAPL", qty=3.0, avg_cost=180.0, currency="EUR")
            pos_usd = _make_pos("AAPL", qty=7.0, avg_cost=200.0, currency="USD")
            df = p2._build_grouped_portfolio([pos_eur, pos_usd])

        assert len(df) == 1  # same ticker → same row
        expected = (3.0 * 180.0 * self._FX["EUR_USD"]) + (7.0 * 200.0)
        invested = float(df["Investito (USD)"].iloc[0])
        assert math.isclose(invested, expected, rel_tol=1e-6)

    def test_pl_computed_with_live_price_not_stored_price(self) -> None:
        """P/L usa sempre il prezzo live (USD), non il valore salvato (potrebbe essere EUR)."""
        with (
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._get_current_price_yf",
                side_effect=lambda t: self._LIVE.get(t),
            ),
            mock.patch(
                "personal.data_entry.etoro_position_builder._build_fx_cache",
                return_value=self._FX,
            ),
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._resolve_canonical_ticker",
                side_effect=lambda t: t,
            ),
        ):
            import presentation.dashboard_personal.pages.P2_Portafoglio_eToro as p2
            # current_price salvato in EUR (errato — scenario manuale)
            pos = _make_pos("AAPL", qty=5.0, avg_cost=180.0, currency="USD",
                            current_price=180.0)  # stale EUR price stored
            df = p2._build_grouped_portfolio([pos])

        live_price = self._LIVE["AAPL"]  # 200 USD
        expected_val = 5.0 * live_price
        expected_cost = 5.0 * 180.0
        expected_pl = expected_val - expected_cost

        val = float(df["Valore corrente (USD)"].iloc[0])
        pl = float(df["P/L (USD)"].iloc[0])
        assert math.isclose(val, expected_val, rel_tol=1e-6)
        assert math.isclose(pl, expected_pl, rel_tol=1e-6)

    def test_columns_always_usd(self) -> None:
        """Le colonne hanno sempre '(USD)' nel nome, non dipendono dalla valuta input."""
        with (
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._get_current_price_yf",
                side_effect=lambda t: self._LIVE.get(t),
            ),
            mock.patch(
                "personal.data_entry.etoro_position_builder._build_fx_cache",
                return_value=self._FX,
            ),
            mock.patch(
                "presentation.dashboard_personal.pages.P2_Portafoglio_eToro._resolve_canonical_ticker",
                side_effect=lambda t: t,
            ),
        ):
            import presentation.dashboard_personal.pages.P2_Portafoglio_eToro as p2
            positions = [
                _make_pos("AAPL", 1.0, 100.0, currency="EUR"),
                _make_pos("EUN5.DE", 2.0, 90.0, currency="EUR"),
            ]
            df = p2._build_grouped_portfolio(positions)

        assert "Investito (USD)" in df.columns
        assert "Valore corrente (USD)" in df.columns
        assert "P/L (USD)" in df.columns
        assert not any("EUR" in c for c in df.columns)
        assert not any("GBX" in c or "GBP" in c for c in df.columns)
