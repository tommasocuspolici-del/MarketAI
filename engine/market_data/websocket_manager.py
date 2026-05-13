"""WebSocket Stream Manager — prezzi live da Finnhub in background thread.

Finnhub offre un WebSocket per ricevere trade tick in tempo reale.
Questo modulo gestisce la connessione in un asyncio loop separato
(thread daemon) in modo da non bloccare Streamlit o lo scheduler.

Endpoint: wss://ws.finnhub.io?token={api_key}
Subscribe: {"type":"subscribe","symbol":"AAPL"}
Trade msg: {"data":[{"s":"AAPL","p":150.0,"t":1714000000000,"v":500}],"type":"trade"}

Feature flag: realtime_websocket (Regola 29).
Rate limit Finnhub: 60 req/min, nessun limite esplicito sui messaggi WS.
API key: FINNHUB_API_KEY da .env (Regola 15).

ANTI-REGRESSIONE (v9.0 Sett.2):
  · Il loop asyncio gira in un THREAD SEPARATO — non nel thread principale
    Streamlit. get_price() è thread-safe tramite threading.Lock.
  · websockets 12.x usa `websockets.connect()` come context manager async.
    NON usare `websockets.asyncio.client` (aggiunto in 13.x, incompatibile
    con il pin attuale ">=12.0,<13.0").
  · Reconnect con exponential backoff: non spammare Finnhub in caso di
    rete intermittente — rispetta il rate budget (Regola 28).
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from shared.exceptions import ConfigurationError, FeatureDisabledError
from shared.feature_flags import is_enabled
from shared.logger import get_logger
from shared.metrics import metrics

__version__ = "9.0.0"
__all__ = ["LivePrice", "WebSocketStreamManager", "get_ws_manager"]

log = get_logger(__name__)

# Endpoint Finnhub WebSocket
_WS_BASE_URL = "wss://ws.finnhub.io"

# Reconnect: exponential backoff con cap (Regola 7: nessun magic number)
_RECONNECT_DELAY_BASE_S: float = 1.0
_RECONNECT_DELAY_MAX_S: float = 60.0
_MAX_RECONNECT_ATTEMPTS: int = 20

# Prezzo scartato se più vecchio di 90s (buffer sopra i 60s della Regola 25)
_PRICE_STALE_SECONDS: float = 90.0


@dataclass(frozen=True, slots=True)
class LivePrice:
    """Prezzo live ricevuto dal WebSocket Finnhub."""

    ticker: str
    price: float          # ultimo trade price
    volume: float         # volume del trade
    timestamp_ms: int     # timestamp Finnhub (epoch ms)
    received_at: float    # time.time() locale — usato per stale check


class WebSocketStreamManager:
    """Gestisce una connessione WebSocket Finnhub persistente in background.

    Ciclo di vita:
      1. ``start(tickers)``     — avvia thread daemon con asyncio loop
      2. ``get_price(ticker)``  — accede al dict in-memory (thread-safe)
      3. ``stop()``             — ferma il loop e il thread

    Thread-safety: ``self._prices`` è protetto da ``self._lock``.
    Il loop asyncio gira in ``self._thread`` (daemon) — non blocca
    né Streamlit né lo scheduler.

    Feature flag: richiede ``realtime_websocket: true``.
    """

    def __init__(self, api_key: str) -> None:
        # REGOLA 29: verifica flag all'istanziazione
        if not is_enabled("realtime_websocket"):
            raise FeatureDisabledError(
                "Feature 'realtime_websocket' is disabled. "
                "Enable in config/feature_flags.yaml to use WebSocket stream."
            )
        if not api_key:
            raise ConfigurationError(
                "FINNHUB_API_KEY is required for WebSocketStreamManager."
            )
        self._api_key: str = api_key
        self._prices: dict[str, LivePrice] = {}
        self._subscribed: set[str] = set()
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = asyncio.Event()   # segnale di shutdown interno
        self._running = False

    # ─── Public API ─────────────────────────────────────────────────────────

    def start(self, tickers: list[str]) -> None:
        """Avvia il thread WebSocket e si connette ai ticker specificati.

        Idempotente: se già in esecuzione, aggiorna solo la lista ticker.
        """
        with self._lock:
            if self._running:
                # Già avviato: aggiorna i ticker da subscribare
                new = set(tickers) - self._subscribed
                if new and self._loop is not None:
                    asyncio.run_coroutine_threadsafe(
                        self._subscribe_batch(list(new)), self._loop
                    )
                self._subscribed.update(tickers)
                return
            self._subscribed = set(tickers)
            self._running = True

        # Avvia thread daemon con proprio asyncio loop
        self._thread = threading.Thread(
            target=self._thread_main,
            name="ws-finnhub",
            daemon=True,  # non impedisce lo shutdown dell'app
        )
        self._thread.start()
        log.info("ws_manager.started", tickers=len(tickers))

    def stop(self) -> None:
        """Ferma il thread WebSocket in modo pulito."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._loop is not None:
            # Segnala lo stop al loop asyncio
            self._loop.call_soon_threadsafe(self._stop_event.set)

        if self._thread is not None:
            self._thread.join(timeout=5.0)

        log.info("ws_manager.stopped")

    def get_price(self, ticker: str) -> LivePrice | None:
        """Ritorna il prezzo live per il ticker, None se assente o stale.

        Un prezzo è considerato stale se ricevuto più di _PRICE_STALE_SECONDS fa.
        In quel caso la UI deve usare il fallback REST (Regola 25: ≤ 60s).
        """
        with self._lock:
            lp = self._prices.get(ticker)
        if lp is None:
            return None
        age = time.time() - lp.received_at
        if age > _PRICE_STALE_SECONDS:
            log.debug("ws_manager.price_stale", ticker=ticker, age_s=age)
            return None
        return lp

    def get_all_prices(self) -> dict[str, LivePrice]:
        """Snapshot del dict prezzi live (copia difensiva)."""
        with self._lock:
            return dict(self._prices)

    @property
    def is_running(self) -> bool:
        """True se il thread WebSocket è attivo."""
        return self._running and self._thread is not None and self._thread.is_alive()

    # ─── Thread/asyncio internals ────────────────────────────────────────────

    def _thread_main(self) -> None:
        """Entry point del thread daemon — crea e lancia l'asyncio loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        # reset stop_event nel nuovo loop
        self._stop_event = asyncio.Event()
        try:
            self._loop.run_until_complete(self._run_with_reconnect())
        except Exception as exc:
            log.error("ws_manager.thread_crashed", error=str(exc))
        finally:
            self._loop.close()
            self._loop = None

    async def _run_with_reconnect(self) -> None:
        """Loop principale con reconnect esponenziale."""
        attempt = 0
        delay = _RECONNECT_DELAY_BASE_S

        while not self._stop_event.is_set() and attempt < _MAX_RECONNECT_ATTEMPTS:
            try:
                await self._connect_and_stream()
                # Se la connessione è terminata normalmente (stop_event) → esci
                if self._stop_event.is_set():
                    break
                # Disconnessione non richiesta: reconnect
                attempt += 1
                log.warning(
                    "ws_manager.disconnected_reconnecting",
                    attempt=attempt,
                    delay_s=delay,
                )
            except Exception as exc:
                attempt += 1
                log.warning(
                    "ws_manager.connect_error",
                    error=str(exc)[:120],
                    attempt=attempt,
                    delay_s=delay,
                )

            # Backoff esponenziale con cap
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_DELAY_MAX_S)

        if attempt >= _MAX_RECONNECT_ATTEMPTS:
            log.error("ws_manager.max_reconnects_exceeded")

    async def _connect_and_stream(self) -> None:
        """Connetti al WebSocket, subscribe ai ticker, ricevi messaggi.

        ANTI-REGRESSIONE: websockets 12.x usa `websockets.connect()` (non
        `websockets.asyncio.client`). Non importare da `websockets.asyncio`
        — quel namespace esiste solo dalla 13.x.
        """
        try:
            import websockets  # type: ignore[import]
        except ImportError as exc:
            raise FeatureDisabledError(
                "websockets package not installed. "
                "Run: poetry install"
            ) from exc

        url = f"{_WS_BASE_URL}?token={self._api_key}"
        # Timeout ping/pong per rilevare connessioni zombie
        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            log.info("ws_manager.connected")
            metrics.inc("ws_connections_total", source="finnhub")

            # Subscribe ai ticker configurati
            with self._lock:
                tickers_to_sub = list(self._subscribed)
            await self._subscribe_batch(tickers_to_sub, ws=ws)

            # Loop di ricezione messaggi
            while not self._stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    self._handle_message(raw)
                except asyncio.TimeoutError:
                    # Nessun messaggio in 30s — normale fuori-orario
                    continue

    async def _subscribe_batch(
        self,
        tickers: list[str],
        ws: Any = None,
    ) -> None:
        """Invia messaggi subscribe al WebSocket per ogni ticker."""
        if ws is None:
            return  # non ancora connesso; i ticker saranno subscribati alla connect
        for ticker in tickers:
            msg = json.dumps({"type": "subscribe", "symbol": ticker})
            await ws.send(msg)
            log.debug("ws_manager.subscribed", ticker=ticker)

    def _handle_message(self, raw: str) -> None:
        """Parsa un messaggio WebSocket e aggiorna il dict prezzi.

        Formato trade: {"data":[{"s":"AAPL","p":150.0,"t":1714000000,"v":100}],"type":"trade"}
        """
        try:
            msg: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            log.debug("ws_manager.invalid_json")
            return

        if msg.get("type") != "trade":
            return

        trades: list[dict[str, Any]] = msg.get("data") or []
        now = time.time()

        updated: list[str] = []
        with self._lock:
            for trade in trades:
                ticker = str(trade.get("s", ""))
                price = trade.get("p")
                volume = trade.get("v", 0.0)
                ts_ms = trade.get("t", 0)

                if not ticker or price is None:
                    continue

                self._prices[ticker] = LivePrice(
                    ticker=ticker,
                    price=float(price),
                    volume=float(volume),
                    timestamp_ms=int(ts_ms),
                    received_at=now,
                )
                updated.append(ticker)

        if updated:
            metrics.inc("ws_ticks_received_total", source="finnhub", count=len(updated))


# ─── Singleton ───────────────────────────────────────────────────────────────

_ws_lock = threading.Lock()
_ws_instance: WebSocketStreamManager | None = None


def get_ws_manager(api_key: str | None = None) -> WebSocketStreamManager | None:
    """Ritorna il singleton WebSocketStreamManager, o None se flag disabilitato.

    Crea l'istanza lazily al primo call. Thread-safe.
    """
    global _ws_instance  # noqa: PLW0603
    if not is_enabled("realtime_websocket"):
        return None
    with _ws_lock:
        if _ws_instance is None:
            key = api_key or os.getenv("FINNHUB_API_KEY", "").strip()
            if not key:
                log.warning("ws_manager.no_api_key_skipped")
                return None
            _ws_instance = WebSocketStreamManager(api_key=key)
        return _ws_instance


def reset_ws_manager() -> None:
    """Resetta il singleton — uso esclusivo nei test."""
    global _ws_instance  # noqa: PLW0603
    with _ws_lock:
        if _ws_instance is not None:
            try:
                _ws_instance.stop()
            except Exception:  # noqa: BLE001
                pass
        _ws_instance = None
