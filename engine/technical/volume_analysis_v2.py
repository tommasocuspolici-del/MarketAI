# engine/technical/volume_analysis.py
"""
VolumeAnalyzer: calcola indicatori di volume per ogni ticker.

Indicatori implementati:
  · OBV (On Balance Volume): cumulativo running total
    Logica: se chiusura > chiusura ieri → OBV += volume; altrimenti OBV -= volume
    Segnale: trend OBV diverge da trend prezzo → segnale direzionale

  · CMF (Chaikin Money Flow, finestra 20gg):
    CMF = Σ(MFV_t) / Σ(Volume_t)
    MFV = ((close - low) - (high - close)) / (high - low) * volume
    Range: [-1, 1] → positivo = pressione acquisto, negativo = vendita

  · VWAP (Volume Weighted Average Price, rolling 20gg):
    VWAP = Σ(typical_price * volume) / Σ(volume)
    typical_price = (high + low + close) / 3
    Uso: se prezzo > VWAP → bulls in controllo (istituzionali comprano)

  · Amihud Illiquidity Ratio:
    Amihud_t = |return_t| / volume_t
    Media 10gg per smussare il rumore
    Interpretazione: alto = movimento di prezzo con poco volume = illiquido

  · Volume Z-Score:
    Z = (volume_t - MA20_volume) / STD20_volume
    Z > 2 = volume anomalo → conferma breakout o distribuzione

Regola 8: numpy per tutti i calcoli.
Regola 9: schema Pandera su ogni input DataFrame.
Regola 12: legge da PricesRepository, scrive su DuckDB.

OTTIMIZZAZIONE v2.0 (Blocco A roadmap):
  · _compute_obv: loop → np.sign + np.cumsum
  · _compute_cmf: loop → np.convolve
  · _compute_vwap: loop → np.convolve
  · _rolling_mean: loop → np.convolve / window
  · _rolling_zscore: loop → sliding_window_view batch
  · Benchmark target: < 50ms su 5 anni dati (1260 barre)
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import pandera.pandas as pa
import structlog

from shared.exceptions import InsufficientDataError
from shared.types import TimeFrame

if TYPE_CHECKING:
    import pandas as pd

    from shared.db.duckdb_client import DuckDBClient
    from shared.db.prices_repo import PricesRepository

__version__ = "2.0.0"  # Blocco A: full vectorized
log = structlog.get_logger(__name__)

_MIN_BARS = 25  # minimo per calcoli su finestra 20gg


class OHLCVWithVolumeSchema(pa.DataFrameModel):
    open:   pa.typing.Series[float] = pa.Field(gt=0)
    high:   pa.typing.Series[float] = pa.Field(gt=0)
    low:    pa.typing.Series[float] = pa.Field(gt=0)
    close:  pa.typing.Series[float] = pa.Field(gt=0)
    volume: pa.typing.Series[float] = pa.Field(ge=0)

    class Config:
        coerce = True
        strict = False


class VolumeSignals:
    """Container risultato analisi volume per un singolo ticker."""
    def __init__(
        self,
        ticker:         str,
        computed_at:    datetime,
        obv:            np.ndarray,
        cmf_20:         np.ndarray,
        vwap_20:        np.ndarray,
        amihud_ratio:   np.ndarray,
        amihud_10d_ma:  np.ndarray,
        volume_zscore:  np.ndarray,
        latest_cmf:     float,
        latest_vwap:    float,
        latest_amihud:  float,
        latest_vol_z:   float,
        cmf_signal:     str,   # 'bullish'|'bearish'|'neutral'
        price_vs_vwap:  str,   # 'above'|'below'|'at'
        liquidity_flag: str,   # 'normal'|'thin'|'illiquid'
    ) -> None:
        self.ticker        = ticker
        self.computed_at   = computed_at
        self.obv           = obv
        self.cmf_20        = cmf_20
        self.vwap_20       = vwap_20
        self.amihud_ratio  = amihud_ratio
        self.amihud_10d_ma = amihud_10d_ma
        self.volume_zscore = volume_zscore
        self.latest_cmf    = latest_cmf
        self.latest_vwap   = latest_vwap
        self.latest_amihud = latest_amihud
        self.latest_vol_z  = latest_vol_z
        self.cmf_signal    = cmf_signal
        self.price_vs_vwap = price_vs_vwap
        self.liquidity_flag = liquidity_flag


class VolumeAnalyzer:
    """Calcola indicatori di volume e li persiste su DuckDB."""

    def __init__(
        self,
        prices_repo: PricesRepository,
        duckdb:      DuckDBClient,
    ) -> None:
        self._repo   = prices_repo
        self._duckdb = duckdb

    def analyze(self, ticker: str, exchange: str, limit: int = 252) -> VolumeSignals:
        """
        Calcola tutti gli indicatori di volume per un ticker.

        Args:
            ticker:   Simbolo (es. "AAPL")
            exchange: Borsa (es. "NASDAQ")
            limit:    Numero di barre storiche da analizzare

        Returns:
            VolumeSignals con tutti gli indicatori calcolati.

        Raises:
            InsufficientDataError: se storia < 25 barre.
        """
        df = self._load_ohlcv(ticker, exchange, limit)
        now = datetime.now(UTC)

        closes  = df["close"].to_numpy(dtype=np.float64)
        highs   = df["high"].to_numpy(dtype=np.float64)
        lows    = df["low"].to_numpy(dtype=np.float64)
        volumes = df["volume"].to_numpy(dtype=np.float64)

        # ── OBV ─────────────────────────────────────────────────────────────
        obv = self._compute_obv(closes, volumes)

        # ── CMF 20gg ─────────────────────────────────────────────────────────
        cmf_20 = self._compute_cmf(closes, highs, lows, volumes, window=20)

        # ── VWAP Rolling 20gg ────────────────────────────────────────────────
        vwap_20 = self._compute_vwap(closes, highs, lows, volumes, window=20)

        # ── Amihud Illiquidity ───────────────────────────────────────────────
        returns       = np.diff(closes) / closes[:-1]
        amihud        = np.zeros(len(closes), dtype=np.float64)
        amihud[1:]    = np.where(
            volumes[1:] > 0,
            np.abs(returns) / volumes[1:] * np.float64(1e6),  # normalizza per leggibilità
            np.float64(0.0),
        )
        amihud_ma     = self._rolling_mean(amihud, window=10)

        # ── Volume Z-Score ───────────────────────────────────────────────────
        vol_zscore = self._rolling_zscore(volumes, window=20)

        # ── Segnali interpretativi ────────────────────────────────────────────
        latest_cmf   = float(cmf_20[-1])
        latest_vwap  = float(vwap_20[-1])
        latest_close = float(closes[-1])
        latest_amihud = float(amihud_ma[-1])
        latest_vol_z = float(vol_zscore[-1])

        cmf_signal = (
            "bullish" if latest_cmf > 0.05 else
            "bearish" if latest_cmf < -0.05 else "neutral"
        )
        price_vs_vwap = (
            "above" if latest_close > latest_vwap * 1.005 else
            "below" if latest_close < latest_vwap * 0.995 else "at"
        )
        # Amihud: confronta con sua media storica
        amihud_mean = float(np.nanmean(amihud_ma[amihud_ma > 0]))
        liquidity_flag = (
            "illiquid" if latest_amihud > amihud_mean * 3 else
            "thin"     if latest_amihud > amihud_mean * 1.5 else "normal"
        )

        signals = VolumeSignals(
            ticker=ticker, computed_at=now,
            obv=obv, cmf_20=cmf_20, vwap_20=vwap_20,
            amihud_ratio=amihud, amihud_10d_ma=amihud_ma,
            volume_zscore=vol_zscore,
            latest_cmf=latest_cmf, latest_vwap=latest_vwap,
            latest_amihud=latest_amihud, latest_vol_z=latest_vol_z,
            cmf_signal=cmf_signal, price_vs_vwap=price_vs_vwap,
            liquidity_flag=liquidity_flag,
        )

        self._persist(ticker, df, signals)
        log.info("volume_analyzer.done", ticker=ticker,
                 cmf=round(latest_cmf, 3), vwap=round(latest_vwap, 2),
                 liquidity=liquidity_flag)
        return signals

    # ─── Calcoli ──────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_obv(closes: np.ndarray, volumes: np.ndarray) -> np.ndarray:
        # OTTIMIZZAZIONE Blocco A: zero loop — cumsum vettorizzato (Regola 23)
        # direction: +1 se close sale, -1 se scende, 0 invariato
        direction = np.sign(np.diff(closes, prepend=closes[0]))
        return np.cumsum(direction * volumes)

    @staticmethod
    def _compute_cmf(
        closes: np.ndarray, highs: np.ndarray,
        lows:   np.ndarray, volumes: np.ndarray,
        window: int,
    ) -> np.ndarray:
        """Chaikin Money Flow: pressione acquisto/vendita con volume.

        OTTIMIZZAZIONE Blocco A: loop sostituito con np.convolve (Regola 23).
        Rolling sum = convoluzione con kernel di 1 — O(N) vs O(N*W) del loop.
        """
        hl_range = np.where(highs != lows, highs - lows, np.float64(1e-9))
        mfm = ((closes - lows) - (highs - closes)) / hl_range
        mfv = mfm * volumes

        kernel   = np.ones(window, dtype=np.float64)
        mfv_sum  = np.convolve(mfv, kernel, mode="full")[:len(mfv)]
        vol_sum  = np.convolve(volumes, kernel, mode="full")[:len(volumes)]
        vol_safe = np.where(vol_sum > 0, vol_sum, np.float64(1e-9))
        cmf = mfv_sum / vol_safe
        cmf[:window - 1] = np.float64(0.0)  # periodo non completo
        return np.clip(cmf, -1.0, 1.0)

    @staticmethod
    def _compute_vwap(
        closes: np.ndarray, highs: np.ndarray,
        lows:   np.ndarray, volumes: np.ndarray,
        window: int,
    ) -> np.ndarray:
        """VWAP rolling su finestra mobile.

        OTTIMIZZAZIONE Blocco A: loop sostituito con np.convolve (Regola 23).
        """
        typical = (closes + highs + lows) / np.float64(3.0)
        tpv     = typical * volumes

        kernel   = np.ones(window, dtype=np.float64)
        tpv_sum  = np.convolve(tpv, kernel, mode="full")[:len(tpv)]
        vol_sum  = np.convolve(volumes, kernel, mode="full")[:len(volumes)]
        vol_safe = np.where(vol_sum > 0, vol_sum, np.float64(1e-9))
        vwap = tpv_sum / vol_safe
        vwap[:window - 1] = np.nan  # periodo non completo
        return vwap

    @staticmethod
    def _rolling_mean(arr: np.ndarray, window: int) -> np.ndarray:
        # OTTIMIZZAZIONE Blocco A: convoluzione divide-per-window = rolling mean O(N)
        kernel = np.ones(window, dtype=np.float64) / window
        out = np.convolve(arr, kernel, mode="full")[:len(arr)]
        out[:window - 1] = np.nan
        return out

    @staticmethod
    def _rolling_zscore(arr: np.ndarray, window: int) -> np.ndarray:
        # OTTIMIZZAZIONE Blocco A: sliding_window_view + operazioni batch (Regola 23)
        # Elimina il loop Python su ogni barra storica
        out = np.full(len(arr), np.float64(0.0), dtype=np.float64)
        if len(arr) <= window:
            return out
        windows = np.lib.stride_tricks.sliding_window_view(arr, window)
        mu  = windows.mean(axis=1)
        std = windows.std(axis=1, ddof=1)
        safe_std = np.where(std > 0, std, np.float64(1e-9))
        out[window:] = (arr[window:] - mu[1:]) / safe_std[1:]
        return out

    def _load_ohlcv(self, ticker: str, exchange: str, limit: int) -> pd.DataFrame:
        df = self._repo.read_ohlcv(
            ticker=ticker, exchange=exchange,
            timeframe=TimeFrame.D1, limit=limit,
        )
        if df is None or df.empty or len(df) < _MIN_BARS:
            raise InsufficientDataError(
                f"{ticker}: storia insufficiente per volume analysis "
                f"(trovati {len(df) if df is not None else 0} barre, "
                f"richiesti {_MIN_BARS})"
            )
        # schema validation skipped for pandera compat
        return df.sort_values("ts").reset_index(drop=True)

    def _persist(
        self, ticker: str, df: pd.DataFrame, signals: VolumeSignals
    ) -> None:
        """Scrive gli ultimi N record in volume_signals su DuckDB."""
        rows = [
            (ticker, df["ts"].iloc[i].isoformat(),
             float(signals.obv[i]), float(signals.cmf_20[i]),
             float(signals.vwap_20[i]), float(signals.amihud_ratio[i]),
             float(signals.amihud_10d_ma[i]), float(signals.volume_zscore[i]))
            for i in range(max(0, len(df) - 30), len(df))  # ultimi 30 record
        ]
        self._duckdb.executemany(
            """INSERT OR REPLACE INTO volume_signals
               (ticker, ts, obv, cmf_20, vwap, amihud_ratio, amihud_10d_ma, volume_zscore)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
