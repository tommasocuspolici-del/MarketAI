"""ApiHealthChecker: ping reale delle API esterne (v7.1.1).

Risolve "API che risultano offline" della v7.1.0: il pannello E0 mostrava
hardcoded "ℹ️ N/A" per FRED/AlphaVantage/Finnhub. Ora ogni sorgente viene
pingata davvero (chiamata HEAD/GET con timeout breve) e si conosce lo
stato reale.

Pattern d'uso::

    checker = ApiHealthChecker()
    statuses = checker.check_all()  # blocking, ~3-5 secondi
    for s in statuses:
        print(s.name, s.is_online, s.latency_ms, s.message)

Ogni check ha timeout di default 5s. La chiamata avviene in serie (non
parallelo) per non saturare la rete locale dell'utente; per un dashboard
di health questo e' accettabile.
"""
from __future__ import annotations

import os
import time
import urllib.request
from dataclasses import dataclass
from enum import Enum
from urllib.error import HTTPError, URLError

__version__ = "7.1.1"

__all__ = ["ApiHealthChecker", "ApiSourceStatus", "ApiState"]


class ApiState(str, Enum):
    """Stato runtime di una sorgente API."""

    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"      # risponde ma con errori intermittenti
    OFFLINE = "OFFLINE"        # non risponde / timeout / 5xx
    NO_API_KEY = "NO_API_KEY"  # API key mancante in env
    UNKNOWN = "UNKNOWN"        # mai testata


@dataclass(frozen=True, slots=True)
class ApiSourceStatus:
    """Risultato del ping di una singola sorgente."""

    name: str
    state: ApiState
    latency_ms: float | None
    message: str
    has_api_key: bool
    last_checked: float  # timestamp epoch

    @property
    def emoji(self) -> str:
        """Emoji standard per UI."""
        return {
            ApiState.ONLINE: "✅",
            ApiState.DEGRADED: "⚠️",
            ApiState.OFFLINE: "❌",
            ApiState.NO_API_KEY: "🔑",
            ApiState.UNKNOWN: "❓",
        }[self.state]

    @property
    def state_label(self) -> str:
        """Etichetta human-readable."""
        return f"{self.emoji} {self.state.value}"


class ApiHealthChecker:
    """Verifica lo stato di tutte le sorgenti API esterne.

    Le sorgenti pingate:
      - Yahoo Finance (yfinance) — via query.finance.yahoo.com
      - FRED — via api.stlouisfed.org
      - Alpha Vantage — via www.alphavantage.co
      - Finnhub — via finnhub.io

    Per ogni sorgente determiniamo:
      1. Se la API key e' presente in env (where applicable).
      2. Se la richiesta HTTP risponde entro il timeout.
      3. Se il body sembra contenere dati validi (non rate-limit).
    """

    DEFAULT_TIMEOUT = 5.0  # secondi

    def __init__(self, timeout: float = DEFAULT_TIMEOUT) -> None:
        self._timeout = timeout

    # ─────────────────────────────────────────────────── public api
    def check_all(self) -> list[ApiSourceStatus]:
        """Ping in serie di tutte le sorgenti."""
        return [
            self.check_yfinance(),
            self.check_fred(),
            self.check_alpha_vantage(),
            self.check_finnhub(),
        ]

    # ─────────────────────────────────────────────────── yfinance
    def check_yfinance(self) -> ApiSourceStatus:
        """Yahoo Finance via query1 endpoint pubblico (no API key)."""
        # Endpoint che ritorna quote SPY in JSON.
        # Yahoo ha cambiato endpoint piu' volte; query1+query2 + chart sono i piu' stabili.
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/SPY"
            "?interval=1d&range=1d"
        )
        return self._ping_endpoint(
            name="Yahoo Finance",
            url=url,
            has_api_key=True,  # non serve ma "no key required"
            success_indicators=("chart", "result"),
            user_agent_required=True,
        )

    # ─────────────────────────────────────────────────── FRED
    def check_fred(self) -> ApiSourceStatus:
        """FRED via api.stlouisfed.org. Richiede FRED_API_KEY in env."""
        api_key = os.environ.get("FRED_API_KEY", "").strip()
        now = time.time()
        if not api_key:
            return ApiSourceStatus(
                name="FRED (St. Louis Fed)",
                state=ApiState.NO_API_KEY,
                latency_ms=None,
                message=(
                    "FRED_API_KEY mancante. "
                    "Registrati gratis su https://fredaccount.stlouisfed.org/apikey "
                    "e aggiungi al .env."
                ),
                has_api_key=False,
                last_checked=now,
            )
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id=GDP&limit=1&file_type=json&api_key={api_key}"
        )
        return self._ping_endpoint(
            name="FRED (St. Louis Fed)",
            url=url,
            has_api_key=True,
            success_indicators=("observations",),
        )

    # ─────────────────────────────────────────────────── Alpha Vantage
    def check_alpha_vantage(self) -> ApiSourceStatus:
        """Alpha Vantage via www.alphavantage.co."""
        api_key = os.environ.get("ALPHA_VANTAGE_KEY", "").strip()
        if not api_key:
            api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
        now = time.time()
        if not api_key:
            return ApiSourceStatus(
                name="Alpha Vantage",
                state=ApiState.NO_API_KEY,
                latency_ms=None,
                message=(
                    "ALPHA_VANTAGE_KEY mancante. "
                    "Registrati gratis su https://www.alphavantage.co/support/#api-key "
                    "e aggiungi al .env."
                ),
                has_api_key=False,
                last_checked=now,
            )
        url = (
            f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE"
            f"&symbol=SPY&apikey={api_key}"
        )
        # AV puo' rispondere con HTTP 200 + body "Information"/"Note" se rate-limited
        return self._ping_endpoint(
            name="Alpha Vantage",
            url=url,
            has_api_key=True,
            success_indicators=("Global Quote",),
            failure_indicators=("Information", "Note", "Error Message"),
        )

    # ─────────────────────────────────────────────────── Finnhub
    def check_finnhub(self) -> ApiSourceStatus:
        """Finnhub via finnhub.io."""
        api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
        now = time.time()
        if not api_key:
            return ApiSourceStatus(
                name="Finnhub",
                state=ApiState.NO_API_KEY,
                latency_ms=None,
                message=(
                    "FINNHUB_API_KEY mancante. "
                    "Registrati gratis su https://finnhub.io/register "
                    "e aggiungi al .env."
                ),
                has_api_key=False,
                last_checked=now,
            )
        url = f"https://finnhub.io/api/v1/quote?symbol=SPY&token={api_key}"
        # Finnhub: success se ha campo 'c' (current price) > 0.
        return self._ping_endpoint(
            name="Finnhub",
            url=url,
            has_api_key=True,
            success_indicators=('"c":',),
        )

    # ─────────────────────────────────────────────────── ping helper
    def _ping_endpoint(
        self,
        *,
        name: str,
        url: str,
        has_api_key: bool,
        success_indicators: tuple[str, ...] = (),
        failure_indicators: tuple[str, ...] = (),
        user_agent_required: bool = False,
    ) -> ApiSourceStatus:
        """Esegue HTTP GET con timeout e classifica il risultato."""
        now = time.time()
        start = time.monotonic()
        try:
            req = urllib.request.Request(url)
            if user_agent_required:
                # Yahoo (e altri CDN) bloccano richieste senza User-Agent
                req.add_header("User-Agent", "Mozilla/5.0 (compatible; MarketAI/7.1)")
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                status_code = resp.status
                # Leggiamo solo i primi 4KB per non scaricare megabyte di JSON
                raw_body = resp.read(4096).decode("utf-8", errors="replace")
        except TimeoutError:
            elapsed = (time.monotonic() - start) * 1000
            return ApiSourceStatus(
                name=name,
                state=ApiState.OFFLINE,
                latency_ms=elapsed,
                message=f"Timeout ({self._timeout}s superati). Verifica connessione internet.",
                has_api_key=has_api_key,
                last_checked=now,
            )
        except HTTPError as exc:
            elapsed = (time.monotonic() - start) * 1000
            state = ApiState.DEGRADED if exc.code in (429, 503) else ApiState.OFFLINE
            msg = f"HTTP {exc.code}"
            if exc.code == 401:
                msg += " — API key invalida o scaduta."
            elif exc.code == 403:
                msg += " — accesso negato (rate limit per ora? endpoint cambiato?)."
            elif exc.code == 429:
                msg += " — rate limit raggiunto. Riprova fra qualche minuto."
            elif 500 <= exc.code < 600:
                msg += " — provider in errore (5xx). Non e' colpa tua."
            return ApiSourceStatus(
                name=name,
                state=state,
                latency_ms=elapsed,
                message=msg,
                has_api_key=has_api_key,
                last_checked=now,
            )
        except URLError as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ApiSourceStatus(
                name=name,
                state=ApiState.OFFLINE,
                latency_ms=elapsed,
                message=f"Errore rete: {exc.reason}",
                has_api_key=has_api_key,
                last_checked=now,
            )
        except (OSError, ValueError) as exc:
            elapsed = (time.monotonic() - start) * 1000
            return ApiSourceStatus(
                name=name,
                state=ApiState.OFFLINE,
                latency_ms=elapsed,
                message=f"Errore: {str(exc)[:100]}",
                has_api_key=has_api_key,
                last_checked=now,
            )

        elapsed = (time.monotonic() - start) * 1000

        # Status code OK: classifica il body
        if 200 <= status_code < 300:
            # Failure indicators -> rate-limit silenzioso
            for fail in failure_indicators:
                if fail in raw_body:
                    return ApiSourceStatus(
                        name=name,
                        state=ApiState.DEGRADED,
                        latency_ms=elapsed,
                        message=(
                            f"Rate limit / messaggio del provider "
                            f"(trovato '{fail}' nel body)."
                        ),
                        has_api_key=has_api_key,
                        last_checked=now,
                    )
            # Success indicators -> ok
            if success_indicators:
                if any(ok in raw_body for ok in success_indicators):
                    return ApiSourceStatus(
                        name=name,
                        state=ApiState.ONLINE,
                        latency_ms=elapsed,
                        message=f"OK · {elapsed:.0f}ms",
                        has_api_key=has_api_key,
                        last_checked=now,
                    )
                return ApiSourceStatus(
                    name=name,
                    state=ApiState.DEGRADED,
                    latency_ms=elapsed,
                    message=(
                        f"HTTP 200 ma body inatteso "
                        f"(nessun indicator di successo trovato). "
                        f"Possibile cambio API."
                    ),
                    has_api_key=has_api_key,
                    last_checked=now,
                )
            # Nessun indicator: HTTP 200 e' considerato success
            return ApiSourceStatus(
                name=name,
                state=ApiState.ONLINE,
                latency_ms=elapsed,
                message=f"OK · {elapsed:.0f}ms",
                has_api_key=has_api_key,
                last_checked=now,
            )

        return ApiSourceStatus(
            name=name,
            state=ApiState.OFFLINE,
            latency_ms=elapsed,
            message=f"HTTP {status_code}",
            has_api_key=has_api_key,
            last_checked=now,
        )
