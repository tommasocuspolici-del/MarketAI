"""SilentFailureDetector: rileva HTTP 200 con dati semanticamente sbagliati (Rule 47).

Caso d'uso documentati e gestiti:
  - yfinance: ``info`` dict con tutti None -> ticker non trovato.
  - yfinance: ``history()`` ritorna DataFrame vuoto -> non solleva eccezione.
  - Alpha Vantage: JSON con chiave "Information" o "Note" -> rate limit silenzioso.
  - Finnhub: ``metric`` dict con tutti i campi null -> dato non disponibile.
  - SEC EDGAR: CIK "0000000000" -> ticker non in EDGAR.
  - Generico: stringhe "N/A", "None", "-", "null" -> da convertire a None.

Convenzione: chiamare PRIMA di DataCleaner. Diversamente, il pulizia statistica
puo' mascherare il problema mappando "N/A" a NaN e poi forward-fillando.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

__version__ = "7.1.0"

__all__ = ["SilentFailureDetector", "SilentFailureError"]


class SilentFailureError(Exception):
    """Sollevato quando viene rilevato un silent failure dell'API."""

    def __init__(self, source: str, reason: str, raw: Any = None) -> None:
        self.source = source
        self.reason = reason
        self.raw = raw
        super().__init__(f"[{source}] Silent failure: {reason}")


# Stringhe che diverse API ritornano per indicare "non disponibile"
# anche dove ci si aspetta un numero. Vanno convertite a None prima
# di qualsiasi pipeline di calcolo.
_NULL_STRING_TOKENS: frozenset[str] = frozenset(
    {"n/a", "none", "-", "", "null", "nan", "--", "na"}
)


class SilentFailureDetector:
    """Insieme di metodi statici per rilevare silent failures.

    Stateless: ogni metodo e' indipendente. La classe esiste per dare un
    namespace coerente e facilitare l'individuazione dei rilevatori per
    ciascuna sorgente.
    """

    # ──────────────────────────────────────────────── yfinance
    @staticmethod
    def check_yfinance_info(info: dict[str, Any] | None, ticker: str) -> None:
        """Verifica che il dizionario info di yfinance contenga dati reali.

        Raises:
            SilentFailureError: se il dict e' vuoto o tutti i campi prezzo
                critici sono None (ticker probabilmente invalido).
        """
        if not info:
            raise SilentFailureError(
                "yfinance",
                f"info dict vuoto o None per ticker {ticker}.",
                raw=info,
            )
        critical_fields = ["regularMarketPrice", "currentPrice", "previousClose"]
        values = [info.get(f) for f in critical_fields]
        if all(v is None for v in values):
            raise SilentFailureError(
                "yfinance",
                f"Tutti i campi prezzo sono None per {ticker}. "
                f"Probabile ticker invalido o dato non disponibile.",
                raw={k: info.get(k) for k in critical_fields},
            )

    @staticmethod
    def check_yfinance_history(history: pd.DataFrame | None, ticker: str) -> None:
        """Verifica che il DataFrame storico non sia vuoto.

        Raises:
            SilentFailureError: se il DataFrame e' None, vuoto o non valido.
        """
        if history is None or not isinstance(history, pd.DataFrame) or history.empty:
            raise SilentFailureError(
                "yfinance",
                f"history() ha restituito DataFrame vuoto per {ticker}.",
                raw=None,
            )

    @staticmethod
    def is_yfinance_frozen(history: pd.DataFrame, n_days: int = 3) -> bool:
        """Heuristic: True se le ultime n_days righe hanno close identico.

        Usato come WARN, non blocca: ci sono casi legittimi (mercato chiuso,
        circuit breaker, halt). Il chiamante decide se loggare/segnalare.
        """
        close_col = None
        for c in ("Close", "close", "adj_close", "Adj Close"):
            if c in history.columns:
                close_col = c
                break
        if close_col is None or len(history) < n_days:
            return False
        recent = history[close_col].tail(n_days).values
        return all(recent[i] == recent[0] and recent[0] > 0 for i in range(1, n_days))

    # ──────────────────────────────────────────────── alpha vantage
    @staticmethod
    def check_alpha_vantage_response(
        response: dict[str, Any], endpoint: str
    ) -> None:
        """Verifica che la risposta Alpha Vantage non sia rate-limit/errore.

        Alpha Vantage restituisce HTTP 200 con JSON ``{"Information": ...}``
        o ``{"Note": ...}`` quando il rate limit e' raggiunto.

        Raises:
            SilentFailureError: se la risposta e' un rate-limit/errore mascherato.
        """
        if "Information" in response:
            raise SilentFailureError(
                "alpha_vantage",
                f"Rate limit o messaggio AV per {endpoint}: "
                f"{response['Information'][:120]}",
                raw=response,
            )
        if "Note" in response:
            raise SilentFailureError(
                "alpha_vantage",
                f"Throttling AV per {endpoint}: {response['Note'][:120]}. "
                f"Free tier: 5 req/min, 500/day.",
                raw=response,
            )
        if "Error Message" in response:
            raise SilentFailureError(
                "alpha_vantage",
                f"Errore AV per {endpoint}: {response['Error Message'][:200]}",
                raw=response,
            )

    # ──────────────────────────────────────────────── finnhub
    @staticmethod
    def check_finnhub_metrics(
        metrics: dict[str, Any] | None, ticker: str
    ) -> None:
        """Verifica che le metriche Finnhub contengano dati reali."""
        if not metrics:
            raise SilentFailureError(
                "finnhub",
                f"metrics dict vuoto o None per {ticker}.",
                raw=metrics,
            )
        key_fields = [
            "peBasicExclExtraTTM",
            "epsBasicExclExtraTTM",
            "marketCapitalization",
            "bookValuePerShareAnnual",
        ]
        values = [metrics.get(f) for f in key_fields]
        non_null = [v for v in values if v is not None and v != 0]
        if not non_null:
            raise SilentFailureError(
                "finnhub",
                f"Tutti i fondamentali critici sono None o 0 per {ticker}. "
                f"Probabile ticker non supportato dal free tier.",
                raw={k: metrics.get(k) for k in key_fields},
            )

    @staticmethod
    def check_finnhub_pe_zero(pe: float | None, ticker: str) -> None:
        """Verifica che P/E non sia esattamente 0 (Finnhub usa 0 per N/A)."""
        if pe is not None and pe == 0:
            raise SilentFailureError(
                "finnhub",
                f"P/E = 0 per {ticker}: spesso significa 'non disponibile', "
                f"non P/E reale.",
                raw={"pe": pe, "ticker": ticker},
            )

    # ──────────────────────────────────────────────── sec edgar
    @staticmethod
    def check_sec_edgar_cik(cik: str | None, ticker: str) -> None:
        """Verifica che il CIK SEC EDGAR sia valido."""
        if not cik or cik.strip("0") == "":
            raise SilentFailureError(
                "sec_edgar",
                f"CIK non trovato o invalido per {ticker}. "
                f"Il ticker potrebbe non essere quotato negli USA.",
                raw={"cik": cik, "ticker": ticker},
            )

    # ──────────────────────────────────────────────── generico
    @staticmethod
    def sanitize_string_none(value: Any) -> float | None:
        """Converte stringhe 'N/A', 'None', '-', 'null' in None.

        Tenta anche di convertire stringhe numeriche (con virgola come
        separatore decimale tipico EU).
        """
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value) if not _is_nan(value) else None
        if isinstance(value, str):
            stripped = value.strip().lower()
            if stripped in _NULL_STRING_TOKENS:
                return None
            try:
                return float(stripped.replace(",", ".").replace(" ", ""))
            except ValueError:
                return None
        return None


def _is_nan(x: float) -> bool:
    """True se x e' NaN (lavora anche su int senza conversion errors)."""
    try:
        return x != x  # NaN-only property
    except TypeError:
        return False
