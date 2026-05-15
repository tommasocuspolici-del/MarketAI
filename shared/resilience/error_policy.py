"""Policy standardizzata per la gestione degli errori nei moduli MarketAI.

Tre livelli:
  RECOVER  → errore recuperabile: log warning, usa fallback, continua
  DEGRADE  → errore che degrada il servizio: log error, il componente
              restituisce None/vuoto ma l'app non crasha
  FATAL    → errore non recuperabile: log critical, rilancia l'eccezione

Uso::

    from shared.resilience.error_policy import apply_error_policy, error_policy

    @apply_error_policy(level="RECOVER", fallback=0.0, context="fetch_fx_rate")
    def _fetch_fx_rate(pair: str) -> float:
        ...

    # Oppure nel blocco except:
    except Exception as exc:
        return error_policy.degrade(exc, context="live_market_service._extract_kpi")
"""
from __future__ import annotations

import functools
import logging
from enum import Enum
from typing import Any, Callable, TypeVar

log = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])


class ErrorLevel(str, Enum):
    RECOVER = "RECOVER"   # Usa fallback, log WARNING
    DEGRADE = "DEGRADE"   # Restituisce None, log ERROR
    FATAL   = "FATAL"     # Rilancia, log CRITICAL


class ErrorPolicy:
    """Applica la policy di error handling con logging strutturato uniforme."""

    def handle(
        self,
        exc: Exception,
        *,
        level: ErrorLevel,
        context: str,
        fallback: Any = None,
    ) -> Any:
        """Gestisce un'eccezione secondo la policy specificata.

        Args:
            exc: L'eccezione catturata.
            level: Il livello di severity (RECOVER, DEGRADE, FATAL).
            context: Stringa descrittiva del punto di fallimento (es. "modulo.funzione").
            fallback: Valore da restituire in caso di RECOVER o DEGRADE.

        Returns:
            fallback se level è RECOVER o DEGRADE.

        Raises:
            exc: L'eccezione originale se level è FATAL.
        """
        msg = f"[{level.value}] {context}: {type(exc).__name__}: {exc}"
        if level == ErrorLevel.RECOVER:
            log.warning(msg, exc_info=False)
            return fallback
        if level == ErrorLevel.DEGRADE:
            log.error(msg, exc_info=True)
            return fallback
        # FATAL
        log.critical(msg, exc_info=True)
        raise exc


error_policy = ErrorPolicy()


def apply_error_policy(
    level: str = "DEGRADE",
    fallback: Any = None,
    context: str = "",
) -> Callable[[F], F]:
    """Decorator che applica ErrorPolicy a una funzione.

    Args:
        level: "RECOVER", "DEGRADE" o "FATAL".
        fallback: Valore restituito in caso di errore (solo RECOVER/DEGRADE).
        context: Stringa descrittiva. Se vuota, usa module.qualname della funzione.

    Example::

        @apply_error_policy(level="RECOVER", fallback=None)
        def _get_live_price_usd(ticker: str) -> float | None:
            ...
    """
    _level = ErrorLevel(level.upper())

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            _ctx = context or f"{fn.__module__}.{fn.__qualname__}"
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                return error_policy.handle(exc, level=_level, context=_ctx, fallback=fallback)
        return wrapper  # type: ignore[return-value]

    return decorator
