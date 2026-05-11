"""BasisAnalyzer — Settimana 5 Roadmap Unificata.

Calcola il basis tra il futures e il suo ETF spot proxy.

Definizione:
  basis     = futures_close - spot_etf_close
  basis_pct = basis / spot_etf_close * 100

  Basis positivo (futures > spot): normale in contango (costo di carry).
  Basis negativo (futures < spot): backwardation (scarsità spot).

  Z-Score del basis: misura se il basis corrente è anomalo rispetto
  alla sua storia recente. Basis molto lontano dalla media → opportunità
  di convergenza (arbitraggio) o segnale di stress.

  Signal:
    basis_zscore > +1.5 → 'divergence' (futures troppo caro vs spot)
    basis_zscore < -1.5 → 'convergence' (futures troppo economico vs spot)
    altrimenti           → 'neutral'

ETF spot proxies (da FuturesFetcher):
  CL=F → USO  | GC=F → GLD | ES=F → SPY | ZC=F → CORN | ZW=F → WEAT

Regola 2 (SRP): solo calcolo basis — non fa roll o OI.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np

from engine.futures_analysis.schemas import BasisResult
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient
    from shared.db.prices_repo import PricesRepository

__version__ = "1.0.0"
__all__ = ["BasisAnalyzer"]

log = get_logger(__name__)

# Mapping futures → ETF spot proxy
_SPOT_PROXIES: dict[str, str] = {
    "CL=F": "USO",
    "GC=F": "GLD",
    "ES=F": "SPY",
    "ZC=F": "CORN",
    "ZW=F": "WEAT",
}

# Soglie Z-Score per segnale basis
_DIVERGENCE_THRESHOLD  =  1.5
_CONVERGENCE_THRESHOLD = -1.5

# Lookback per lo Z-Score (barre)
_ZSCORE_LOOKBACK = 60


class BasisAnalyzer:
    """Calcola il basis futures-spot e il suo Z-Score storico.

    Legge i prezzi futures da `futures_ohlcv` (DuckDB, migration 007)
    e i prezzi ETF da `prices_ohlcv` via PricesRepository.

    Usage::

        analyzer = BasisAnalyzer(duckdb=get_duckdb_client(), prices_repo=get_prices_repository())
        result = analyzer.analyze("GC=F")
    """

    def __init__(
        self,
        duckdb:      DuckDBClient,
        prices_repo: PricesRepository,
    ) -> None:
        self._db    = duckdb
        self._repo  = prices_repo

    def analyze(self, ticker: str) -> BasisResult:
        """Calcola il basis per un ticker futures.

        Args:
            ticker: Simbolo futures (es. 'GC=F').

        Returns:
            BasisResult con basis, basis_pct, zscore e signal.
        """
        spot_ticker = _SPOT_PROXIES.get(ticker)
        if spot_ticker is None:
            log.warning("basis_analyzer.no_proxy", ticker=ticker)
            return _null_result(ticker, "UNKNOWN")

        # Leggi prezzo futures corrente da futures_ohlcv
        futures_close = self._read_futures_close(ticker)
        if futures_close is None:
            log.warning("basis_analyzer.no_futures_data", ticker=ticker)
            return _null_result(ticker, spot_ticker)

        # Leggi prezzo spot ETF corrente
        from shared.types import TimeFrame
        spot_df = self._repo.read_prices(ticker=spot_ticker, timeframe=TimeFrame.D1)
        if spot_df is None or spot_df.empty:
            log.warning("basis_analyzer.no_spot_data", spot_ticker=spot_ticker)
            return _null_result(ticker, spot_ticker)

        spot_closes = spot_df["close"].dropna().to_numpy(dtype=np.float64)
        spot_close  = float(spot_closes[-1])

        if spot_close <= 0:
            return _null_result(ticker, spot_ticker)

        # Basis corrente
        basis     = float(np.float64(futures_close) - np.float64(spot_close))
        basis_pct = float(basis / spot_close * 100.0)

        # Z-Score del basis su storia recente
        basis_zscore = self._compute_basis_zscore(ticker, spot_ticker, basis)

        # Signal
        if basis_zscore is not None and basis_zscore > _DIVERGENCE_THRESHOLD:
            signal = "divergence"
        elif basis_zscore is not None and basis_zscore < _CONVERGENCE_THRESHOLD:
            signal = "convergence"
        else:
            signal = "neutral"

        log.info(
            "basis_analyzer.done",
            ticker=ticker,
            spot_ticker=spot_ticker,
            basis=round(basis, 3),
            basis_pct=round(basis_pct, 3),
            zscore=round(basis_zscore, 3) if basis_zscore else None,
            signal=signal,
        )

        return BasisResult(
            ticker=ticker,
            spot_ticker=spot_ticker,
            computed_at=datetime.now(UTC),
            basis=basis,
            basis_pct=basis_pct,
            basis_zscore=basis_zscore,
            signal=signal,
        )

    def analyze_from_prices(
        self,
        ticker:         str,
        futures_closes: np.ndarray,
        spot_closes:    np.ndarray,
        spot_ticker:    str = "ETF",
    ) -> BasisResult:
        """Calcola il basis da array numpy (per test senza DB).

        Args:
            ticker:         Simbolo futures.
            futures_closes: Array prezzi futures (ordinato cronologico).
            spot_closes:    Array prezzi spot ETF (stessa lunghezza).
            spot_ticker:    Nome ETF proxy per logging.

        Returns:
            BasisResult.
        """
        if len(futures_closes) == 0 or len(spot_closes) == 0:
            return _null_result(ticker, spot_ticker)

        futures_close = float(futures_closes[-1])
        spot_close    = float(spot_closes[-1])

        if spot_close <= 0:
            return _null_result(ticker, spot_ticker)

        basis     = float(np.float64(futures_close) - np.float64(spot_close))
        basis_pct = float(basis / spot_close * 100.0)

        # Serie storica basis
        min_len = min(len(futures_closes), len(spot_closes))
        hist_f  = futures_closes[-min_len:]
        hist_s  = spot_closes[-min_len:]
        valid   = hist_s > 0
        hist_basis = hist_f[valid] - hist_s[valid]

        basis_zscore: float | None = None
        if len(hist_basis) >= 10:
            mu  = float(np.mean(hist_basis))
            std = float(np.std(hist_basis, ddof=1))
            basis_zscore = float((basis - mu) / std) if std > 0 else 0.0

        if basis_zscore is not None and basis_zscore > _DIVERGENCE_THRESHOLD:
            signal = "divergence"
        elif basis_zscore is not None and basis_zscore < _CONVERGENCE_THRESHOLD:
            signal = "convergence"
        else:
            signal = "neutral"

        return BasisResult(
            ticker=ticker,
            spot_ticker=spot_ticker,
            computed_at=datetime.now(UTC),
            basis=basis,
            basis_pct=basis_pct,
            basis_zscore=basis_zscore,
            signal=signal,
        )

    # ─── Helpers ─────────────────────────────────────────────────────────

    def _read_futures_close(self, ticker: str) -> float | None:
        """Legge l'ultimo prezzo close da futures_ohlcv."""
        try:
            rows = self._db.query(
                "SELECT close FROM futures_ohlcv "
                "WHERE ticker = ? AND contract_month = 'front' "
                "ORDER BY ts DESC LIMIT 1",
                [ticker],
            )
            if not rows or rows[0][0] is None:
                return None
            return float(rows[0][0])
        except Exception as exc:
            log.warning("basis_analyzer.futures_read_failed", ticker=ticker, error=str(exc)[:80])
            return None

    def _compute_basis_zscore(
        self, ticker: str, spot_ticker: str, current_basis: float
    ) -> float | None:
        """Calcola Z-Score del basis su _ZSCORE_LOOKBACK barre storiche."""
        try:
            rows = self._db.query(
                "SELECT basis FROM futures_ohlcv "
                "WHERE ticker = ? AND contract_month = 'front' "
                "AND basis IS NOT NULL "
                "ORDER BY ts DESC LIMIT ?",
                [ticker, _ZSCORE_LOOKBACK],
            )
            if not rows or len(rows) < 10:
                return None
            historical = np.array([float(r[0]) for r in rows], dtype=np.float64)
            mu  = float(np.mean(historical))
            std = float(np.std(historical, ddof=1))
            return float((current_basis - mu) / std) if std > 0 else 0.0
        except Exception:
            return None


def _null_result(ticker: str, spot_ticker: str) -> BasisResult:
    return BasisResult(
        ticker=ticker,
        spot_ticker=spot_ticker,
        computed_at=datetime.now(UTC),
        basis=None,
        basis_pct=None,
        basis_zscore=None,
        signal="neutral",
    )
