"""Test del client API eToro (v7.1.1) e dei modelli Pydantic.

Test mockati: non vogliamo fare chiamate reali all'API in CI.
"""
from __future__ import annotations

import io
import json
from unittest import mock
from urllib.error import HTTPError, URLError

import pytest

from personal.data_entry.etoro_client import (
    EtoroAuthError,
    EtoroClient,
    EtoroClientConfig,
    EtoroClientError,
    EtoroNetworkError,
    EtoroRateLimitError,
)
from personal.data_entry.etoro_models import (
    EtoroInstrument,
    EtoroPortfolioResponse,
    EtoroPosition,
    parse_portfolio_response,
)


# ===================================================== models
def test_position_direction_long() -> None:
    """is_buy=True -> direction='LONG'."""
    pos = EtoroPosition(
        positionId=1,
        cid=1,
        openDateTime="2024-01-01T09:00:00Z",
        openRate=100.0,
        instrumentId=1001,
        isBuy=True,
        amount=1000.0,
        leverage=1,
        units=10.0,
    )
    assert pos.direction == "LONG"
    assert pos.is_buy is True


def test_position_direction_short() -> None:
    """is_buy=False -> direction='SHORT'."""
    pos = EtoroPosition(
        positionId=1,
        cid=1,
        openDateTime="2024-01-01T09:00:00Z",
        openRate=100.0,
        instrumentId=1001,
        isBuy=False,
        amount=1000.0,
        leverage=1,
        units=10.0,
    )
    assert pos.direction == "SHORT"


def test_instrument_best_symbol_ticker_priority() -> None:
    """best_symbol preferisce ticker > symbol > display_name."""
    inst = EtoroInstrument(
        instrumentId=1001,
        ticker="AAPL",
        symbol="aapl",
        displayName="Apple Inc",
    )
    assert inst.best_symbol == "AAPL"


def test_instrument_best_symbol_fallback() -> None:
    """Senza ticker/symbol, usa display_name."""
    inst = EtoroInstrument(
        instrumentId=1001,
        displayName="Apple Inc",
    )
    assert inst.best_symbol == "Apple Inc"


def test_parse_portfolio_response_minimal() -> None:
    """Payload minimale parsato senza errori (gestione default)."""
    payload = {"clientPortfolio": {"credit": 1000.0}}
    response = parse_portfolio_response(payload)
    assert response.client_portfolio.credit == 1000.0
    assert response.client_portfolio.positions == []
    assert response.client_portfolio.orders == []


def test_parse_portfolio_response_with_positions() -> None:
    """Payload completo con posizioni."""
    payload = {
        "clientPortfolio": {
            "credit": 5000.5,
            "unrealizedPnL": 250.75,
            "positions": [
                {
                    "positionId": 1001,
                    "cid": 100,
                    "openDateTime": "2024-01-01T10:00:00Z",
                    "openRate": 187.42,
                    "instrumentId": 1001,
                    "isBuy": True,
                    "amount": 1000.0,
                    "leverage": 1,
                    "units": 5.34,
                    "pnL": 100.5,
                    "totalFees": 2.0,
                }
            ],
        }
    }
    response = parse_portfolio_response(payload)
    assert response.client_portfolio.credit == 5000.5
    assert response.client_portfolio.unrealized_pnl == 250.75
    assert len(response.client_portfolio.positions) == 1
    pos = response.client_portfolio.positions[0]
    assert pos.position_id == 1001
    assert pos.direction == "LONG"
    assert pos.units == 5.34


def test_parse_portfolio_response_ignores_extra_fields() -> None:
    """Campi extra non noti non rompono il parsing."""
    payload = {
        "clientPortfolio": {
            "credit": 100.0,
            "_some_new_api_field": "ignored",
            "positions": [],
        }
    }
    # Non deve sollevare
    response = parse_portfolio_response(payload)
    assert response.client_portfolio.credit == 100.0


# ===================================================== client init
def test_client_requires_api_key() -> None:
    """Constructor con api_key vuoto -> EtoroAuthError."""
    with pytest.raises(EtoroAuthError, match="API_KEY"):
        EtoroClient(EtoroClientConfig(api_key="", user_key="x"))


def test_client_requires_user_key() -> None:
    """Constructor con user_key vuoto -> EtoroAuthError."""
    with pytest.raises(EtoroAuthError, match="USER_KEY"):
        EtoroClient(EtoroClientConfig(api_key="x", user_key=""))


def test_from_env_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """from_env senza ETORO_API_KEY in env -> EtoroAuthError."""
    monkeypatch.delenv("ETORO_API_KEY", raising=False)
    monkeypatch.setenv("ETORO_USER_KEY", "x")
    with pytest.raises(EtoroAuthError, match="ETORO_API_KEY"):
        EtoroClient.from_env()


def test_from_env_with_both_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """from_env con entrambe le keys -> client costruito ok."""
    monkeypatch.setenv("ETORO_API_KEY", "fake_api")
    monkeypatch.setenv("ETORO_USER_KEY", "fake_user")
    client = EtoroClient.from_env()
    assert client._config.api_key == "fake_api"
    assert client._config.user_key == "fake_user"


# ===================================================== headers
def test_build_headers_includes_required_fields() -> None:
    """Ogni richiesta deve avere x-api-key, x-user-key, x-request-id."""
    client = EtoroClient(EtoroClientConfig(api_key="key1", user_key="key2"))
    headers = client._build_headers()
    assert headers["x-api-key"] == "key1"
    assert headers["x-user-key"] == "key2"
    assert "x-request-id" in headers
    # x-request-id deve essere un UUID v4 valido
    import uuid as uuid_mod
    parsed = uuid_mod.UUID(headers["x-request-id"])
    assert parsed.version == 4


def test_build_headers_unique_request_id() -> None:
    """Ogni call genera un x-request-id diverso (UUID univoci)."""
    client = EtoroClient(EtoroClientConfig(api_key="k", user_key="u"))
    h1 = client._build_headers()
    h2 = client._build_headers()
    assert h1["x-request-id"] != h2["x-request-id"]


# ===================================================== HTTP error mapping
def _make_mock_response(body_dict: dict) -> mock.MagicMock:
    """Helper: mock di una HTTPResponse riuscita."""
    body = json.dumps(body_dict).encode("utf-8")
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__ = mock.MagicMock(return_value=resp)
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


def test_http_401_raises_auth_error() -> None:
    """HTTP 401 -> EtoroAuthError con messaggio chiaro."""
    client = EtoroClient(
        EtoroClientConfig(api_key="x", user_key="y", max_retries=1)
    )
    err = HTTPError(
        url="http://x", code=401, msg="Unauthorized",
        hdrs=None, fp=io.BytesIO(b'{"error":"invalid api key"}'),  # type: ignore[arg-type]
    )
    with mock.patch(
        "personal.data_entry.etoro_client.urllib.request.urlopen",
        side_effect=err,
    ), pytest.raises(EtoroAuthError, match="401"):
        client.get_real_portfolio()


def test_http_403_raises_auth_error() -> None:
    """HTTP 403 -> EtoroAuthError (permessi insufficienti)."""
    client = EtoroClient(
        EtoroClientConfig(api_key="x", user_key="y", max_retries=1)
    )
    err = HTTPError(
        url="http://x", code=403, msg="Forbidden",
        hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
    )
    with mock.patch(
        "personal.data_entry.etoro_client.urllib.request.urlopen",
        side_effect=err,
    ), pytest.raises(EtoroAuthError, match="403"):
        client.get_real_portfolio()


def test_http_500_raises_network_error() -> None:
    """HTTP 5xx -> EtoroNetworkError dopo i retry esauriti."""
    client = EtoroClient(
        EtoroClientConfig(
            api_key="x", user_key="y",
            max_retries=2, retry_base_delay=0.001,  # retry veloci per test
        )
    )
    err = HTTPError(
        url="http://x", code=502, msg="Bad Gateway",
        hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
    )
    with mock.patch(
        "personal.data_entry.etoro_client.urllib.request.urlopen",
        side_effect=err,
    ), pytest.raises(EtoroNetworkError, match="502"):
        client.get_real_portfolio()


def test_http_429_eventually_raises_rate_limit() -> None:
    """HTTP 429 viene retentato; se persiste -> EtoroRateLimitError."""
    client = EtoroClient(
        EtoroClientConfig(
            api_key="x", user_key="y",
            max_retries=2, retry_base_delay=0.001,
        )
    )
    err = HTTPError(
        url="http://x", code=429, msg="Too Many Requests",
        hdrs=None, fp=io.BytesIO(b""),  # type: ignore[arg-type]
    )
    with mock.patch(
        "personal.data_entry.etoro_client.urllib.request.urlopen",
        side_effect=err,
    ), pytest.raises(EtoroRateLimitError, match="429"):
        client.get_real_portfolio()


def test_url_error_raises_network_error() -> None:
    """URLError -> EtoroNetworkError dopo retry esauriti."""
    client = EtoroClient(
        EtoroClientConfig(
            api_key="x", user_key="y",
            max_retries=2, retry_base_delay=0.001,
        )
    )
    with mock.patch(
        "personal.data_entry.etoro_client.urllib.request.urlopen",
        side_effect=URLError("Network unreachable"),
    ), pytest.raises(EtoroNetworkError):
        client.get_real_portfolio()


# ===================================================== success cases
def test_get_real_portfolio_success() -> None:
    """Risposta JSON valida -> EtoroPortfolioResponse parsato."""
    client = EtoroClient(
        EtoroClientConfig(api_key="x", user_key="y", max_retries=1)
    )
    payload = {
        "clientPortfolio": {
            "credit": 1500.0,
            "unrealizedPnL": 75.5,
            "positions": [
                {
                    "positionId": 9001,
                    "cid": 100,
                    "openDateTime": "2024-01-01T09:00:00Z",
                    "openRate": 100.0,
                    "instrumentId": 1001,
                    "isBuy": True,
                    "amount": 500.0,
                    "leverage": 1,
                    "units": 5.0,
                    "pnL": 50.0,
                }
            ],
        }
    }
    with mock.patch(
        "personal.data_entry.etoro_client.urllib.request.urlopen",
        return_value=_make_mock_response(payload),
    ):
        response = client.get_real_portfolio()
    assert response.client_portfolio.credit == 1500.0
    assert len(response.client_portfolio.positions) == 1


def test_get_instruments_caches_results() -> None:
    """get_instruments cacha gli ID risolti, evita chiamate duplicate."""
    client = EtoroClient(
        EtoroClientConfig(api_key="x", user_key="y", max_retries=1)
    )
    payload = [
        {"instrumentId": 1001, "ticker": "AAPL", "displayName": "Apple"},
        {"instrumentId": 1002, "ticker": "MSFT", "displayName": "Microsoft"},
    ]
    with mock.patch(
        "personal.data_entry.etoro_client.urllib.request.urlopen",
        return_value=_make_mock_response(payload),
    ) as mock_urlopen:
        # Prima chiamata: HTTP fatto
        result1 = client.get_instruments([1001, 1002])
        assert mock_urlopen.call_count == 1
        # Seconda chiamata con stessi ID: cache hit, NIENTE HTTP
        result2 = client.get_instruments([1001, 1002])
        assert mock_urlopen.call_count == 1  # ancora 1, non 2!

    assert result1[1001].ticker == "AAPL"
    assert result2[1002].ticker == "MSFT"


def test_get_instruments_partial_cache_miss() -> None:
    """Se solo alcuni ID sono in cache, fa request solo per i mancanti."""
    client = EtoroClient(
        EtoroClientConfig(api_key="x", user_key="y", max_retries=1)
    )
    # Pre-popola cache con 1001
    client._instrument_cache[1001] = EtoroInstrument(
        instrumentId=1001, ticker="AAPL"
    )

    payload = [
        {"instrumentId": 1002, "ticker": "MSFT", "displayName": "Microsoft"},
    ]
    with mock.patch(
        "personal.data_entry.etoro_client.urllib.request.urlopen",
        return_value=_make_mock_response(payload),
    ) as mock_urlopen:
        result = client.get_instruments([1001, 1002])
        # Solo 1 HTTP call per il missing 1002
        assert mock_urlopen.call_count == 1

    assert result[1001].ticker == "AAPL"
    assert result[1002].ticker == "MSFT"


def test_get_instruments_empty_input() -> None:
    """Lista vuota -> dict vuoto, nessuna chiamata HTTP."""
    client = EtoroClient(
        EtoroClientConfig(api_key="x", user_key="y")
    )
    with mock.patch(
        "personal.data_entry.etoro_client.urllib.request.urlopen",
    ) as mock_urlopen:
        result = client.get_instruments([])
    assert result == {}
    mock_urlopen.assert_not_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
