"""Client per eToro Public API (v7.1.1).

Sostituisce il parsing manuale di file XLSX (che richiedeva all'utente di
scaricare l'Account Statement) con chiamate dirette all'API ufficiale eToro.

Riferimenti:
  - Portal: https://api-portal.etoro.com/
  - Auth:   https://api-portal.etoro.com/getting-started/authentication
  - PnL:    https://api-portal.etoro.com/api-reference/trading--real/get-real-account-pnl-and-portfolio-details

Pre-requisiti utente:
  1. Account eToro verified (KYC completo).
  2. Generare API key da Settings → Trade → Get API Keys.
  3. Salvare in .env:
        ETORO_API_KEY=<x-api-key>
        ETORO_USER_KEY=<x-user-key>

Pattern d'uso::

    from personal.data_entry.etoro_client import EtoroClient

    client = EtoroClient.from_env()
    portfolio = client.get_real_portfolio()
    for pos in portfolio.client_portfolio.positions:
        print(pos.position_id, pos.direction, pos.amount)

Architettura:
  - urllib.request (stdlib): zero dipendenze nuove, sufficiente per
    chiamate occasionali (max ~10/min in tipico uso UI).
  - Cache in-process (dict) per gli instrument_id -> simbolo (immutabile).
  - Retry exponenziale su 429 (rate limit) e 5xx.
  - Auth via 3 header: x-api-key, x-user-key, x-request-id (UUID per call).
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

__version__ = "7.1.1"

__all__ = [
    "EtoroAuthError",
    "EtoroClient",
    "EtoroClientError",
    "EtoroNetworkError",
    "EtoroRateLimitError",
]

log = logging.getLogger(__name__)

# Endpoints
_BASE_URL = "https://public-api.etoro.com/api/v1"
_PORTFOLIO_PNL_PATH = "/trading/info/real/pnl"
_INSTRUMENTS_PATH = "/market-data/instruments"
_RATES_PATH = "/market-data/rates"
_SEARCH_PATH = "/market-data/search"

# Default timeouts
_DEFAULT_TIMEOUT = 15.0  # secondi
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_RETRY_BASE_DELAY = 1.0  # esponenziale: 1s, 2s, 4s


# ───────────────────────────────────────────────────────────── exceptions
class EtoroClientError(Exception):
    """Base exception del client eToro."""


class EtoroAuthError(EtoroClientError):
    """Autenticazione fallita: API key mancante o invalida."""


class EtoroRateLimitError(EtoroClientError):
    """Rate limit raggiunto. Riprovare piu' tardi."""


class EtoroNetworkError(EtoroClientError):
    """Errore di rete (DNS, timeout, connessione rifiutata)."""


# ───────────────────────────────────────────────────────────── config
@dataclass(frozen=True, slots=True)
class EtoroClientConfig:
    """Configurazione client. Immutabile."""

    api_key: str
    user_key: str
    base_url: str = _BASE_URL
    timeout: float = _DEFAULT_TIMEOUT
    max_retries: int = _DEFAULT_MAX_RETRIES
    retry_base_delay: float = _DEFAULT_RETRY_BASE_DELAY


# ───────────────────────────────────────────────────────────── client
class EtoroClient:
    """Client sincrono per eToro Public API.

    Thread-safe: la cache instrument_id e' protetta da un lock interno.
    """

    def __init__(self, config: EtoroClientConfig) -> None:
        if not config.api_key:
            raise EtoroAuthError("ETORO_API_KEY mancante.")
        if not config.user_key:
            raise EtoroAuthError("ETORO_USER_KEY mancante.")
        self._config = config
        # Cache instrument_id -> EtoroInstrument
        self._instrument_cache: dict[int, EtoroInstrument] = {}

    # ─────────────────────────────────────────────────── factory
    @classmethod
    def from_env(
        cls,
        api_key_var: str = "ETORO_API_KEY",
        user_key_var: str = "ETORO_USER_KEY",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> EtoroClient:
        """Costruisce client leggendo le credenziali da env vars.

        Raises:
            EtoroAuthError: se una delle env vars manca.
        """
        api_key = os.environ.get(api_key_var, "").strip()
        user_key = os.environ.get(user_key_var, "").strip()
        if not api_key:
            raise EtoroAuthError(
                f"Variabile d'ambiente {api_key_var} mancante. "
                f"Aggiungi al file .env il tuo eToro API key. "
                f"Vedi https://api-portal.etoro.com/getting-started/authentication"
            )
        if not user_key:
            raise EtoroAuthError(
                f"Variabile d'ambiente {user_key_var} mancante. "
                f"Aggiungi al file .env il tuo eToro user key. "
                f"Generalo da Settings → Trade → Get API Keys."
            )
        config = EtoroClientConfig(
            api_key=api_key, user_key=user_key, timeout=timeout
        )
        return cls(config)

    # ─────────────────────────────────────────────────── public api
    def get_real_portfolio(self) -> EtoroPortfolioResponse:
        """Recupera portfolio reale: posizioni, ordini, mirrors, PnL."""
        payload = self._get_json(_PORTFOLIO_PNL_PATH)
        import json, pathlib
        pathlib.Path("etoro_raw_payload.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        # v7.1.3 (fix B2): logga le keys della prima posizione raw per
        # diagnosticare cambi schema dell'API eToro. Non logga i valori
        # (potrebbero contenere PII o cifre sensibili) — solo i nomi
        # delle keys ricevute, utile per allineare il modello Pydantic.
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
    def get_instruments(
        self, instrument_ids: list[int]
    ) -> dict[int, EtoroInstrument]:
        """Risolve N instrument_id -> dettagli (ticker, exchange, ecc.).

        Usa cache locale: gli ID risolti in precedenza non rifanno HTTP.
        """
        if not instrument_ids:
            return {}

        # Filtra ID gia' in cache
        missing_ids = [
            iid for iid in instrument_ids if iid not in self._instrument_cache
        ]

        if missing_ids:
            # Batch request: API supporta CSV nei query params
            ids_csv = ",".join(str(iid) for iid in missing_ids)
            payload = self._get_json(
                _INSTRUMENTS_PATH, params={"instrumentIds": ids_csv}
            )
            # API ritorna lista di instrument dicts
            instruments_raw = (
                payload if isinstance(payload, list) else payload.get(
                    "instruments", []
                )
            )
            for raw in instruments_raw:
                try:
                    inst = EtoroInstrument.model_validate(raw)
                    self._instrument_cache[inst.instrument_id] = inst
                except (ValueError, TypeError) as exc:
                    log.warning(
                        "Failed to parse instrument %s: %s", raw, exc
                    )

        return {
            iid: self._instrument_cache[iid]
            for iid in instrument_ids
            if iid in self._instrument_cache
        }

    def get_rates(
        self, instrument_ids: list[int]
    ) -> dict[int, EtoroInstrumentRate]:
        """Quote live per N instrument_id."""
        if not instrument_ids:
            return {}
        ids_csv = ",".join(str(iid) for iid in instrument_ids)
        payload = self._get_json(
            _RATES_PATH, params={"instrumentIds": ids_csv}
        )
        rates_raw = (
            payload if isinstance(payload, list) else payload.get("rates", [])
        )
        out: dict[int, EtoroInstrumentRate] = {}
        for raw in rates_raw:
            try:
                rate = EtoroInstrumentRate.model_validate(raw)
                out[rate.instrument_id] = rate
            except (ValueError, TypeError) as exc:
                log.warning("Failed to parse rate %s: %s", raw, exc)
        return out

    def search_instrument(
        self, ticker: str, *, fields: tuple[str, ...] = ()
    ) -> list[EtoroInstrument]:
        """Cerca strumenti per ticker (es. 'AAPL', 'BTC').

        Args:
            ticker: simbolo da risolvere.
            fields: campi opzionali da richiedere (default: i comuni).
        """
        if not ticker.strip():
            return []
        default_fields = (
            "instrumentId",
            "displayName",
            "ticker",
            "symbol",
            "name",
            "assetClassId",
            "exchangeId",
        )
        params = {
            "internalSymbolFull": ticker.strip(),
            "fields": ",".join(fields or default_fields),
        }
        payload = self._get_json(_SEARCH_PATH, params=params)
        results_raw = (
            payload if isinstance(payload, list) else payload.get("results", [])
        )
        return [
            EtoroInstrument.model_validate(r)
            for r in results_raw
            if isinstance(r, dict)
        ]

    # ─────────────────────────────────────────────────── internal
    def _build_headers(self) -> dict[str, str]:
        """Costruisce gli header standard per ogni richiesta."""
        return {
            "x-api-key": self._config.api_key,
            "x-user-key": self._config.user_key,
            "x-request-id": str(uuid.uuid4()),
            "Accept": "application/json",
            "User-Agent": "MarketAI/7.1.1 (Python urllib)",
        }

    def _build_url(self, path: str, params: dict[str, str] | None = None) -> str:
        """Compose URL completa con eventuale query string."""
        url = f"{self._config.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return url

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        """GET con retry esponenziale. Ritorna payload parsato."""
        url = self._build_url(path, params)
        last_exc: Exception | None = None

        for attempt in range(self._config.max_retries):
            try:
                return self._do_request(url)
            except EtoroRateLimitError as exc:
                last_exc = exc
                # 429: backoff esponenziale piu' lungo
                wait = self._config.retry_base_delay * (2 ** (attempt + 1))
                log.warning(
                    "Rate limit (attempt %d/%d): wait %.1fs",
                    attempt + 1,
                    self._config.max_retries,
                    wait,
                )
                time.sleep(wait)
            except EtoroNetworkError as exc:
                last_exc = exc
                if attempt == self._config.max_retries - 1:
                    raise
                wait = self._config.retry_base_delay * (2 ** attempt)
                log.warning(
                    "Network error (attempt %d/%d): %s; wait %.1fs",
                    attempt + 1,
                    self._config.max_retries,
                    exc,
                    wait,
                )
                time.sleep(wait)
            except EtoroAuthError:
                # 401/403: non ha senso retentare
                raise
            except EtoroClientError:
                # 4xx generici: non retentare
                raise

        # Esauriti i retry
        assert last_exc is not None
        raise last_exc

    def _do_request(self, url: str) -> Any:
        """Esegue una singola GET. Solleva exception classificata."""
        req = urllib.request.Request(url, headers=self._build_headers())
        try:
            with urllib.request.urlopen(
                req, timeout=self._config.timeout
            ) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            self._raise_for_http_error(exc)
            raise  # not reached, ma necessario per type checker
        except TimeoutError as exc:
            raise EtoroNetworkError(
                f"Timeout dopo {self._config.timeout}s su {url}"
            ) from exc
        except urllib.error.URLError as exc:
            raise EtoroNetworkError(f"Errore di rete: {exc.reason}") from exc
        except OSError as exc:
            raise EtoroNetworkError(f"Errore I/O: {exc}") from exc

        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EtoroClientError(
                f"Risposta non-JSON valida da {url}"
            ) from exc

    @staticmethod
    def _raise_for_http_error(exc: urllib.error.HTTPError) -> None:
        """Mappa HTTPError -> exception classificata del client."""
        code = exc.code
        try:
            body_preview = exc.read(2048).decode("utf-8", errors="replace")
        except OSError:
            body_preview = ""

        if code == 401:
            raise EtoroAuthError(
                f"HTTP 401: API key invalida o scaduta. "
                f"Verifica ETORO_API_KEY e ETORO_USER_KEY in .env. "
                f"Body: {body_preview[:200]}"
            ) from exc
        if code == 403:
            raise EtoroAuthError(
                f"HTTP 403: accesso negato. "
                f"Verifica che la API key abbia i permessi necessari "
                f"(Read per portfolio, Write per ordini). "
                f"Body: {body_preview[:200]}"
            ) from exc
        if code == 429:
            raise EtoroRateLimitError(
                f"HTTP 429: rate limit raggiunto. "
                f"Body: {body_preview[:200]}"
            ) from exc
        if 500 <= code < 600:
            raise EtoroNetworkError(
                f"HTTP {code}: errore lato eToro (5xx). "
                f"Body: {body_preview[:200]}"
            ) from exc
        # 4xx generico
        raise EtoroClientError(
            f"HTTP {code}: {exc.reason}. Body: {body_preview[:200]}"
        ) from exc
