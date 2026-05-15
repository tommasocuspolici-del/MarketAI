"""EquityRiskPremium — calcolo e tracking dell'Equity Risk Premium.

ERP = Earnings Yield (1 / Forward PE) - Risk-Free Rate (DGS10)

Fonte risk-free rate (in ordine di priorità):
  1. yield_curve_snapshots.y_10y (fonte primaria per il progetto)
  2. macro_series WHERE series_id='DGS10'
  3. shiller_cape_historical.bond_yield (serie storica lunga)

Interpretazione ERP (calibrata su dati S&P 500 1990-2025):
  > 3%:  'attractive'  — azioni convenienti rispetto ai bond
  1-3%:  'fair'        — valutazione relativa equa
  0-1%:  'expensive'   — azioni costose relativamente ai bond
  < 0%:  'extreme'     — azioni storicamente molto costose

Regola 8: numpy per calcoli.
Regola 12: legge da DuckDB — nessun fetch inline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Literal

import numpy as np

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["EquityRiskPremium", "ERPResult", "ERPRegime"]

log = logging.getLogger(__name__)

ERPRegime = Literal["attractive", "fair", "expensive", "extreme"]

# Soglie ERP (dati storici S&P 500 1990-2025)
_ERP_ATTRACTIVE = 0.03   # > 3%
_ERP_FAIR_MIN   = 0.01   # 1-3%
_ERP_EXPENSIVE  = 0.00   # 0-1%
# < 0% → extreme

# Media/deviazione storica ERP S&P 500 per fallback z-score
_ERP_HIST_MEAN = 0.025
_ERP_HIST_STD  = 0.018


@dataclass(frozen=True)
class ERPResult:
    """Risultato del calcolo ERP per un ticker in una data specifica.

    Attributes:
        calc_date:      Data del calcolo.
        ticker:         Ticker di riferimento.
        erp_value:      ERP = Earnings Yield - Risk-Free Rate.
        earnings_yield: 1 / Forward PE (proxy rendimento azionario).
        risk_free_rate: DGS10 usato per il calcolo.
        forward_pe:     Forward PE di input.
        regime:         Classificazione qualitativa ERP.
        zscore:         Z-score rispetto alla serie storica (None se < 12 pts).
        percentile:     Percentile storico [0, 100] (None se < 12 pts).
    """
    calc_date:      date
    ticker:         str
    erp_value:      float | None
    earnings_yield: float | None
    risk_free_rate: float | None
    forward_pe:     float | None
    regime:         ERPRegime | None
    zscore:         float | None
    percentile:     float | None


class EquityRiskPremium:
    """Calcola e contestualizza l'Equity Risk Premium.

    Usage::

        erp = EquityRiskPremium(client=get_duckdb_client())
        result = erp.compute("^GSPC")
        print(result.erp_value, result.regime)
    """

    def __init__(self, client: DuckDBClient, lookback_years: int = 20) -> None:
        self._client = client
        self._lookback = lookback_years

    # ─── Public API ──────────────────────────────────────────────────────────

    def compute(self, ticker: str = "^GSPC", as_of: date | None = None) -> ERPResult:
        """Calcola ERP per il ticker alla data indicata.

        Legge forward_pe da pe_metrics o fundamentals_valuation.
        Legge risk_free da yield_curve_snapshots o macro_series.

        Args:
            ticker: Ticker (default '^GSPC').
            as_of:  Data di riferimento (default: oggi).

        Returns:
            ERPResult con valore, regime e z-score storico.
        """
        as_of = as_of or date.today()

        forward_pe     = self._get_forward_pe(ticker, as_of)
        risk_free_rate = self._get_risk_free_rate(as_of)

        erp, ey = self._calculate_erp(forward_pe, risk_free_rate)
        regime  = _classify_regime(erp)

        zscore, percentile = self._historical_context(ticker, as_of, erp)

        return ERPResult(
            calc_date=as_of,
            ticker=ticker,
            erp_value=erp,
            earnings_yield=ey,
            risk_free_rate=risk_free_rate,
            forward_pe=forward_pe,
            regime=regime,
            zscore=zscore,
            percentile=percentile,
        )

    def compute_batch(
        self,
        tickers: list[str],
        as_of: date | None = None,
    ) -> list[ERPResult]:
        """Calcola ERP per una lista di ticker.

        Args:
            tickers: Lista di ticker.
            as_of:   Data comune (default: oggi).

        Returns:
            Lista di ERPResult, uno per ticker.
        """
        as_of = as_of or date.today()
        return [self.compute(t, as_of) for t in tickers]

    def get_historical_erp(
        self,
        ticker: str = "^GSPC",
        lookback_years: int | None = None,
    ) -> list[ERPResult]:
        """Restituisce la serie storica ERP da pe_metrics.

        Args:
            ticker:         Ticker di riferimento.
            lookback_years: Anni di storia (default: self._lookback).

        Returns:
            Lista di ERPResult ordinati per data crescente.
        """
        years = lookback_years or self._lookback
        cutoff = date.today() - timedelta(days=years * 365)
        try:
            rows = self._client.query(
                """
                SELECT metric_date, forward_pe, erp_implied, risk_free_rate
                FROM pe_metrics
                WHERE ticker = ? AND metric_date >= ?
                  AND forward_pe IS NOT NULL
                ORDER BY metric_date ASC
                """,
                [ticker, cutoff],
            )
        except Exception as exc:
            log.debug("erp.hist_read_failed ticker=%s: %s", ticker, str(exc)[:80])
            return []

        results: list[ERPResult] = []
        for r in rows:
            d      = r[0] if isinstance(r[0], date) else date.fromisoformat(str(r[0]))
            fpe    = float(r[1]) if r[1] is not None else None
            erp_db = float(r[2]) if r[2] is not None else None
            rf     = float(r[3]) if r[3] is not None else None

            # Usa ERP già calcolato se disponibile, altrimenti ricalcola
            if erp_db is None:
                erp_db, _ = self._calculate_erp(fpe, rf)

            results.append(ERPResult(
                calc_date=d,
                ticker=ticker,
                erp_value=erp_db,
                earnings_yield=(1.0 / fpe) if fpe and fpe > 0 else None,
                risk_free_rate=rf,
                forward_pe=fpe,
                regime=_classify_regime(erp_db),
                zscore=None,
                percentile=None,
            ))

        return results

    # ─── Internal helpers ────────────────────────────────────────────────────

    def _get_forward_pe(self, ticker: str, as_of: date) -> float | None:
        """Legge forward PE da pe_metrics → fundamentals_valuation."""
        # 1. pe_metrics (già calcolato dal PECalculator)
        try:
            rows = self._client.query(
                "SELECT forward_pe FROM pe_metrics "
                "WHERE ticker = ? AND metric_date <= ? AND forward_pe IS NOT NULL "
                "ORDER BY metric_date DESC LIMIT 1",
                [ticker, as_of],
            )
            if rows and rows[0][0]:
                return float(rows[0][0])
        except Exception:
            pass

        # 2. fundamentals_valuation (Alpha Vantage)
        try:
            rows = self._client.query(
                "SELECT pe_forward FROM fundamentals_valuation "
                "WHERE ticker = ? AND computed_at::DATE <= ? AND pe_forward IS NOT NULL "
                "ORDER BY computed_at DESC LIMIT 1",
                [ticker, as_of],
            )
            if rows and rows[0][0]:
                return float(rows[0][0])
        except Exception:
            pass

        return None

    def _get_risk_free_rate(self, as_of: date) -> float | None:
        """Legge DGS10 da yield_curve_snapshots → macro_series → shiller."""
        # 1. yield_curve_snapshots.y_10y (fonte primaria del progetto)
        try:
            rows = self._client.query(
                "SELECT y_10y FROM yield_curve_snapshots "
                "WHERE snapshot_date <= ? AND y_10y IS NOT NULL "
                "ORDER BY snapshot_date DESC LIMIT 1",
                [as_of],
            )
            if rows and rows[0][0]:
                return float(rows[0][0]) / 100.0
        except Exception:
            pass

        # 2. macro_series DGS10
        try:
            rows = self._client.query(
                "SELECT value FROM macro_series "
                "WHERE series_id = 'DGS10' AND ts::DATE <= ? AND value IS NOT NULL "
                "ORDER BY ts DESC LIMIT 1",
                [as_of],
            )
            if rows and rows[0][0]:
                return float(rows[0][0]) / 100.0
        except Exception:
            pass

        # 3. shiller_cape_historical.bond_yield (serie storica lunga)
        try:
            rows = self._client.query(
                "SELECT bond_yield FROM shiller_cape_historical "
                "WHERE data_date <= ? AND bond_yield IS NOT NULL "
                "ORDER BY data_date DESC LIMIT 1",
                [as_of],
            )
            if rows and rows[0][0]:
                return float(rows[0][0]) / 100.0
        except Exception:
            pass

        return None

    @staticmethod
    def _calculate_erp(
        forward_pe: float | None,
        risk_free: float | None,
    ) -> tuple[float | None, float | None]:
        """ERP = Earnings Yield (1/ForwardPE) - Risk-Free Rate."""
        if forward_pe is None or forward_pe <= 0:
            return None, None
        earnings_yield = 1.0 / float(forward_pe)
        if risk_free is None:
            return None, earnings_yield
        erp = earnings_yield - risk_free
        return float(erp), float(earnings_yield)

    def _historical_context(
        self,
        ticker: str,
        as_of: date,
        erp: float | None,
    ) -> tuple[float | None, float | None]:
        """Z-score e percentile ERP rispetto alla serie storica."""
        if erp is None:
            return None, None

        cutoff = as_of - timedelta(days=self._lookback * 365)
        try:
            rows = self._client.query(
                "SELECT erp_implied FROM pe_metrics "
                "WHERE ticker = ? AND metric_date >= ? AND erp_implied IS NOT NULL "
                "ORDER BY metric_date",
                [ticker, cutoff],
            )
            if len(rows) >= 12:
                hist = np.array([float(r[0]) for r in rows], dtype=np.float64)
                mean = float(np.mean(hist))
                std  = float(np.std(hist, ddof=1))
                if std < 1e-6:
                    std = _ERP_HIST_STD
                z = float(np.clip((erp - mean) / std, -5, 5))
                from scipy import stats
                p = float(stats.percentileofscore(hist, erp))
                return z, float(np.clip(p, 0, 100))
        except Exception:
            pass

        # Fallback z-score con parametri storici
        z = float(np.clip((erp - _ERP_HIST_MEAN) / _ERP_HIST_STD, -5, 5))
        from scipy import stats
        p = float(stats.norm.cdf(z) * 100)
        return z, float(np.clip(p, 0, 100))


def _classify_regime(erp: float | None) -> ERPRegime | None:
    """Classifica il regime ERP in base alle soglie storiche."""
    if erp is None:
        return None
    if erp > _ERP_ATTRACTIVE:
        return "attractive"
    if erp > _ERP_FAIR_MIN:
        return "fair"
    if erp > _ERP_EXPENSIVE:
        return "expensive"
    return "extreme"
