"""Test di regressione BUG-P1 — etoro_client.py debug code removal.

Verifica che get_real_portfolio() NON scriva etoro_raw_payload.json su disco
in condizioni normali (ETORO_DEBUG_PAYLOAD non impostato).

Rif: ROADMAP_CODE_QUALITY_v1.0 Settimana 1 — P1 (Critica).
"""
from __future__ import annotations

import json
import pathlib
from unittest import mock

import pytest

from personal.data_entry.etoro_client import EtoroClient, EtoroClientConfig


def _make_portfolio_response() -> mock.MagicMock:
    payload = {
        "clientPortfolio": {
            "credit": 1000.0,
            "unrealizedPnL": 50.0,
            "positions": [],
        }
    }
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__ = mock.MagicMock(return_value=resp)
    resp.__exit__ = mock.MagicMock(return_value=False)
    return resp


def test_get_real_portfolio_does_not_create_debug_file(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BUG-P1: in produzione nessun file debug deve essere scritto su disco."""
    monkeypatch.delenv("ETORO_DEBUG_PAYLOAD", raising=False)
    monkeypatch.chdir(tmp_path)

    client = EtoroClient(EtoroClientConfig(api_key="x", user_key="y", max_retries=1))
    with mock.patch(
        "personal.data_entry.etoro_client.urllib.request.urlopen",
        return_value=_make_portfolio_response(),
    ):
        portfolio = client.get_real_portfolio()

    assert portfolio.client_portfolio.credit == 1000.0
    debug_file = tmp_path / "etoro_raw_payload.json"
    assert not debug_file.exists(), (
        f"BUG-P1 REGRESSIONE: etoro_raw_payload.json creato in {debug_file}. "
        "Verificare che il blocco debug sia protetto da ETORO_DEBUG_PAYLOAD."
    )


def test_get_real_portfolio_creates_debug_file_when_env_set(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con ETORO_DEBUG_PAYLOAD=1, il file debug DEVE essere creato."""
    monkeypatch.setenv("ETORO_DEBUG_PAYLOAD", "1")
    monkeypatch.chdir(tmp_path)

    client = EtoroClient(EtoroClientConfig(api_key="x", user_key="y", max_retries=1))
    with mock.patch(
        "personal.data_entry.etoro_client.urllib.request.urlopen",
        return_value=_make_portfolio_response(),
    ):
        client.get_real_portfolio()

    debug_file = tmp_path / "etoro_raw_payload.json"
    assert debug_file.exists(), "Con ETORO_DEBUG_PAYLOAD=1 il file debug deve esistere."
    data = json.loads(debug_file.read_text(encoding="utf-8"))
    assert "clientPortfolio" in data
