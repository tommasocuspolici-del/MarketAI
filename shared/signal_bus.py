"""SignalBus — lean async pub/sub in-process (v10, Blocco B).

LEAN MODE: only subscribe/publish/unsubscribe.
Persistence to DuckDB: enabled only if feature_flag "signal_persistence_duckdb".
Signal DAG: enabled only if feature_flag "signal_dag_enabled".
Wildcard "*": supported for monitoring and health checks.

All handlers run as asyncio Tasks. A handler failure is logged and swallowed
so it never blocks other handlers (QC requirement: reliability > completeness).
"""
from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from typing import Awaitable, Callable

from shared.logger import get_logger
from shared.signal_registry import get_signal_registry
from shared.signal_types import Signal

__version__ = "10.0.0"

__all__ = [
    "SignalBus",
    "get_signal_bus",
]

log = get_logger(__name__)

Handler = Callable[[Signal], Awaitable[None] | None]

_WILDCARD = "*"


class SignalBus:
    """Lean pub/sub signal bus.

    publish() is synchronous but internally schedules async handlers via the
    running event loop (if any) or calls them directly in sync fallback mode.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._lock = threading.RLock()
        self._registry = get_signal_registry()

    # ── Subscription ───────────────────────────────────────────────────────

    def subscribe(self, signal_name: str, handler: Handler) -> None:
        """Register *handler* to be called whenever *signal_name* is published.

        Use signal_name="*" to receive every signal (monitoring / health).
        """
        with self._lock:
            self._handlers[signal_name].append(handler)
        log.debug("signal_bus.subscribed", name=signal_name)

    def unsubscribe(self, signal_name: str, handler: Handler) -> None:
        """Remove *handler* from *signal_name* subscribers."""
        with self._lock:
            handlers = self._handlers.get(signal_name, [])
            try:
                handlers.remove(handler)
            except ValueError:
                pass

    # ── Publishing ─────────────────────────────────────────────────────────

    def publish(self, signal: Signal) -> None:
        """Publish *signal* synchronously.

        1. Stores in SignalRegistry (always, < 1 ms).
        2. Dispatches to exact-name subscribers.
        3. Dispatches to wildcard "*" subscribers.

        Handlers that raise are caught, logged, and skipped.
        """
        self._registry.publish(signal)

        with self._lock:
            exact    = list(self._handlers.get(signal.name, []))
            wildcard = list(self._handlers.get(_WILDCARD, []))
        targets = exact + wildcard

        if not targets:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            for handler in targets:
                loop.create_task(self._safe_dispatch(handler, signal))
        else:
            for handler in targets:
                try:
                    result = handler(signal)
                    if asyncio.iscoroutine(result):
                        asyncio.run(result)
                except Exception as exc:
                    log.error(
                        "signal_bus.handler_error",
                        handler=getattr(handler, "__name__", repr(handler)),
                        signal=signal.name,
                        error=str(exc),
                    )

    async def publish_async(self, signal: Signal) -> None:
        """Async variant of publish — awaits all handlers."""
        self._registry.publish(signal)

        with self._lock:
            exact    = list(self._handlers.get(signal.name, []))
            wildcard = list(self._handlers.get(_WILDCARD, []))
        targets = exact + wildcard

        tasks = [asyncio.create_task(self._safe_dispatch(h, signal)) for h in targets]
        if tasks:
            await asyncio.gather(*tasks)

    # ── Internal ───────────────────────────────────────────────────────────

    @staticmethod
    async def _safe_dispatch(handler: Handler, signal: Signal) -> None:
        try:
            result = handler(signal)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            log.error(
                "signal_bus.handler_error",
                handler=getattr(handler, "__name__", repr(handler)),
                signal=signal.name,
                error=str(exc),
            )

    def subscriber_count(self, signal_name: str) -> int:
        with self._lock:
            return len(self._handlers.get(signal_name, []))

    def all_subscriptions(self) -> dict[str, int]:
        with self._lock:
            return {k: len(v) for k, v in self._handlers.items() if v}


# ── Module-level singleton ─────────────────────────────────────────────────

_bus: SignalBus | None = None
_bus_lock = threading.Lock()


def get_signal_bus() -> SignalBus:
    """Return the process-wide SignalBus singleton."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = SignalBus()
    return _bus
