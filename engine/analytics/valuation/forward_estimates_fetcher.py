"""ForwardEstimatesFetcher — stime EPS forward per il Valuation Engine.

Fonti (in ordine di priorità):
  1. fundamentals_valuation.pe_forward (Alpha Vantage, già popolato dallo scheduler)
  2. yfinance Ticker.info['forwardPE'] (gratuito, ritardo ~1g)
  3. YAML manuale in config/valuation.yaml → sezione forward_eps_manual

Per l'indice ^GSPC/SPY, la fonte primaria è yfinance perché Alpha Vantage
non copre gli indici.

Regola 12: pipeline invariabile — nessun fetch inline in lettura.
Regola 29: gated da feature flag 'forward_pe_estimates'.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from shared.feature_flags import is_enabled
from shared.exceptions import FeatureDisabledError

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["ForwardEstimatesFetcher", "ForwardEstimate"]

log = logging.getLogger(__name__)

_VALUATION_YAML = Path(__file__).resolve().parents[4] / "config" / "valuation.yaml"
_TABLE = "fundamentals_valuation"


@dataclass(frozen=True)
class ForwardEstimate:
    """Stima EPS forward 12M per un ticker.

    Attributes:
        ticker:        Ticker di riferimento.
        as_of:         Data del calcolo.
        forward_pe:    P/E forward (da fonte esterna o derivato).
        eps_forward:   EPS forward 12M (price / forward_pe, se price disponibile).
        source:        Fonte ('av' | 'yfinance' | 'yaml_manual' | 'none').
        is_estimated:  Sempre True — forward EPS è sempre una stima.
    """
    ticker:       str
    as_of:        date
    forward_pe:   float | None
    eps_forward:  float | None
    source:       str
    is_estimated: bool = True


class ForwardEstimatesFetcher:
    """Recupera stime forward PE/EPS per il Valuation Engine.

    Per i ticker coperti dallo scheduler Alpha Vantage, legge
    direttamente da fundamentals_valuation (già popolato).
    Per ^GSPC/SPY usa yfinance. Fallback finale: YAML manuale.

    Usage::

        fetcher = ForwardEstimatesFetcher(client=get_duckdb_client())
        est = fetcher.get_forward_estimate("^GSPC")
        print(est.forward_pe, est.source)
    """

    def __init__(self, client: DuckDBClient) -> None:
        if not is_enabled("forward_pe_estimates"):
            raise FeatureDisabledError(
                "Feature 'forward_pe_estimates' is disabled. "
                "Abilita in config/feature_flags.yaml."
            )
        self._client = client
        self._yaml_manual = self._load_yaml_manual()

    # ─── Public API ──────────────────────────────────────────────────────────

    def get_forward_estimate(self, ticker: str, as_of: date | None = None) -> ForwardEstimate:
        """Restituisce la stima forward PE/EPS più recente per il ticker.

        Cascade: Alpha Vantage DB → yfinance → YAML manuale.

        Args:
            ticker: Ticker Yahoo Finance.
            as_of:  Data di riferimento (default: oggi).

        Returns:
            ForwardEstimate (eps_forward=None se nessuna fonte disponibile).
        """
        as_of = as_of or date.today()

        # 1. Leggi da fundamentals_valuation (Alpha Vantage scheduler)
        est = self._read_from_av(ticker, as_of)
        if est.forward_pe is not None:
            return est

        # 2. yfinance fallback
        est = self._fetch_from_yfinance(ticker, as_of)
        if est.forward_pe is not None:
            return est

        # 3. YAML manuale
        return self._read_from_yaml(ticker, as_of)

    def persist_estimate(self, est: ForwardEstimate, price: float | None = None) -> bool:
        """Persiste la stima in fundamentals_valuation.

        Aggiorna solo pe_forward — non sovrascrive altri campi.

        Args:
            est:   ForwardEstimate da persistere.
            price: Prezzo corrente (opzionale, per calcolare market_cap).

        Returns:
            True se la persistenza è riuscita.
        """
        if est.forward_pe is None:
            return False
        try:
            self._client.execute(
                f"""
                INSERT INTO {_TABLE}
                    (ticker, computed_at, pe_forward, source)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (ticker, computed_at) DO UPDATE SET
                    pe_forward = excluded.pe_forward,
                    source     = excluded.source
                """,
                [est.ticker, datetime.now(UTC).isoformat(), est.forward_pe, est.source],
            )
            log.info("forward_estimates.persisted", ticker=est.ticker,
                     forward_pe=round(est.forward_pe, 2), source=est.source)
            return True
        except Exception as exc:
            log.warning("forward_estimates.persist_failed ticker=%s: %s",
                        est.ticker, str(exc)[:120])
            return False

    # ─── Internal sources ────────────────────────────────────────────────────

    def _read_from_av(self, ticker: str, as_of: date) -> ForwardEstimate:
        """Legge pe_forward da fundamentals_valuation (Alpha Vantage)."""
        try:
            rows = self._client.query(
                "SELECT pe_forward, pe_ttm FROM fundamentals_valuation "
                "WHERE ticker = ? AND computed_at::DATE <= ? "
                "ORDER BY computed_at DESC LIMIT 1",
                [ticker, as_of],
            )
            if rows and rows[0][0]:
                pe_fwd = float(rows[0][0])
                return ForwardEstimate(
                    ticker=ticker, as_of=as_of,
                    forward_pe=pe_fwd, eps_forward=None,
                    source="av",
                )
        except Exception as exc:
            log.debug("forward_estimates.av_read_failed ticker=%s: %s",
                      ticker, str(exc)[:80])
        return ForwardEstimate(ticker=ticker, as_of=as_of,
                               forward_pe=None, eps_forward=None, source="none")

    def _fetch_from_yfinance(self, ticker: str, as_of: date) -> ForwardEstimate:
        """Legge forwardPE da yfinance Ticker.info."""
        try:
            import yfinance as yf
            info: dict[str, Any] = yf.Ticker(ticker).info or {}
            fwd_pe = info.get("forwardPE")
            if fwd_pe and float(fwd_pe) > 0:
                pe = float(fwd_pe)
                # Deriva forward EPS se price disponibile
                price = info.get("currentPrice") or info.get("regularMarketPrice")
                eps_fwd = (float(price) / pe) if price and pe > 0 else None
                return ForwardEstimate(
                    ticker=ticker, as_of=as_of,
                    forward_pe=pe, eps_forward=eps_fwd,
                    source="yfinance",
                )
        except Exception as exc:
            log.debug("forward_estimates.yfinance_failed ticker=%s: %s",
                      ticker, str(exc)[:80])
        return ForwardEstimate(ticker=ticker, as_of=as_of,
                               forward_pe=None, eps_forward=None, source="none")

    def _read_from_yaml(self, ticker: str, as_of: date) -> ForwardEstimate:
        """Legge stime manuali da valuation.yaml → forward_eps_manual."""
        entry = self._yaml_manual.get(ticker)
        if entry:
            pe = entry.get("forward_pe")
            eps = entry.get("eps_forward")
            if pe:
                return ForwardEstimate(
                    ticker=ticker, as_of=as_of,
                    forward_pe=float(pe),
                    eps_forward=float(eps) if eps else None,
                    source="yaml_manual",
                )
        return ForwardEstimate(ticker=ticker, as_of=as_of,
                               forward_pe=None, eps_forward=None, source="none")

    @staticmethod
    def _load_yaml_manual() -> dict[str, Any]:
        """Carica la sezione forward_eps_manual da config/valuation.yaml."""
        try:
            with _VALUATION_YAML.open() as f:
                raw = yaml.safe_load(f) or {}
            return raw.get("forward_eps_manual", {})
        except Exception as exc:
            log.debug("forward_estimates.yaml_load_failed: %s", str(exc)[:80])
            return {}
