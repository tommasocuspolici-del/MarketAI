"""Tests per personal.data_entry.etoro_models v7.1.3 (B2).

Verifica che le posizioni con i nuovi schema (senza positionId/cid/instrumentId
top-level) non causino piu' ValidationError.
"""
from __future__ import annotations

import pytest

from personal.data_entry.etoro_models import (
    EtoroPosition,
    EtoroPortfolioResponse,
    parse_portfolio_response,
)

# Payload minimo richiesto: openDateTime, openRate, isBuy, amount, leverage, units.
_BASE_REQUIRED = {
    "openDateTime": "2026-01-15T10:30:00Z",
    "openRate": 150.0,
    "isBuy": True,
    "amount": 1000.0,
    "leverage": 1,
    "units": 6.66,
}


def test_position_accepts_payload_without_position_id():
    """v7.1.3: positionId mancante non solleva piu' (era il bug B2)."""
    payload = dict(_BASE_REQUIRED)
    pos = EtoroPosition.model_validate(payload)
    assert pos.position_id is None


def test_position_accepts_payload_without_cid():
    """cid mancante non solleva piu'."""
    payload = dict(_BASE_REQUIRED)
    pos = EtoroPosition.model_validate(payload)
    assert pos.cid is None


def test_position_accepts_payload_without_instrument_id():
    """instrumentId mancante non solleva piu'."""
    payload = dict(_BASE_REQUIRED)
    pos = EtoroPosition.model_validate(payload)
    assert pos.instrument_id is None


def test_position_accepts_payload_with_all_three():
    """Quando i 3 campi ci sono, vengono parsati correttamente (non regressione)."""
    payload = {
        **_BASE_REQUIRED,
        "positionId": 12345,
        "cid": 99999,
        "instrumentId": 1001,
    }
    pos = EtoroPosition.model_validate(payload)
    assert pos.position_id == 12345
    assert pos.cid == 99999
    assert pos.instrument_id == 1001


def test_position_direction_property_independent_of_id():
    """direction e' derivata da is_buy, non dipende dai 3 campi opzionali."""
    payload = {**_BASE_REQUIRED, "isBuy": False}
    pos = EtoroPosition.model_validate(payload)
    assert pos.direction == "SHORT"


def test_portfolio_response_with_mixed_positions():
    """Lista di posizioni con/senza instrumentId — entrambe parseabili.

    Riproduce esattamente lo scenario del bug B2: 21 posizioni dove alcune
    hanno instrumentId e altre no. Prima del fix, TUTTE causavano error;
    ora il parsing va a buon fine e il filtro avviene a livello importer.
    """
    payload = {
        "clientPortfolio": {
            "credit": 1234.56,
            "unrealizedPnL": 100.0,
            "positions": [
                # Con tutti gli ID (caso "vecchio formato")
                {**_BASE_REQUIRED, "positionId": 1, "cid": 100, "instrumentId": 1001},
                # Senza nessuno (caso "nuovo formato")
                {**_BASE_REQUIRED},
                # Solo instrumentId (caso ibrido)
                {**_BASE_REQUIRED, "instrumentId": 1003},
            ],
        }
    }
    parsed = parse_portfolio_response(payload)
    assert isinstance(parsed, EtoroPortfolioResponse)
    positions = parsed.client_portfolio.positions
    assert len(positions) == 3
    # Conta posizioni utilizzabili (con instrument_id risolvibile)
    usable = [p for p in positions if p.instrument_id is not None]
    assert len(usable) == 2  # la prima e la terza
    assert positions[0].instrument_id == 1001
    assert positions[1].instrument_id is None
    assert positions[2].instrument_id == 1003


def test_pnl_alias_still_works():
    """Non regressione: alias pnL -> pnl funziona."""
    payload = {**_BASE_REQUIRED, "pnL": 25.50}
    pos = EtoroPosition.model_validate(payload)
    assert pos.pnl == pytest.approx(25.50)
