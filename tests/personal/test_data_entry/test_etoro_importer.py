"""Test del EtoroImporter (v7.1.1) — facade unica API/XLSX.

Verifica:
  1. Routing automatico tra API e XLSX in base alle credenziali.
  2. Conversione corretta delle posizioni API in DataFrame canonico.
  3. Fallback su XLSX in caso di errore API.
"""
from __future__ import annotations

from io import BytesIO
from unittest import mock

import pandas as pd
import pytest
from openpyxl import Workbook

from personal.data_entry.etoro_client import EtoroClientError, EtoroNetworkError
from personal.data_entry.etoro_importer import (
    EtoroImporter,
    EtoroImportError,
    _api_positions_to_dataframe,
)
from personal.data_entry.etoro_models import (
    EtoroClientPortfolio,
    EtoroInstrument,
    EtoroInstrumentRate,
    EtoroPortfolioResponse,
    EtoroPosition,
)


# ===================================================== credential detection
def test_no_credentials_falls_back_to_xlsx_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Senza env vars, has_api_credentials=False."""
    monkeypatch.delenv("ETORO_API_KEY", raising=False)
    monkeypatch.delenv("ETORO_USER_KEY", raising=False)
    importer = EtoroImporter()
    assert importer.has_api_credentials is False
    assert "non trovate" in importer.credential_status_message


def test_with_credentials_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con entrambe le env vars, has_api_credentials=True."""
    monkeypatch.setenv("ETORO_API_KEY", "fake_api")
    monkeypatch.setenv("ETORO_USER_KEY", "fake_user")
    importer = EtoroImporter()
    assert importer.has_api_credentials is True
    assert "API eToro configurata" in importer.credential_status_message


def test_partial_credentials_treated_as_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Solo una delle due env vars -> has_api_credentials=False."""
    monkeypatch.setenv("ETORO_API_KEY", "fake_api")
    monkeypatch.delenv("ETORO_USER_KEY", raising=False)
    importer = EtoroImporter()
    assert importer.has_api_credentials is False


# ===================================================== _api_positions_to_dataframe
def test_api_positions_to_dataframe_long_position() -> None:
    """Conversione posizione LONG con instrument risolto."""
    positions = [
        EtoroPosition(
            positionId=1,
            cid=1,
            openDateTime="2024-01-01T09:00:00Z",
            openRate=100.0,
            instrumentId=1001,
            isBuy=True,
            amount=1000.0,
            leverage=1,
            units=10.0,
            pnL=50.0,
            closeRate=105.0,
        )
    ]
    instruments = {
        1001: EtoroInstrument(instrumentId=1001, ticker="AAPL", name="Apple"),
    }
    rates = {
        1001: EtoroInstrumentRate(
            instrumentId=1001, bid=104.5, ask=105.5
        ),
    }

    df = _api_positions_to_dataframe(positions, instruments, rates)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["ticker"] == "AAPL"
    assert row["direction"] == "LONG"
    assert row["quantity"] == 10.0
    assert row["open_price"] == 100.0
    # current_price viene da rates.mid_price = (104.5 + 105.5) / 2
    assert row["current_price"] == 105.0
    # market_value = 105.0 * 10.0
    assert row["market_value"] == 1050.0
    # profit_pct = (50 / 1000) * 100
    assert row["profit_pct"] == 5.0
    assert row["profit_eur"] == 50.0


def test_api_positions_to_dataframe_short_position() -> None:
    """Conversione posizione SHORT."""
    positions = [
        EtoroPosition(
            positionId=2,
            cid=1,
            openDateTime="2024-01-01T09:00:00Z",
            openRate=200.0,
            instrumentId=1002,
            isBuy=False,
            amount=2000.0,
            leverage=2,
            units=10.0,
            pnL=-100.0,
        )
    ]
    instruments = {
        1002: EtoroInstrument(instrumentId=1002, ticker="TSLA"),
    }
    df = _api_positions_to_dataframe(positions, instruments, {})
    row = df.iloc[0]
    assert row["direction"] == "SHORT"
    assert row["profit_pct"] == -5.0  # -100/2000 * 100
    assert row["profit_eur"] == -100.0


def test_api_positions_to_dataframe_unknown_instrument() -> None:
    """Posizione con instrument_id non risolto -> ticker = '#<id>'."""
    positions = [
        EtoroPosition(
            positionId=3,
            cid=1,
            openDateTime="2024-01-01T09:00:00Z",
            openRate=50.0,
            instrumentId=9999,
            isBuy=True,
            amount=500.0,
            leverage=1,
            units=10.0,
            pnL=0.0,
        )
    ]
    df = _api_positions_to_dataframe(positions, {}, {})
    assert df.iloc[0]["ticker"] == "#9999"


def test_api_positions_to_dataframe_empty() -> None:
    """Nessuna posizione -> DataFrame vuoto con colonne canoniche."""
    df = _api_positions_to_dataframe([], {}, {})
    assert len(df) == 0
    assert "ticker" in df.columns
    assert "direction" in df.columns
    assert "quantity" in df.columns


# ===================================================== import_via_api flow
def test_import_via_api_calls_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """import_via_api orchestra correttamente client + instruments + rates."""
    monkeypatch.setenv("ETORO_API_KEY", "x")
    monkeypatch.setenv("ETORO_USER_KEY", "y")

    fake_portfolio = EtoroPortfolioResponse(
        clientPortfolio=EtoroClientPortfolio(
            credit=1000.0,
            positions=[
                EtoroPosition(
                    positionId=1, cid=1,
                    openDateTime="2024-01-01T09:00:00Z",
                    openRate=100.0, instrumentId=1001, isBuy=True,
                    amount=500.0, leverage=1, units=5.0, pnL=25.0,
                )
            ],
        )
    )
    fake_instruments = {
        1001: EtoroInstrument(instrumentId=1001, ticker="AAPL")
    }

    importer = EtoroImporter()
    with mock.patch(
        "personal.data_entry.etoro_importer.EtoroClient.from_env"
    ) as mock_from_env:
        mock_client = mock.MagicMock()
        mock_client.get_real_portfolio.return_value = fake_portfolio
        mock_client.get_instruments.return_value = fake_instruments
        mock_client.get_rates.return_value = {}
        mock_from_env.return_value = mock_client

        result = importer.import_via_api()

    assert result.source == "api"
    assert result.n_positions == 1
    assert len(result.positions) == 1
    assert result.positions.iloc[0]["ticker"] == "AAPL"


def test_import_via_api_no_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    """Account senza posizioni -> result vuoto ma source='api'."""
    monkeypatch.setenv("ETORO_API_KEY", "x")
    monkeypatch.setenv("ETORO_USER_KEY", "y")

    fake_portfolio = EtoroPortfolioResponse(
        clientPortfolio=EtoroClientPortfolio(credit=0.0, positions=[])
    )

    importer = EtoroImporter()
    with mock.patch(
        "personal.data_entry.etoro_importer.EtoroClient.from_env"
    ) as mock_from_env:
        mock_client = mock.MagicMock()
        mock_client.get_real_portfolio.return_value = fake_portfolio
        mock_from_env.return_value = mock_client

        result = importer.import_via_api()

    assert result.source == "api"
    assert result.n_positions == 0
    assert len(result.positions) == 0


# ===================================================== fallback flow
def test_import_open_positions_uses_api_when_credentials_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con credenziali, usa API per default."""
    monkeypatch.setenv("ETORO_API_KEY", "x")
    monkeypatch.setenv("ETORO_USER_KEY", "y")

    fake_portfolio = EtoroPortfolioResponse(
        clientPortfolio=EtoroClientPortfolio(credit=0.0, positions=[])
    )

    importer = EtoroImporter()
    with mock.patch(
        "personal.data_entry.etoro_importer.EtoroClient.from_env"
    ) as mock_from_env:
        mock_client = mock.MagicMock()
        mock_client.get_real_portfolio.return_value = fake_portfolio
        mock_from_env.return_value = mock_client

        result = importer.import_open_positions()
    assert result.source == "api"


def test_import_open_positions_falls_back_to_xlsx_on_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Errore di rete API + XLSX disponibile -> fallback automatico."""
    monkeypatch.setenv("ETORO_API_KEY", "x")
    monkeypatch.setenv("ETORO_USER_KEY", "y")

    importer = EtoroImporter()

    # XLSX di test minimo
    wb = Workbook()
    ws = wb.active
    ws.title = "Open Positions"
    ws.append(["Symbol", "Action", "Units", "Open Rate"])
    ws.append(["AAPL", "Buy", 5, 187.42])
    out = BytesIO()
    wb.save(out)
    xlsx_bytes = out.getvalue()

    with mock.patch(
        "personal.data_entry.etoro_importer.EtoroClient.from_env"
    ) as mock_from_env:
        mock_client = mock.MagicMock()
        mock_client.get_real_portfolio.side_effect = EtoroNetworkError(
            "Connection refused"
        )
        mock_from_env.return_value = mock_client

        result = importer.import_open_positions(xlsx_source=xlsx_bytes)

    # Fallback su XLSX deve essere stato attivato
    assert result.source == "xlsx"
    assert "Fallback" in result.notes
    assert result.n_positions >= 1


def test_import_open_positions_no_creds_no_xlsx_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Senza credenziali e senza XLSX -> EtoroImportError esplicativo."""
    monkeypatch.delenv("ETORO_API_KEY", raising=False)
    monkeypatch.delenv("ETORO_USER_KEY", raising=False)

    importer = EtoroImporter()
    with pytest.raises(EtoroImportError, match="Nessuna credenziale"):
        importer.import_open_positions()


def test_import_open_positions_force_xlsx_skips_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """force_xlsx=True ignora le credenziali API."""
    monkeypatch.setenv("ETORO_API_KEY", "x")
    monkeypatch.setenv("ETORO_USER_KEY", "y")

    importer = EtoroImporter()

    wb = Workbook()
    ws = wb.active
    ws.title = "Open Positions"
    ws.append(["Symbol", "Action", "Units", "Open Rate"])
    ws.append(["TSLA", "Sell", 2, 250.0])
    out = BytesIO()
    wb.save(out)

    # Anche con credenziali, force_xlsx deve usare il parser
    with mock.patch(
        "personal.data_entry.etoro_importer.EtoroClient.from_env"
    ) as mock_from_env:
        result = importer.import_open_positions(
            xlsx_source=out.getvalue(),
            force_xlsx=True,
        )
        # API non deve essere stato neanche istanziato
        mock_from_env.assert_not_called()

    assert result.source == "xlsx"
    assert result.n_positions == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
