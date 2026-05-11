"""Structured logging setup.

Rule 6: structlog only, never print() in production.
Rule 15: Never log secrets or API keys.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING, Any, cast

import structlog

if TYPE_CHECKING:
    from structlog.types import EventDict, Processor

__version__ = "6.0.0"

__all__ = ["configure_logging", "get_logger", "redact_secrets"]


# ═══════════════════════════════════════════════════════════════════════════
# Secret redaction
# ═══════════════════════════════════════════════════════════════════════════
# Chiavi sensibili che non devono mai comparire nei log (Regola 15).
_SECRET_KEY_SUBSTRINGS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "token",
    "secret",
    "password",
    "passwd",
    "auth",
    "bearer",
    "credential",
)

_REDACTED: str = "***REDACTED***"


def redact_secrets(
    _logger: logging.Logger,
    _method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Redact any key that looks like a secret from the log event.

    Chiamato come processor structlog. Ogni chiave il cui nome contiene
    una delle sottostringhe sospette viene sostituita con ``***REDACTED***``.
    """
    for key in list(event_dict.keys()):
        key_lower = key.lower()
        if any(s in key_lower for s in _SECRET_KEY_SUBSTRINGS):
            event_dict[key] = _REDACTED
    return event_dict


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════
def configure_logging(
    level: str | None = None,
    json_format: bool | None = None,
) -> None:
    """Configure structlog + stdlib logging once at app startup.

    Args:
        level: Log level. Falls back to LOG_LEVEL env var, then "INFO".
        json_format: If True, emits JSON logs. If None, reads LOG_FORMAT env
            (``json`` = JSON, anything else = console).
    """
    resolved_level: str = (level or os.getenv("LOG_LEVEL") or "INFO").upper()
    numeric_level = getattr(logging, resolved_level, logging.INFO)

    if json_format is None:
        json_format = os.getenv("LOG_FORMAT", "json").lower() == "json"

    # Stdlib logging: output grezzo su stderr, structlog si occupa della formattazione
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=numeric_level,
    )

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        redact_secrets,  # Redaction di secret obbligatoria PRIMA del rendering
    ]

    if json_format:
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        # Console renderer colorato per sviluppo locale
        shared_processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    """Get a structured logger.

    Args:
        name: Logger name (typically ``__name__``).
        **initial_values: Key/value pairs permanently bound to this logger.

    Returns:
        A BoundLogger ready to use.
    """
    # Configurazione lazy: se non ancora configurato, configura con default
    if not structlog.is_configured():
        configure_logging()
    log = structlog.get_logger(name)
    if initial_values:
        log = log.bind(**initial_values)
    # Cast esplicito: structlog.get_logger ha tipo generico, qui garantiamo BoundLogger
    return cast("structlog.stdlib.BoundLogger", log)
