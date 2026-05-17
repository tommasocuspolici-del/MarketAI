# engine/technical/divergence_detector.py
"""
DivergenceDetector: identifica divergenze prezzo/oscillatore.

Tipi di divergenza:
  · BULLISH REGULAR (RSI): prezzo fa Lower Low, RSI fa Higher Low
    → momentum in recupero mentre prezzo scende → possibile inversione rialzista
  · BEARISH REGULAR (RSI): prezzo fa Higher High, RSI fa Lower High
    → momentum in calo mentre prezzo sale → possibile inversione ribassista
  · BULLISH REGULAR (MACD): prezzo fa Lower Low, MACD histogram fa Higher Low
  · BEARISH REGULAR (MACD): prezzo fa Higher High, MACD histogram fa Lower High

Algoritmo di rilevamento:
  1. Identifica i pivot (minimi/massimi locali) con finestra N barre
  2. Confronta coppie di pivot consecutivi su prezzo e oscillatore
  3. Se la direzione è opposta → divergenza rilevata
  4. Calcola la "strength" come differenza percentuale tra i pivot

Regola 2 (SRP): questo modulo fa solo detection — non produce trade signals.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import numpy as np
import numpy.typing as npt
import structlog

from shared.types import TimeFrame

if TYPE_CHECKING:
    import pandas as pd

    from shared.db.duckdb_client import DuckDBClient
    from shared.db.prices_repo import PricesRepository

__version__ = "1.0.0"
log = structlog.get_logger(__name__)


class DivergenceSignal:
    def __init__(
        self,
        ticker:          str,
        detected_at:     datetime,
        divergence_type: str,
        indicator:       str,
        price_trend:     str,
        indicator_trend: str,
        strength:        float,
        lookback_bars:   int,
    ) -> None:
        self.ticker          = ticker
        self.detected_at     = detected_at
        self.divergence_type = divergence_type
        self.indicator       = indicator
        self.price_trend     = price_trend
        self.indicator_trend = indicator_trend
        self.strength        = strength
        self.lookback_bars   = lookback_bars


class DivergenceDetector:
    """Rileva divergenze RSI e MACD rispetto al prezzo."""

    def __init__(
        self,
        prices_repo: PricesRepository,
        duckdb:      DuckDBClient,
        pivot_window: int = 5,    # barre sinistra/destra per pivot
    ) -> None:
        self._repo         = prices_repo
        self._duckdb       = duckdb
        self._pivot_window = pivot_window

    def detect(self, ticker: str, exchange: str) -> list[DivergenceSignal]:
        """
        Analizza le ultime 100 barre e ritorna le divergenze rilevate.
        Persiste i segnali nuovi su DuckDB.
        """
        df = self._repo.read_ohlcv(
            ticker=ticker, exchange=exchange,
            timeframe=TimeFrame.D1, limit=100,
        )
        if df is None or len(df) < 50:
            return []

        df    = df.sort_values("ts").reset_index(drop=True)
        close = df["close"].to_numpy(dtype=np.float64)

        # Calcola oscillatori
        rsi      = self._compute_rsi(close, period=14)
        macd_hist = self._compute_macd_histogram(close)

        signals: list[DivergenceSignal] = []

        # Ricerca divergenze RSI
        signals.extend(
            self._find_divergences(ticker, df["ts"], close, rsi, "RSI")
        )
        # Ricerca divergenze MACD
        signals.extend(
            self._find_divergences(ticker, df["ts"], close, macd_hist, "MACD")
        )

        # Persisti solo i nuovi segnali
        if signals:
            self._persist(signals)
            log.info(
                "divergence.detected",
                ticker=ticker,
                count=len(signals),
                types=[s.divergence_type for s in signals],
            )
        return signals

    def _find_divergences(
        self,
        ticker:    str,
        timestamps: pd.Series,
        prices:    npt.NDArray[np.float64],
        indicator: npt.NDArray[np.float64],
        ind_name:  str,
    ) -> list[DivergenceSignal]:
        signals = []

        # Trova pivot su prezzo e indicatore
        price_highs   = self._find_pivots(prices,    kind="high")
        price_lows    = self._find_pivots(prices,    kind="low")
        ind_highs     = self._find_pivots(indicator, kind="high")
        ind_lows      = self._find_pivots(indicator, kind="low")

        datetime.now(UTC)

        # ── Bearish: Higher High prezzo + Lower High indicatore ──────────────
        if len(price_highs) >= 2 and len(ind_highs) >= 2:
            ph1, ph2 = price_highs[-2], price_highs[-1]  # due pivot più recenti
            ih1, ih2 = ind_highs[-2],   ind_highs[-1]

            if (prices[ph2]    > prices[ph1] and      # prezzo: Higher High
                indicator[ih2] < indicator[ih1]):      # indicatore: Lower High

                strength = abs(
                    (indicator[ih2] - indicator[ih1]) / (abs(indicator[ih1]) + 1e-9)
                )
                signals.append(DivergenceSignal(
                    ticker=ticker,
                    detected_at=timestamps.iloc[ph2].to_pydatetime().replace(tzinfo=UTC),
                    divergence_type="bearish_" + ind_name.lower(),
                    indicator=ind_name,
                    price_trend="higher_high",
                    indicator_trend="lower_high",
                    strength=float(np.clip(strength, 0, 1)),
                    lookback_bars=int(ph2 - ph1),
                ))

        # ── Bullish: Lower Low prezzo + Higher Low indicatore ────────────────
        if len(price_lows) >= 2 and len(ind_lows) >= 2:
            pl1, pl2 = price_lows[-2], price_lows[-1]
            il1, il2 = ind_lows[-2],   ind_lows[-1]

            if (prices[pl2]    < prices[pl1] and       # prezzo: Lower Low
                indicator[il2] > indicator[il1]):       # indicatore: Higher Low

                strength = abs(
                    (indicator[il2] - indicator[il1]) / (abs(indicator[il1]) + 1e-9)
                )
                signals.append(DivergenceSignal(
                    ticker=ticker,
                    detected_at=timestamps.iloc[pl2].to_pydatetime().replace(tzinfo=UTC),
                    divergence_type="bullish_" + ind_name.lower(),
                    indicator=ind_name,
                    price_trend="lower_low",
                    indicator_trend="higher_low",
                    strength=float(np.clip(strength, 0, 1)),
                    lookback_bars=int(pl2 - pl1),
                ))

        return signals

    def _find_pivots(
        self, arr: npt.NDArray[np.float64], kind: Literal["high", "low"]
    ) -> list[int]:
        """Trova indici dei pivot (massimi o minimi locali) con finestra w."""
        w       = self._pivot_window
        pivots  = []
        for i in range(w, len(arr) - w):
            window = arr[i - w: i + w + 1]
            center = arr[i]
            if (kind == "high" and center == np.max(window)) or (kind == "low" and center == np.min(window)):
                pivots.append(i)
        return pivots

    @staticmethod
    def _compute_rsi(closes: npt.NDArray[np.float64], period: int = 14) -> npt.NDArray[np.float64]:
        delta  = np.diff(closes, prepend=closes[0])
        gains  = np.where(delta > 0, delta, 0.0)
        losses = np.where(delta < 0, -delta, 0.0)

        avg_gain = np.zeros(len(closes), dtype=np.float64)
        avg_loss = np.zeros(len(closes), dtype=np.float64)
        avg_gain[period] = np.mean(gains[1: period + 1])
        avg_loss[period] = np.mean(losses[1: period + 1])

        for i in range(period + 1, len(closes)):
            avg_gain[i] = (avg_gain[i-1] * (period - 1) + gains[i]) / period
            avg_loss[i] = (avg_loss[i-1] * (period - 1) + losses[i]) / period

        rs  = np.where(avg_loss > 0, avg_gain / avg_loss, np.float64(100.0))
        rsi = 100.0 - (100.0 / (1.0 + rs))
        return rsi

    @staticmethod
    def _compute_macd_histogram(
        closes: npt.NDArray[np.float64],
        fast: int = 12, slow: int = 26, signal: int = 9,
    ) -> npt.NDArray[np.float64]:
        def ema(arr: npt.NDArray[np.float64], period: int) -> npt.NDArray[np.float64]:
            alpha = 2.0 / (period + 1)
            out   = np.zeros(len(arr), dtype=np.float64)
            out[0] = arr[0]
            for i in range(1, len(arr)):
                out[i] = alpha * arr[i] + (1 - alpha) * out[i-1]
            return out

        fast_ema   = ema(closes, fast)
        slow_ema   = ema(closes, slow)
        macd_line  = fast_ema - slow_ema
        signal_line = ema(macd_line, signal)
        return macd_line - signal_line  # histogram

    def _persist(self, signals: list[DivergenceSignal]) -> None:
        for s in signals:
            self._duckdb.execute(
                """INSERT OR REPLACE INTO divergence_signals
                   (ticker, detected_at, divergence_type, indicator,
                    price_trend, indicator_trend, strength, lookback_bars)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [s.ticker, s.detected_at, s.divergence_type, s.indicator,
                 s.price_trend, s.indicator_trend, s.strength, s.lookback_bars],
            )
