"""Client per eToro Public API (v7.1.3).

Aggiunto metodo get_instrument_id_from_order() per supportare
la risoluzione tier-4 via orderId (richiesto da etoro_importer v7.3.0).
Migliorata validazione del campo instrumentID nella risposta degli ordini.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from personal.data_entry.etoro_models import (
    EtoroInstrument,
    EtoroInstrumentRate,
    EtoroPortfolioResponse,
    parse_portfolio_response,
)
from shared.config.operational_config import OP_CONFIG

__version__ = "7.1.3"

__all__ = [
    "EtoroAuthError",
    "EtoroClient",
    "EtoroClientError",
    "EtoroNetworkError",
    "EtoroRateLimitError",
]

log = logging.getLogger(__name__)

_BASE_URL = "https://public-api.etoro.com/api/v1"
_PORTFOLIO_PNL_PATH = "/trading/info/real/pnl"
_INSTRUMENTS_PATH = "/market-data/instruments"
_RATES_PATH = "/market-data/rates"
_ORDERS_PATH = "/trading/info/real/orders"  # per risoluzione via orderId
_SEARCH_PATH = "/market-data/search"

# [v8.1.0 FIX-P4] Costanti operative → config/operational_defaults.yaml
# Per modificare questi valori, aggiornare il YAML e riavviare.
_DEFAULT_TIMEOUT: float = OP_CONFIG.http.default_timeout_s
_DEFAULT_MAX_RETRIES: int = OP_CONFIG.http.max_retries
_DEFAULT_RETRY_BASE_DELAY: float = OP_CONFIG.http.retry_base_delay_s
class EtoroClientError(Exception):
    """Base exception del client eToro."""


class EtoroAuthError(EtoroClientError):
    """Autenticazione fallita."""


class EtoroRateLimitError(EtoroClientError):
    """Rate limit raggiunto."""


class EtoroNetworkError(EtoroClientError):
    """Errore di rete."""


@dataclass(frozen=True, slots=True)
class EtoroClientConfig:
    api_key: str
    user_key: str
    base_url: str = _BASE_URL
    timeout: float = _DEFAULT_TIMEOUT
    max_retries: int = _DEFAULT_MAX_RETRIES
    retry_base_delay: float = _DEFAULT_RETRY_BASE_DELAY


class EtoroClient:
    def __init__(self, config: EtoroClientConfig) -> None:
        if not config.api_key:
            raise EtoroAuthError("ETORO_API_KEY mancante.")
        if not config.user_key:
            raise EtoroAuthError("ETORO_USER_KEY mancante.")
        self._config = config
        self._instrument_cache: dict[int, EtoroInstrument] = {}

    @classmethod
    def from_env(
        cls,
        api_key_var: str = "ETORO_API_KEY",
        user_key_var: str = "ETORO_USER_KEY",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> EtoroClient:
        api_key = os.environ.get(api_key_var, "").strip()
        user_key = os.environ.get(user_key_var, "").strip()
        if not api_key:
            raise EtoroAuthError(f"Variabile d'ambiente {api_key_var} mancante.")
        if not user_key:
            raise EtoroAuthError(f"Variabile d'ambiente {user_key_var} mancante.")
        config = EtoroClientConfig(api_key=api_key, user_key=user_key, timeout=timeout)
        return cls(config)

    def get_real_portfolio(self) -> EtoroPortfolioResponse:
        payload = self._get_json(_PORTFOLIO_PNL_PATH)
        # [v8.1.0 FIX-P1] Debug block protetto da env var (mai in produzione).
        # Per abilitare in locale: ETORO_DEBUG_PAYLOAD=1 python -m ...
        if os.getenv("ETORO_DEBUG_PAYLOAD"):  # pragma: no cover
            import json as _json, pathlib as _pathlib
            _pathlib.Path("etoro_raw_payload.json").write_text(
                _json.dumps(payload, indent=2, ensure_ascii=False)
            )
        positions_raw = payload.get("clientPortfolio", {}).get("positions", [])
        if positions_raw:
            log.debug(
                "etoro.position_keys_received",
                extra={
                    "first_position_keys": sorted(list(positions_raw[0].keys())),
                    "n_positions": len(positions_raw),
                },
            )
        return parse_portfolio_response(payload)

    def get_instruments(self, instrument_ids: list[int]) -> dict[int, EtoroInstrument]:
        if not instrument_ids:
            return {}
        missing = [iid for iid in instrument_ids if iid not in self._instrument_cache]
        if missing:
            ids_csv = ",".join(str(iid) for iid in missing)
            payload = self._get_json(_INSTRUMENTS_PATH, params={"instrumentIds": ids_csv})
            instruments_raw = payload if isinstance(payload, list) else payload.get("instruments", [])
            for raw in instruments_raw:
                try:
                    inst = EtoroInstrument.model_validate(raw)
                    self._instrument_cache[inst.instrument_id] = inst
                except Exception as exc:
                    log.warning("Failed to parse instrument %s: %s", raw, exc)
        return {iid: self._instrument_cache[iid] for iid in instrument_ids if iid in self._instrument_cache}

    def get_rates(self, instrument_ids: list[int]) -> dict[int, EtoroInstrumentRate]:
        if not instrument_ids:
            return {}
        ids_csv = ",".join(str(iid) for iid in instrument_ids)
        payload = self._get_json(_RATES_PATH, params={"instrumentIds": ids_csv})
        rates_raw = payload if isinstance(payload, list) else payload.get("rates", [])
        out: dict[int, EtoroInstrumentRate] = {}
        for raw in rates_raw:
            try:
                rate = EtoroInstrumentRate.model_validate(raw)
                out[rate.instrument_id] = rate
            except Exception as exc:
                log.warning("Failed to parse rate %s: %s", raw, exc)
        return out

    def search_instrument(self, ticker: str, *, fields: tuple[str, ...] = ()) -> list[EtoroInstrument]:
        if not ticker.strip():
            return []
        default_fields = (
            "instrumentId", "displayName", "ticker", "symbol", "name",
            "assetClassId", "exchangeId",
        )
        params = {
            "internalSymbolFull": ticker.strip(),
            "fields": ",".join(fields or default_fields),
        }
        payload = self._get_json(_SEARCH_PATH, params=params)
        results_raw = payload if isinstance(payload, list) else payload.get("results", [])
        return [EtoroInstrument.model_validate(r) for r in results_raw if isinstance(r, dict)]

    # ── NUOVO: risoluzione via orderId (richiesto da etoro_importer v7.3.0) ──
    def get_instrument_id_from_order(self, order_id: int) -> int | None:
        """Recupera instrumentID da un orderId.
        
        GET /api/v1/trading/info/real/orders/{orderId}
        → il campo 'instrumentID' è obbligatorio nella risposta (API v1.158.0).
        """
        path = f"{_ORDERS_PATH}/{order_id}"
        try:
            payload = self._get_json(path)
            # Validazione: il campo instrumentID deve esistere ed essere convertibile a int
            if not isinstance(payload, dict) or "instrumentID" not in payload:
                log.warning("get_instrument_id_from_order(%d): 'instrumentID' non presente nella risposta.", order_id)
                return None
            iid = payload["instrumentID"]
            return int(iid)
        except (ValueError, TypeError) as exc:
            log.warning("get_instrument_id_from_order(%d): formato instrumentID non valido - %s", order_id, exc)
        except EtoroClientError as exc:
            log.warning("get_instrument_id_from_order(%d) failed: %s", order_id, exc)
        return None

    def _build_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._config.api_key,
            "x-user-key": self._config.user_key,
            "x-request-id": str(uuid.uuid4()),
            "Accept": "application/json",
            "User-Agent": "MarketAI/7.1.3 (Python urllib)",
        }

    def _build_url(self, path: str, params: dict[str, str] | None = None) -> str:
        url = f"{self._config.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return url

    def _get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any:
        url = self._build_url(path, params)
        last_exc: Exception | None = None
        for attempt in range(self._config.max_retries):
            try:
                return self._do_request(url)
            except EtoroRateLimitError as exc:
                last_exc = exc
                wait = self._config.retry_base_delay * (2 ** (attempt + 1))
                log.warning("Rate limit (attempt %d): wait %.1fs", attempt + 1, wait)
                time.sleep(wait)
            except EtoroNetworkError as exc:
                last_exc = exc
                if attempt == self._config.max_retries - 1:
                    raise
                wait = self._config.retry_base_delay * (2 ** attempt)
                log.warning("Network error (attempt %d): %s; wait %.1fs", attempt + 1, exc, wait)
                time.sleep(wait)
            except EtoroAuthError:
                raise
            except EtoroClientError:
                raise
        raise last_exc

    def _do_request(self, url: str) -> Any:
        req = urllib.request.Request(url, headers=self._build_headers())
        try:
            with urllib.request.urlopen(req, timeout=self._config.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            self._raise_for_http_error(exc)
            raise
        except TimeoutError as exc:
            raise EtoroNetworkError(f"Timeout su {url}") from exc
        except urllib.error.URLError as exc:
            raise EtoroNetworkError(f"Errore di rete: {exc.reason}") from exc
        except OSError as exc:
            raise EtoroNetworkError(f"Errore I/O: {exc}") from exc
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EtoroClientError(f"Risposta non-JSON da {url}") from exc

    @staticmethod
    def _raise_for_http_error(exc: urllib.error.HTTPError) -> None:
        code = exc.code
        try:
            body_preview = exc.read(OP_CONFIG.http.error_body_preview_bytes).decode("utf-8", errors="replace")
        except OSError:
            body_preview = ""
        if code == 401:
            raise EtoroAuthError(f"HTTP 401: API key invalida.") from exc
        if code == 403:
            raise EtoroAuthError(f"HTTP 403: accesso negato.") from exc
        if code == 429:
            raise EtoroRateLimitError(f"HTTP 429: rate limit.") from exc
        if 500 <= code < 600:
            raise EtoroNetworkError(f"HTTP {code}: errore lato eToro.") from exc
        raise EtoroClientError(f"HTTP {code}: {exc.reason}") from exc