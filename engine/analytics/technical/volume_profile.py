"""VolumeProfileCalculator — VPVR, POC, VAH, VAL, VWAP.

Volume Profile Visible Range (VPVR):
  Distributes volume across price bins to identify key levels.

Key levels:
  POC  — Point of Control: price level with highest volume
  VAH  — Value Area High: upper bound of the 70% volume area
  VAL  — Value Area Low:  lower bound of the 70% volume area
  VWAP — Volume-Weighted Average Price: fair value reference

Signal: price vs POC / VWAP gives a regime-aware support/resistance signal.
  Price > POC → bullish (above value area)
  Price < POC → bearish (below value area)
  Price in [VAL, VAH] → neutral (inside value area)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared.logger import get_logger

__version__ = "10.0.0"

__all__ = [
    "VolumeProfile",
    "VolumeProfileCalculator",
]

log = get_logger(__name__)

_VALUE_AREA_PCT = 0.70    # 70% of total volume defines the value area
_DEFAULT_N_BINS = 50


@dataclass
class VolumeProfile:
    poc:           float          # Point of Control price
    vah:           float          # Value Area High
    val:           float          # Value Area Low
    vwap:          float          # Volume-Weighted Average Price
    price_bins:    np.ndarray     # Bin centres
    volume_bins:   np.ndarray     # Volume per bin
    current_price: float
    signal:        float          # [-1, 1]: price position vs value area
    signal_label:  str            # "above_va" | "in_va" | "below_va"
    n_bars:        int


class VolumeProfileCalculator:
    """Compute volume profile for a price/volume series.

    Args:
        n_bins:          Number of price bins (default 50).
        value_area_pct:  Fraction of total volume defining the value area (default 0.70).
    """

    def __init__(
        self,
        n_bins:         int   = _DEFAULT_N_BINS,
        value_area_pct: float = _VALUE_AREA_PCT,
    ) -> None:
        self._n_bins  = n_bins
        self._va_pct  = value_area_pct

    def compute(self, ohlcv: pd.DataFrame) -> VolumeProfile:
        """Compute volume profile from OHLCV data.

        Args:
            ohlcv: DataFrame with 'high', 'low', 'close', 'volume' columns.

        Returns:
            VolumeProfile with POC, VAH, VAL, VWAP and trading signal.
        """
        ohlcv = ohlcv.dropna(subset=["high", "low", "close", "volume"])
        if len(ohlcv) < 2:
            return self._empty_profile()

        highs   = ohlcv["high"].values.astype(np.float64)
        lows    = ohlcv["low"].values.astype(np.float64)
        closes  = ohlcv["close"].values.astype(np.float64)
        volumes = ohlcv["volume"].values.astype(np.float64)

        price_min = float(lows.min())
        price_max = float(highs.max())

        if price_max <= price_min:
            return self._empty_profile()

        # Bin edges and centres
        edges   = np.linspace(price_min, price_max, self._n_bins + 1)
        centres = (edges[:-1] + edges[1:]) / 2.0

        # Distribute bar volume across bins it spans
        vol_bins = np.zeros(self._n_bins, dtype=np.float64)
        for h, l, v in zip(highs, lows, volumes):
            lo_idx = np.searchsorted(edges, l, side="left")
            hi_idx = np.searchsorted(edges, h, side="right")
            lo_idx = max(lo_idx - 1, 0)
            hi_idx = min(hi_idx, self._n_bins)
            span   = hi_idx - lo_idx
            if span > 0:
                vol_bins[lo_idx:hi_idx] += v / span

        # POC: bin with max volume
        poc_idx = int(np.argmax(vol_bins))
        poc     = float(centres[poc_idx])

        # Value Area: expand from POC outward until 70% of volume captured
        vah, val = self._compute_value_area(centres, vol_bins, poc_idx)

        # VWAP: volume-weighted average of typical price
        typical = (highs + lows + closes) / 3.0
        total_v = float(volumes.sum())
        vwap    = float(np.dot(typical, volumes) / total_v) if total_v > 0 else float(np.mean(closes))

        current = float(closes[-1])
        signal, label = self._price_signal(current, vah, val, poc)

        log.debug(
            "volume_profile.computed",
            poc=round(poc, 2), vah=round(vah, 2), val=round(val, 2),
            vwap=round(vwap, 2), current=round(current, 2), signal=round(signal, 3),
        )
        return VolumeProfile(
            poc           = round(poc, 4),
            vah           = round(vah, 4),
            val           = round(val, 4),
            vwap          = round(vwap, 4),
            price_bins    = centres,
            volume_bins   = vol_bins,
            current_price = round(current, 4),
            signal        = round(signal, 4),
            signal_label  = label,
            n_bars        = len(ohlcv),
        )

    def _compute_value_area(
        self,
        centres:  np.ndarray,
        vol_bins: np.ndarray,
        poc_idx:  int,
    ) -> tuple[float, float]:
        total       = float(vol_bins.sum())
        target      = total * self._va_pct
        accumulated = float(vol_bins[poc_idx])
        lo_idx      = poc_idx
        hi_idx      = poc_idx

        while accumulated < target and (lo_idx > 0 or hi_idx < len(vol_bins) - 1):
            add_lo = vol_bins[lo_idx - 1] if lo_idx > 0 else 0.0
            add_hi = vol_bins[hi_idx + 1] if hi_idx < len(vol_bins) - 1 else 0.0
            if add_hi >= add_lo and hi_idx < len(vol_bins) - 1:
                hi_idx     += 1
                accumulated += vol_bins[hi_idx]
            elif lo_idx > 0:
                lo_idx     -= 1
                accumulated += vol_bins[lo_idx]
            else:
                break

        return float(centres[hi_idx]), float(centres[lo_idx])

    @staticmethod
    def _price_signal(
        price: float, vah: float, val: float, poc: float,
    ) -> tuple[float, str]:
        """Return (signal [-1,1], label) based on price vs value area."""
        if price >= vah:
            pct_above = float(np.clip((price - vah) / (vah - val + 1e-9), 0.0, 1.0))
            return float(np.clip(0.3 + pct_above * 0.7, 0.0, 1.0)), "above_va"
        if price <= val:
            pct_below = float(np.clip((val - price) / (vah - val + 1e-9), 0.0, 1.0))
            return float(np.clip(-0.3 - pct_below * 0.7, -1.0, 0.0)), "below_va"
        # Inside value area: normalise position (POC = 0)
        mid   = (vah + val) / 2.0
        span  = (vah - val) / 2.0
        score = float(np.clip((price - mid) / (span + 1e-9) * 0.3, -0.3, 0.3))
        return score, "in_va"

    @staticmethod
    def _empty_profile() -> VolumeProfile:
        return VolumeProfile(
            poc=0.0, vah=0.0, val=0.0, vwap=0.0,
            price_bins=np.array([]), volume_bins=np.array([]),
            current_price=0.0, signal=0.0, signal_label="in_va", n_bars=0,
        )
