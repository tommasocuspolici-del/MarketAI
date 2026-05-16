"""CycleAnalyzer — Hurst exponent + FFT dominant cycle detection.

Hurst Exponent (R/S analysis):
  H > 0.5 → trending (persistent) — trend-following strategies favoured
  H ≈ 0.5 → random walk — no exploitable structure
  H < 0.5 → mean-reverting — mean-reversion strategies favoured

FFT Dominant Cycle:
  Applies Fast Fourier Transform to de-trended price returns.
  Identifies the dominant cycle length (in trading days) in the price series.
  Common cycles: 20D (monthly), 63D (quarterly), 126D (semi-annual).

Uses scipy.fft for FFT (available) and a pure-numpy R/S implementation
for the Hurst exponent (no external libraries needed).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.fft import fft, fftfreq

from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = [
    "CycleResult",
    "CycleAnalyzer",
]

log = get_logger(__name__)

_MIN_OBS_HURST  = 50      # minimum observations for meaningful Hurst estimate
_MIN_OBS_FFT    = 30      # minimum observations for FFT


@dataclass
class CycleResult:
    hurst:              float | None   # [0, 1] — None if insufficient data
    hurst_regime:       str            # "trending" | "random" | "mean_reverting" | "unknown"
    dominant_cycle_days: int | None    # Dominant FFT cycle in trading days
    fft_power:          np.ndarray     # Power spectrum
    fft_freqs:          np.ndarray     # Frequency array
    n_obs:              int


class CycleAnalyzer:
    """Estimate Hurst exponent and dominant market cycle via FFT.

    Args:
        min_obs_hurst:  Minimum observations for Hurst calculation.
        min_obs_fft:    Minimum observations for FFT.
    """

    def __init__(
        self,
        min_obs_hurst: int = _MIN_OBS_HURST,
        min_obs_fft:   int = _MIN_OBS_FFT,
    ) -> None:
        self._min_hurst = min_obs_hurst
        self._min_fft   = min_obs_fft

    def analyze(self, prices: pd.Series | np.ndarray) -> CycleResult:
        """Compute Hurst exponent and dominant FFT cycle.

        Args:
            prices: Closing price series (pd.Series or np.ndarray).

        Returns:
            CycleResult with Hurst and dominant cycle.
        """
        arr = np.asarray(prices, dtype=np.float64)
        arr = arr[~np.isnan(arr)]
        n   = len(arr)

        hurst       = self._hurst_rs(arr) if n >= self._min_hurst else None
        h_regime    = self._hurst_regime(hurst)
        cycle_days  = self._fft_dominant_cycle(arr) if n >= self._min_fft else None

        # FFT power spectrum (for chart)
        if n >= self._min_fft:
            returns      = np.diff(np.log(arr + 1e-9))
            power        = np.abs(fft(returns - returns.mean())) ** 2
            freqs        = fftfreq(len(returns))
            pos_mask     = freqs > 0
            fft_power    = power[pos_mask]
            fft_freqs    = freqs[pos_mask]
        else:
            fft_power = np.array([])
            fft_freqs = np.array([])

        log.debug(
            "cycle.analyzed",
            hurst=round(hurst, 3) if hurst else None,
            regime=h_regime,
            cycle_days=cycle_days,
            n=n,
        )
        return CycleResult(
            hurst               = round(hurst, 4) if hurst is not None else None,
            hurst_regime        = h_regime,
            dominant_cycle_days = cycle_days,
            fft_power           = fft_power,
            fft_freqs           = fft_freqs,
            n_obs               = n,
        )

    # ── Hurst exponent via R/S analysis ───────────────────────────────────

    def _hurst_rs(self, prices: np.ndarray) -> float:
        """Estimate Hurst exponent via rescaled range analysis (multi-window average)."""
        returns = np.diff(np.log(prices + 1e-9))
        n       = len(returns)

        # Multiple window sizes (logarithmically spaced)
        min_w = max(8, n // 20)
        max_w = n // 2
        lags  = sorted(set(
            int(min_w * (max_w / min_w) ** (i / 7.0))
            for i in range(8)
        ))
        lags  = [l for l in lags if min_w <= l <= max_w]
        if len(lags) < 2:
            return 0.5

        rs_vals:  list[float] = []
        lag_vals: list[float] = []

        for lag in lags:
            n_windows = n // lag
            if n_windows < 1:
                continue
            # Average RS across non-overlapping windows of length lag
            rs_list = [
                self._rs_stat(returns[w * lag:(w + 1) * lag])
                for w in range(n_windows)
            ]
            rs_list = [r for r in rs_list if r > 0]
            if rs_list:
                rs_vals.append(np.log(float(np.mean(rs_list))))
                lag_vals.append(np.log(float(lag)))

        if len(rs_vals) < 2:
            return 0.5

        # Hurst = slope of log(RS) vs log(n)
        slope, _ = np.polyfit(lag_vals, rs_vals, 1)
        return float(np.clip(slope, 0.0, 1.0))

    @staticmethod
    def _rs_stat(series: np.ndarray) -> float:
        """Rescaled range for a single segment."""
        if len(series) < 2:
            return 0.0
        mean     = series.mean()
        devs     = np.cumsum(series - mean)
        r        = devs.max() - devs.min()
        s        = series.std(ddof=1)
        if s < 1e-9:
            return 0.0
        return float(r / s)

    # ── FFT dominant cycle ─────────────────────────────────────────────────

    def _fft_dominant_cycle(self, prices: np.ndarray) -> int | None:
        """Find dominant cycle in trading days via FFT on log-returns."""
        returns = np.diff(np.log(prices + 1e-9))
        if len(returns) < self._min_fft:
            return None

        detrended = returns - returns.mean()
        power     = np.abs(fft(detrended)) ** 2
        freqs     = fftfreq(len(detrended))

        # Only positive frequencies with period > 5 and < n/2 trading days
        pos_mask = (freqs > 0) & (freqs < 0.5)
        if not pos_mask.any():
            return None

        pos_freqs = freqs[pos_mask]
        pos_power = power[pos_mask]

        # Filter to meaningful periods: 5 to 252 trading days
        period_mask = (1.0 / (pos_freqs + 1e-9) >= 5) & (1.0 / (pos_freqs + 1e-9) <= 252)
        if not period_mask.any():
            return None

        dom_freq   = pos_freqs[period_mask][np.argmax(pos_power[period_mask])]
        cycle_days = int(round(1.0 / dom_freq))
        return max(5, min(cycle_days, 252))

    @staticmethod
    def _hurst_regime(hurst: float | None) -> str:
        if hurst is None:
            return "unknown"
        if hurst > 0.55:
            return "trending"
        if hurst < 0.45:
            return "mean_reverting"
        return "random"
