"""Calcolo P/E Ratio: Trailing, Forward, Shiller CAPE, ERP.

Fonti dati:
  - Trailing PE: fundamentals_valuation.pe_ttm (Alpha Vantage)
  - Forward PE:  fundamentals_valuation.pe_forward (Alpha Vantage)
  - CAPE:        shiller_cape_historical (Shiller Yale / FRED)
  - ERP:         1/ForwardPE - DGS10 (FRED)
  - Price:       yfinance (via LiveMarketService o fetch singolo)

Regola 8: numpy per calcoli.
Regola 12: legge da DuckDB, non fa fetch inline.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np

from engine.analytics.valuation.schemas import PEMetrics

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
log = logging.getLogger(__name__)

# Regimi ERP (Equity Risk Premium) basati su dati storici S&P 500 1990-2025
_ERP_ATTRACTIVE  =  0.03   # > 3%  → azioni attraenti vs bond
_ERP_FAIR_MAX    =  0.03   # 1-3%  → fair value
_ERP_FAIR_MIN    =  0.01
_ERP_EXPENSIVE   =  0.00   # 0-1%  → costoso
# ERP < 0% → extreme (azioni storicamente molto costose)


def _erp_regime(erp: float | None) -> str | None:
    """Classifica l'ERP in regime qualitativo."""
    if erp is None:
        return None
    if erp > _ERP_ATTRACTIVE:
        return "attractive"
    if erp > _ERP_FAIR_MIN:
        return "fair"
    if erp > _ERP_EXPENSIVE:
        return "expensive"
    return "extreme"


class PECalculator:
    """Calcola Trailing PE, Forward PE, Shiller CAPE, ERP per un ticker.

    Args:
        client: DuckDBClient con tabelle fundamentals_valuation,
                fundamentals_edgar, shiller_cape_historical.

    Usage::

        calc = PECalculator(client=get_duckdb_client())
        metrics = calc.compute("^GSPC")
        print(metrics.trailing_pe, metrics.shiller_cape)
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client

    def compute(self, ticker: str, as_of: date | None = None) -> PEMetrics:
        """Calcola tutte le metriche PE per il ticker alla data specificata.

        Args:
            ticker: Ticker Yahoo Finance (es. '^GSPC', 'SPY', 'AAPL').
            as_of:  Data di riferimento (default: oggi).

        Returns:
            PEMetrics con tutti i valori calcolati (None se dato mancante).
        """
        as_of = as_of or date.today()

        price          = self._get_price(ticker, as_of)
        trailing_pe    = self._get_trailing_pe(ticker, as_of, price)
        forward_pe     = self._get_forward_pe(ticker, as_of, price)
        cape           = self._get_shiller_cape(as_of)
        eps_trailing   = self._get_eps_trailing(ticker, as_of)
        eps_forward    = self._get_eps_forward(ticker, as_of)
        risk_free      = self._get_risk_free_rate(as_of)

        # PEG ratio: Forward PE / EPS growth 5Y (approssimato con YoY se N/D)
        peg = self._compute_peg(forward_pe, ticker, as_of)

        # ERP = Earnings Yield (1/ForwardPE) - Risk-Free Rate
        erp = None
        if forward_pe and forward_pe > 0 and risk_free is not None:
            erp = (1.0 / forward_pe) - risk_free

        return PEMetrics(
            metric_date=as_of,
            ticker=ticker,
            price=price or 0.0,
            trailing_pe=trailing_pe,
            forward_pe=forward_pe,
            shiller_cape=cape,
            peg_ratio=peg,
            erp_implied=erp,
            erp_regime=_erp_regime(erp),
            eps_trailing_4q=eps_trailing,
            eps_forward_1y=eps_forward,
            risk_free_rate=risk_free,
        )

    def persist(self, metrics: PEMetrics, zscore_trailing: float | None = None,
                zscore_forward: float | None = None, zscore_cape: float | None = None,
                pct_trailing: float | None = None, pct_forward: float | None = None,
                pct_cape: float | None = None) -> None:
        """Salva le metriche PE in pe_metrics."""
        try:
            self._client.execute(
                """
                INSERT INTO pe_metrics
                    (metric_date, ticker, price, trailing_pe, forward_pe, shiller_cape,
                     peg_ratio, erp_implied, erp_regime, trailing_pe_zscore,
                     forward_pe_zscore, cape_zscore, trailing_pe_pct, forward_pe_pct,
                     cape_pct, eps_trailing_4q, eps_forward_1y, risk_free_rate)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT (metric_date, ticker) DO UPDATE SET
                    price=excluded.price, trailing_pe=excluded.trailing_pe,
                    forward_pe=excluded.forward_pe, shiller_cape=excluded.shiller_cape,
                    erp_implied=excluded.erp_implied, erp_regime=excluded.erp_regime,
                    trailing_pe_zscore=excluded.trailing_pe_zscore,
                    forward_pe_zscore=excluded.forward_pe_zscore,
                    cape_zscore=excluded.cape_zscore, fetched_at=NOW()
                """,
                [metrics.metric_date, metrics.ticker, metrics.price,
                 metrics.trailing_pe, metrics.forward_pe, metrics.shiller_cape,
                 metrics.peg_ratio, metrics.erp_implied, metrics.erp_regime,
                 zscore_trailing, zscore_forward, zscore_cape,
                 pct_trailing, pct_forward, pct_cape,
                 metrics.eps_trailing_4q, metrics.eps_forward_1y, metrics.risk_free_rate],
            )
        except Exception as exc:
            log.warning("pe_calculator.persist_failed ticker=%s: %s", metrics.ticker, str(exc)[:120])

    # ─── Lettura dati da DuckDB ──────────────────────────────────────────────

    def _get_price(self, ticker: str, as_of: date) -> float | None:
        """Prezzo da fundamentals_valuation (più recente <= as_of)."""
        try:
            rows = self._client.query(
                "SELECT price FROM pe_metrics WHERE ticker=? AND metric_date<=? "
                "ORDER BY metric_date DESC LIMIT 1", [ticker, as_of]
            )
            if rows and rows[0][0]:
                return float(rows[0][0])
        except Exception:
            pass
        # Fallback: cerca in vix_strategy_outputs per il price
        try:
            import yfinance as yf
            t = yf.Ticker(ticker)
            fi = t.fast_info
            p = getattr(fi, "last_price", None)
            return float(p) if p else None
        except Exception:
            return None

    def _get_trailing_pe(self, ticker: str, as_of: date, price: float | None) -> float | None:
        """Trailing PE da fundamentals_valuation (Alpha Vantage) o calcolato."""
        try:
            rows = self._client.query(
                "SELECT pe_ttm FROM fundamentals_valuation "
                "WHERE ticker=? AND computed_at::DATE <= ? "
                "ORDER BY computed_at DESC LIMIT 1", [ticker, as_of]
            )
            if rows and rows[0][0]:
                return float(rows[0][0])
        except Exception:
            pass

        # Calcola da EPS trailing
        eps = self._get_eps_trailing(ticker, as_of)
        if eps and eps > 0 and price and price > 0:
            return price / eps
        return None

    def _get_forward_pe(self, ticker: str, as_of: date, price: float | None) -> float | None:
        """Forward PE da fundamentals_valuation."""
        try:
            rows = self._client.query(
                "SELECT pe_forward FROM fundamentals_valuation "
                "WHERE ticker=? AND computed_at::DATE <= ? "
                "ORDER BY computed_at DESC LIMIT 1", [ticker, as_of]
            )
            if rows and rows[0][0]:
                return float(rows[0][0])
        except Exception:
            pass

        eps_fwd = self._get_eps_forward(ticker, as_of)
        if eps_fwd and eps_fwd > 0 and price and price > 0:
            return price / eps_fwd
        return None

    def _get_shiller_cape(self, as_of: date) -> float | None:
        """CAPE più recente da shiller_cape_historical."""
        try:
            rows = self._client.query(
                "SELECT cape_ratio FROM shiller_cape_historical "
                "WHERE data_date <= ? AND cape_ratio IS NOT NULL "
                "ORDER BY data_date DESC LIMIT 1", [as_of]
            )
            return float(rows[0][0]) if rows and rows[0][0] else None
        except Exception:
            return None

    def _get_eps_trailing(self, ticker: str, as_of: date) -> float | None:
        """EPS trailing 4Q da fundamentals_edgar (somma ultimi 4 quarter)."""
        try:
            cutoff = as_of - timedelta(days=400)
            rows = self._client.query(
                "SELECT eps_diluted FROM fundamentals_edgar "
                "WHERE ticker=? AND report_date::DATE BETWEEN ? AND ? "
                "AND period IN ('Q1','Q2','Q3','Q4') "
                "ORDER BY report_date DESC LIMIT 4",
                [ticker, cutoff, as_of],
            )
            if len(rows) >= 2:
                vals = [float(r[0]) for r in rows if r[0] is not None]
                return sum(vals) if vals else None
        except Exception:
            pass
        return None

    def _get_eps_forward(self, ticker: str, as_of: date) -> float | None:
        """EPS forward da fundamentals_valuation (Alpha Vantage stima)."""
        try:
            # Deriviamo da pe_forward e price se disponibile
            rows = self._client.query(
                "SELECT pe_forward FROM fundamentals_valuation "
                "WHERE ticker=? AND computed_at::DATE <= ? "
                "ORDER BY computed_at DESC LIMIT 1", [ticker, as_of]
            )
            if rows and rows[0][0]:
                price = self._get_price(ticker, as_of)
                if price and price > 0:
                    return price / float(rows[0][0])
        except Exception:
            pass
        return None

    def _get_risk_free_rate(self, as_of: date) -> float | None:
        """DGS10 (US 10Y yield) da macro_data o shiller_cape_historical."""
        try:
            rows = self._client.query(
                "SELECT value FROM macro_data "
                "WHERE series_id='DGS10' AND series_date <= ? "
                "ORDER BY series_date DESC LIMIT 1", [as_of]
            )
            if rows and rows[0][0]:
                return float(rows[0][0]) / 100.0
        except Exception:
            pass
        try:
            rows = self._client.query(
                "SELECT bond_yield FROM shiller_cape_historical "
                "WHERE data_date <= ? AND bond_yield IS NOT NULL "
                "ORDER BY data_date DESC LIMIT 1", [as_of]
            )
            if rows and rows[0][0]:
                return float(rows[0][0]) / 100.0
        except Exception:
            pass
        return None

    def _compute_peg(self, forward_pe: float | None, ticker: str, as_of: date) -> float | None:
        """PEG = Forward PE / EPS growth rate (approssimato)."""
        if forward_pe is None or forward_pe <= 0:
            return None
        try:
            rows = self._client.query(
                "SELECT eps_diluted FROM fundamentals_edgar "
                "WHERE ticker=? AND period='FY' "
                "ORDER BY report_date DESC LIMIT 2", [ticker, ]
            )
            if len(rows) == 2 and rows[0][0] and rows[1][0]:
                eps_new = float(rows[0][0])
                eps_old = float(rows[1][0])
                if eps_old > 0:
                    growth_rate = (eps_new / eps_old - 1.0) * 100
                    if growth_rate > 0:
                        return forward_pe / growth_rate
        except Exception:
            pass
        return None
