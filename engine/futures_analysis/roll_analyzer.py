"""RollAnalyzer — Settimana 5 Roadmap Unificata.

Calcola il roll yield e la term structure dei futures continui.

Definizioni:
  Roll yield = rendimento implicito derivato dalla differenza di prezzo
               tra contratti con scadenze diverse.
  Per i futures continui yfinance (un solo contratto):
    roll_yield_22d = (front_close / price_22d_ago) - 1
    Approssimazione accettabile: il prezzo 22 gg fa rappresenta il contratto
    scaduto/rollato nell'ultimo mese.

  Term structure:
    BACKWARDATION: front > second → mercato vuole la commodity ora
                   (scarsità, domanda immediata elevata, segnale bullish)
    CONTANGO:      front < second → struttura normale per commodity stoccabili
                   (costo di carry, storage cost inclusi)
    FLAT:          |roll| < 0.5% → mercato neutro

  Roll yield annualizzato:
    roll_yield_annual = roll_yield_22d * (252 / 22)
    Converte il roll mensile in un rendimento annuo comparabile a bond/equity.

Regola 2 (SRP): solo calcolo roll yield e term structure.
Regola 8: numpy per tutti i calcoli.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from engine.futures_analysis.schemas import RollYieldResult, TermStructure
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["RollAnalyzer"]

log = get_logger(__name__)

# Finestra per il calcolo del roll yield (giorni lavorativi in 1 mese)
_ROLL_WINDOW_DAYS = 22

# Soglie term structure
_BACKWARDATION_THRESHOLD = 0.005   # > +0.5% → backwardation
_CONTANGO_THRESHOLD      = -0.005  # < -0.5% → contango

# Lookback per percentile rank
_RANK_LOOKBACK = 252


class RollAnalyzer:
    """Calcola roll yield e term structure da dati futures_ohlcv in DuckDB.

    Legge direttamente dalla tabella `futures_ohlcv` (migration 007)
    che viene alimentata dal `FuturesFetcher` dello scheduler.

    Usage::

        analyzer = RollAnalyzer(duckdb=get_duckdb_client())
        result = analyzer.analyze("CL=F")
    """

    def __init__(self, duckdb: DuckDBClient) -> None:
        self._db = duckdb

    def analyze(self, ticker: str) -> RollYieldResult:
        """Calcola roll yield e term structure per un ticker futures.

        Args:
            ticker: Simbolo futures (es. 'CL=F', 'GC=F', 'ES=F').

        Returns:
            RollYieldResult con roll_yield, term_structure e signal.

        Raises:
            ValueError: Se non ci sono dati sufficienti in futures_ohlcv.
        """
        df = self._load_futures_data(ticker)

        if df is None or len(df) < _ROLL_WINDOW_DAYS + 2:
            raise ValueError(
                f"{ticker}: dati insufficienti in futures_ohlcv "
                f"(trovati {len(df) if df is not None else 0}, "
                f"richiesti {_ROLL_WINDOW_DAYS + 2})"
            )

        closes = df["close"].to_numpy(dtype=np.float64)
        front_close   = float(closes[-1])
        second_proxy  = float(closes[-(  _ROLL_WINDOW_DAYS + 1)])

        # Roll yield
        if second_proxy <= 0:
            raise ValueError(f"{ticker}: prezzo proxy negativo o zero ({second_proxy})")

        roll_22d   = float(np.float64(front_close) / np.float64(second_proxy) - 1.0)
        roll_annual = float(roll_22d * (np.float64(252) / np.float64(_ROLL_WINDOW_DAYS)))

        # Term structure
        term_structure = _classify_term_structure(roll_22d)

        # Percentile rank su _RANK_LOOKBACK barre
        roll_pct_rank = self._compute_roll_rank(ticker, roll_22d, closes)

        # Signal semantico
        if term_structure == TermStructure.BACKWARDATION:
            signal = "bullish"
        elif term_structure == TermStructure.CONTANGO:
            signal = "bearish"
        else:
            signal = "neutral"

        log.info(
            "roll_analyzer.done",
            ticker=ticker,
            front=round(front_close, 2),
            second_proxy=round(second_proxy, 2),
            roll_22d_pct=round(roll_22d * 100, 3),
            roll_annual_pct=round(roll_annual * 100, 2),
            term_structure=term_structure.value,
        )

        return RollYieldResult(
            ticker=ticker,
            computed_at=datetime.now(UTC),
            roll_yield_22d=roll_22d,
            roll_yield_annual=roll_annual,
            term_structure=term_structure,
            front_close=front_close,
            second_proxy=second_proxy,
            roll_pct_rank=roll_pct_rank,
            signal=signal,
        )

    def analyze_from_df(self, ticker: str, df: pd.DataFrame) -> RollYieldResult:
        """Calcola roll yield da un DataFrame OHLCV passato direttamente.

        Usato nei test e negli scenari senza DB attivo.

        Args:
            ticker: Simbolo futures.
            df:     DataFrame con almeno una colonna 'close' ordinata per data.

        Returns:
            RollYieldResult.
        """
        if df is None or len(df) < _ROLL_WINDOW_DAYS + 2:
            raise ValueError(f"{ticker}: DataFrame insufficiente ({len(df) if df is not None else 0} righe)")

        closes        = df["close"].to_numpy(dtype=np.float64)
        front_close   = float(closes[-1])
        second_proxy  = float(closes[-(_ROLL_WINDOW_DAYS + 1)])

        if second_proxy <= 0:
            raise ValueError(f"{ticker}: proxy negativo ({second_proxy})")

        roll_22d   = float(np.float64(front_close) / np.float64(second_proxy) - 1.0)
        roll_annual = float(roll_22d * (252.0 / _ROLL_WINDOW_DAYS))
        term_structure = _classify_term_structure(roll_22d)

        # Rank su tutti i roll yield storici calcolabili dal DataFrame
        historical_rolls = _compute_historical_rolls(closes, _ROLL_WINDOW_DAYS)
        roll_pct_rank = float(np.mean(historical_rolls <= roll_22d)) if len(historical_rolls) > 0 else None

        signal = (
            "bullish" if term_structure == TermStructure.BACKWARDATION else
            "bearish" if term_structure == TermStructure.CONTANGO else
            "neutral"
        )

        return RollYieldResult(
            ticker=ticker,
            computed_at=datetime.now(UTC),
            roll_yield_22d=roll_22d,
            roll_yield_annual=roll_annual,
            term_structure=term_structure,
            front_close=front_close,
            second_proxy=second_proxy,
            roll_pct_rank=roll_pct_rank,
            signal=signal,
        )

    # ─── Helpers privati ─────────────────────────────────────────────────

    def _load_futures_data(self, ticker: str) -> pd.DataFrame | None:
        """Legge i dati da futures_ohlcv (migration 007)."""
        try:
            rows = self._db.query(
                "SELECT ts, close FROM futures_ohlcv "
                "WHERE ticker = ? AND contract_month = 'front' "
                "ORDER BY ts ASC",
                [ticker],
            )
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["ts", "close"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            return df.dropna(subset=["close"])
        except Exception as exc:
            log.warning("roll_analyzer.load_failed", ticker=ticker, error=str(exc)[:100])
            return None

    def _compute_roll_rank(
        self, ticker: str, current_roll: float, closes: np.ndarray
    ) -> float | None:
        """Calcola il percentile rank del roll corrente sulla storia disponibile."""
        historical = _compute_historical_rolls(closes, _ROLL_WINDOW_DAYS)
        if len(historical) == 0:
            return None
        return float(np.mean(historical <= current_roll))


# ─── Funzioni pure ───────────────────────────────────────────────────────────

def _classify_term_structure(roll_22d: float) -> TermStructure:
    """Classifica la term structure in base al roll yield a 22 gg."""
    if roll_22d > _BACKWARDATION_THRESHOLD:
        return TermStructure.BACKWARDATION
    if roll_22d < _CONTANGO_THRESHOLD:
        return TermStructure.CONTANGO
    return TermStructure.FLAT


def _compute_historical_rolls(closes: np.ndarray, window: int) -> np.ndarray:
    """Calcola la serie storica di roll yields per il percentile rank."""
    if len(closes) < window + 2:
        return np.array([], dtype=np.float64)
    proxies = closes[:-(window)]
    fronts  = closes[window:]
    # Evita divisione per zero
    mask   = proxies > 0
    rolls  = np.where(mask, fronts / proxies - 1.0, np.nan)
    return rolls[~np.isnan(rolls)]
