"""Conversione prezzi tra la valuta nativa del listino e USD.

Centralizza tutta la logica di conversione che mancava o era sparsa:
  - live_market_service.py: BUG ATTIVO — GBX trattato come USD (prezzi LSE
    come SWDA.L comparivano ~80x più alti in pence sterling invece di dollari)
  - etoro_importer.py v7.4.0: helpers FX già rimossi in favore di questo modulo

v8.1.0 — ROADMAP_CODE_QUALITY_v1.0, Settimana 3 (Blocco B).

Pattern d'uso::

    from engine.market_data.currency_converter import (
        CurrencyConverter,
        get_instrument_native_currency,
    )

    # Rileva valuta da suffisso ticker
    ccy = get_instrument_native_currency("SWDA.L")   # → "GBX"
    ccy = get_instrument_native_currency("EUN5.DE")  # → "EUR"
    ccy = get_instrument_native_currency("AAPL")     # → "USD"

    # Converte prezzo → USD
    conv = CurrencyConverter()
    price_usd = conv.to_usd(10_426.0, "GBX")        # → ~132.0 USD
    price_usd = conv.ticker_price_to_usd(10_426.0, "SWDA.L")  # stesso risultato

Test::

    Vedere tests/engine/test_currency_converter.py
"""
from __future__ import annotations

import logging
from typing import Final

from shared.config.operational_config import OP_CONFIG

__version__ = "1.0.0"

__all__ = ["CurrencyConverter", "get_instrument_native_currency"]

log = logging.getLogger(__name__)


# ── Mappa suffisso ticker → valuta nativa del listino ──────────────────────
# Separata dal codice per facilitare aggiornamenti futuri senza toccare la logica.
# Convenzione: il matching usa .upper() su entrambi i lati (case-insensitive).
_SUFFIX_TO_CURRENCY: Final[dict[str, str]] = {
    ".L":  "GBX",   # London Stock Exchange (pence sterling)
    ".DE": "EUR",   # Deutsche Börse / Xetra
    ".MI": "EUR",   # Borsa Italiana
    ".PA": "EUR",   # Euronext Paris
    ".AS": "EUR",   # Euronext Amsterdam
    ".BR": "EUR",   # Euronext Bruxelles
    ".LS": "EUR",   # Euronext Lisbona
    ".SW": "CHF",   # SIX Swiss Exchange
    ".TO": "CAD",   # Toronto Stock Exchange
    ".AX": "AUD",   # Australian Securities Exchange
    ".HK": "HKD",   # Hong Kong Stock Exchange
    ".T":  "JPY",   # Tokyo Stock Exchange
}


def get_instrument_native_currency(ticker: str) -> str:
    """Restituisce la valuta nativa del listino dal suffisso del ticker.

    La funzione è pure e O(suffissi): nessun I/O, sicura da chiamare
    frequentemente in hot path.

    Args:
        ticker: Ticker Yahoo Finance (es. "SWDA.L", "EUN5.DE", "AAPL", "9984.T").

    Returns:
        Codice valuta ISO ("GBX", "EUR", "CHF", "CAD", "AUD", "HKD", "JPY")
        oppure "USD" come default per ticker senza suffisso riconoscibile.

    Examples:
        >>> get_instrument_native_currency("SWDA.L")
        'GBX'
        >>> get_instrument_native_currency("EUN5.DE")
        'EUR'
        >>> get_instrument_native_currency("AAPL")
        'USD'
        >>> get_instrument_native_currency("9984.T")
        'JPY'
    """
    upper = ticker.upper()
    for suffix, currency in _SUFFIX_TO_CURRENCY.items():
        if upper.endswith(suffix.upper()):
            return currency
    return "USD"


class CurrencyConverter:
    """Converte prezzi dalla valuta nativa del listino in USD.

    Gestisce le conversioni:
      GBX (pence sterling) → USD : prezzo / 100 × GBP/USD
      EUR                  → USD : prezzo × EUR/USD
      CHF                  → USD : prezzo × CHF/USD
      CAD                  → USD : prezzo × CAD/USD
      AUD                  → USD : prezzo × AUD/USD
      HKD                  → USD : prezzo × HKD/USD
      JPY                  → USD : prezzo × JPY/USD
      USD                  → USD : invariato (no I/O)

    I tassi FX vengono recuperati da yfinance in modo lazy al primo uso
    per ogni valuta, poi cachati in sessione (dict in-process). In caso
    di errore yfinance usa i fallback da OP_CONFIG (GBP, EUR) o i valori
    storici statici per le altre valute.

    Thread-safety: la cache in-process NON è thread-safe. In produzione
    LiveMarketService crea una sola istanza di CurrencyConverter per
    processo → nessuna contesa. Se necessario, aggiungere un Lock.

    Esempi::

        conv = CurrencyConverter()
        conv.to_usd(10_426.0, "GBX")   # → ~132.0 USD
        conv.to_usd(118.88, "EUR")     # → ~128.4 USD
        conv.ticker_price_to_usd(10_426.0, "SWDA.L")  # → ~132.0 USD
    """

    # Coppie yfinance per ogni valuta base
    _YF_PAIRS: Final[dict[str, str]] = {
        "GBP": "GBPUSD=X",
        "EUR": "EURUSD=X",
        "CHF": "CHFUSD=X",
        "CAD": "CADUSD=X",
        "AUD": "AUDUSD=X",
        "HKD": "HKDUSD=X",
        "JPY": "JPYUSD=X",
    }

    # Fallback statici: usati se yfinance non raggiungibile.
    # GBP e EUR letti da OP_CONFIG (config/operational_defaults.yaml).
    # Gli altri sono aggiornati raramente — aggiornare trimestralmente.
    _FALLBACKS: Final[dict[str, float]] = {
        "GBP": OP_CONFIG.fx_fallbacks.gbp_usd,
        "EUR": OP_CONFIG.fx_fallbacks.eur_usd,
        "CHF": OP_CONFIG.fx_fallbacks.chf_usd,
        "CAD": 0.73,
        "AUD": 0.65,
        "HKD": 0.13,
        "JPY": 0.0065,
    }

    def __init__(self) -> None:
        # Cache in-session: {valuta_base: tasso_verso_USD}
        self._rate_cache: dict[str, float] = {}

    def _fetch_rate(self, base_ccy: str) -> float:
        """Recupera il tasso base_ccy/USD da yfinance, con fallback.

        Args:
            base_ccy: Codice valuta base ("GBP", "EUR", "CHF", ...).

        Returns:
            Tasso di cambio (quanti USD per 1 unità di base_ccy).
        """
        if base_ccy in self._rate_cache:
            return self._rate_cache[base_ccy]

        pair = self._YF_PAIRS.get(base_ccy)
        fallback = self._FALLBACKS.get(base_ccy, 1.0)

        if pair is None:
            # Valuta non mappata: assume parità con USD (caso raro)
            return fallback

        try:
            import yfinance as yf  # opzionale: non installa in CI senza dati

            t = yf.Ticker(pair)
            fi = t.fast_info
            price = getattr(fi, "last_price", None)
            if price is not None and float(price) > 0:
                rate = float(price)
            else:
                hist = t.history(period="1d")
                rate = float(hist["Close"].iloc[-1]) if not hist.empty else fallback
        except Exception:  # noqa: BLE001 — yfinance può lanciare qualsiasi cosa
            log.warning(
                "CurrencyConverter: yfinance non raggiungibile per %s/USD — "
                "uso fallback %.4f",
                base_ccy,
                fallback,
            )
            rate = fallback

        self._rate_cache[base_ccy] = rate
        return rate

    def to_usd(self, price: float, native_currency: str) -> float:
        """Converte price dalla valuta nativa del listino in USD.

        Args:
            price: Prezzo nella valuta nativa (es. 10426.0 per SWDA.L in GBX).
            native_currency: Codice valuta nativa ("GBX","EUR","CHF",...,"USD").

        Returns:
            Prezzo in USD come float.
        """
        if native_currency == "USD":
            # Fast path: nessun I/O necessario
            return float(price)

        if native_currency == "GBX":
            # GBX = pence sterling: dividi per 100 per avere GBP, poi converti in USD
            gbp_usd = self._fetch_rate("GBP")
            return float(price) / 100.0 * gbp_usd

        # Tutte le altre valute: recupera tasso base/USD e moltiplica
        rate = self._fetch_rate(native_currency)
        return float(price) * rate

    def ticker_price_to_usd(self, price: float, ticker: str) -> float:
        """Converte price alla valuta del ticker in USD.

        Convenience wrapper: rileva la valuta nativa dal suffisso del ticker,
        poi chiama to_usd().

        Args:
            price: Prezzo restituito da yfinance (nella valuta nativa del listino).
            ticker: Ticker Yahoo Finance (es. "SWDA.L", "EUN5.DE", "AAPL").

        Returns:
            Prezzo in USD.
        """
        native_ccy = get_instrument_native_currency(ticker)
        return self.to_usd(price, native_ccy)
