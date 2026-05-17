"""Entity Resolver — mapping mention → ticker (top 50 watched).

Regola 33: mapping basato su dati reali dal portafoglio + watched_tickers.yaml.
"""
from __future__ import annotations

import pathlib
import re

import yaml

from shared.logger import get_logger

__version__ = "1.0.0"
__all__ = ["EntityResolver"]

log = get_logger(__name__)

_WATCHED_PATH = pathlib.Path(__file__).parent.parent.parent / "config" / "watched_tickers.yaml"

# Mapping statico entità comuni → ticker (integrato con watched_tickers.yaml)
_STATIC_MAPPING: dict[str, str] = {
    # Indici
    "s&p 500": "SPY", "s&p500": "SPY", "spx": "^GSPC",
    "nasdaq": "QQQ", "nasdaq 100": "QQQ",
    "dow jones": "DIA", "dow": "DIA",
    "russell 2000": "IWM",
    "vix": "^VIX",
    # Mega-cap USA
    "apple": "AAPL", "microsoft": "MSFT", "amazon": "AMZN",
    "alphabet": "GOOGL", "google": "GOOGL", "meta": "META",
    "nvidia": "NVDA", "tesla": "TSLA", "berkshire": "BRK-B",
    "jpmorgan": "JPM", "jp morgan": "JPM",
    "bank of america": "BAC", "goldman sachs": "GS",
    "exxon": "XOM", "chevron": "CVX",
    # ETF principali
    "spdr": "SPY", "invesco qqq": "QQQ",
    "ishares msci world": "IWDA.L",
    # Commodities
    "crude oil": "CL=F", "wti": "CL=F", "brent": "BZ=F",
    "gold": "GC=F", "silver": "SI=F",
    # Crypto
    "bitcoin": "BTC-USD", "ethereum": "ETH-USD",
    "btc": "BTC-USD", "eth": "ETH-USD",
    # Euro area
    "volkswagen": "VOW3.DE", "sap": "SAP.DE",
    "lvmh": "MC.PA", "total": "TTE.PA",
}


class EntityResolver:
    """Risolve entità testuali in ticker Yahoo Finance.

    Args:
        extra_mapping: Mapping aggiuntivo utente (es. da portafoglio personale).

    Usage::

        resolver = EntityResolver()
        tickers = resolver.extract_tickers("Apple beat earnings estimates, NVIDIA surges")
        # → ["AAPL", "NVDA"]
    """

    def __init__(self, extra_mapping: dict[str, str] | None = None) -> None:
        self._mapping = dict(_STATIC_MAPPING)
        self._mapping.update(self._load_watched())
        if extra_mapping:
            self._mapping.update({k.lower(): v for k, v in extra_mapping.items()})

    def _load_watched(self) -> dict[str, str]:
        """Carica ticker da watched_tickers.yaml e crea alias per company name."""
        result: dict[str, str] = {}
        if not _WATCHED_PATH.exists():
            return result
        try:
            with _WATCHED_PATH.open(encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            for entry in cfg.get("tickers", []):
                ticker = entry.get("ticker") or entry.get("symbol", "")
                name = (entry.get("name") or "").lower().strip()
                if ticker and name:
                    result[name] = ticker
                    # Alias senza suffisso borsa
                    short = name.split()[0] if " " in name else name
                    if short and short not in result:
                        result[short] = ticker
        except Exception as exc:
            log.debug("entity_resolver.watched_load_error", error=str(exc)[:100])
        return result

    def extract_tickers(self, text: str) -> list[str]:
        """Estrae ticker da testo libero (titolo + summary).

        Returns:
            Lista di ticker unici (ordinati per rilevanza).
        """
        if not text:
            return []

        found: set[str] = set()
        text_lower = text.lower()

        # 1. Cerca ticker diretti ($AAPL, AAPL, $BTC)
        for match in re.finditer(r"\$?([A-Z]{2,5}(?:\.[A-Z]{1,2})?)\b", text):
            candidate = match.group(1).upper()
            # Filtro anti-false-positive (parole comuni in maiuscolo)
            if candidate not in {"THE", "AND", "OR", "FOR", "NOT", "BUT", "ARE", "WAS",
                                  "CEO", "CFO", "COO", "IPO", "ETF", "GDP", "CPI", "FED",
                                  "SEC", "PMI", "ISM", "ECB", "BOE", "BOJ", "EUR", "USD"}:
                found.add(candidate)

        # 2. Cerca entità per nome
        for entity, ticker in self._mapping.items():
            if entity in text_lower:
                found.add(ticker)

        return sorted(found)

    def resolve(self, mention: str) -> str | None:
        """Risolve una singola menzione in ticker."""
        return self._mapping.get(mention.lower().strip())

    def add_mapping(self, mention: str, ticker: str) -> None:
        """Aggiunge un mapping runtime (non persistente)."""
        self._mapping[mention.lower().strip()] = ticker
