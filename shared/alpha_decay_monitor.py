"""AlphaDecayMonitor — tracks IC decay for every signal (QC-2).

Each module that produces a signal MUST call monitor.update() after each
computation with the realized forward return, and check_decay() before
publishing to detect low-IC conditions.

IC (Information Coefficient) is the Spearman rank correlation between
signal values and their subsequent forward returns.

Thresholds (from config/alpha_decay.yaml):
    IC_MIN_THRESHOLD = 0.02   → quality_flag = "low_ic"
    IC_SOFT_WARNING  = 0.05   → log warning (no block)
"""
from __future__ import annotations

import threading
from collections import deque
from typing import Any, NamedTuple

import numpy as np
from scipy import stats

from shared.constants import CONFIG_DIR
from shared.logger import get_logger

import yaml

__version__ = "10.0.0"

__all__ = [
    "IC_MIN_THRESHOLD",
    "IC_SOFT_WARNING",
    "AlphaDecayMonitor",
    "ICObservation",
]

log = get_logger(__name__)

_ALPHA_DECAY_PATH = CONFIG_DIR / "alpha_decay.yaml"


def _load_alpha_decay_config() -> dict[str, Any]:
    try:
        result: dict[str, Any] = yaml.safe_load(_ALPHA_DECAY_PATH.read_text()) or {}
        return result
    except Exception:
        return {}


_cfg = _load_alpha_decay_config()
IC_MIN_THRESHOLD: float = float(_cfg.get("ic_min_threshold", 0.02))
IC_SOFT_WARNING: float  = float(_cfg.get("ic_soft_warning", 0.05))
_DEFAULT_LOOKBACK: int  = int(_cfg.get("default_lookback_days", 126))
_WEIGHT_LOW_IC: float   = float(_cfg.get("weight_low_ic", 0.5))
_WEIGHT_DEGRADED: float = float(_cfg.get("weight_degraded", 0.1))


class ICObservation(NamedTuple):
    signal_value:   float
    forward_return: float
    horizon_days:   int


class AlphaDecayMonitor:
    """Thread-safe monitor for IC decay across all signals.

    Usage (in every analytical module after computing a signal value)::

        monitor.update("sentiment_composite", signal_value=0.4, forward_return=0.02)
        ic, flag = monitor.check_decay("sentiment_composite")
    """

    _MIN_OBSERVATIONS = 30          # minimum sample size before IC is meaningful

    def __init__(self, lookback_days: int = _DEFAULT_LOOKBACK) -> None:
        self._lookback = lookback_days
        self._observations: dict[str, deque[ICObservation]] = {}
        self._lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────

    def update(
        self,
        signal_name:    str,
        signal_value:   float,
        forward_return: float,
        horizon_days:   int = 5,
    ) -> None:
        """Register a (signal_value, realized_forward_return) pair."""
        obs = ICObservation(signal_value, forward_return, horizon_days)
        with self._lock:
            if signal_name not in self._observations:
                self._observations[signal_name] = deque(maxlen=self._lookback)
            self._observations[signal_name].append(obs)

    def check_decay(self, signal_name: str) -> tuple[float | None, str]:
        """Return (ic_rolling, quality_flag) for *signal_name*.

        quality_flag:
            "ok"               — IC ≥ IC_SOFT_WARNING or not yet estimated
            "low_ic"           — IC in [IC_MIN, IC_SOFT_WARNING)
            "insufficient_data" — fewer than 30 observations
            (signal_name not tracked) → (None, "insufficient_data")
        """
        with self._lock:
            buf = self._observations.get(signal_name)

        if not buf or len(buf) < self._MIN_OBSERVATIONS:
            return None, "insufficient_data"

        signals  = np.array([o.signal_value   for o in buf])
        returns  = np.array([o.forward_return  for o in buf])

        try:
            corr, _ = stats.spearmanr(signals, returns)
            ic = float(corr) if not np.isnan(corr) else 0.0
        except Exception:
            return None, "insufficient_data"

        if ic < IC_MIN_THRESHOLD:
            flag = "low_ic"
            log.warning(
                "alpha_decay.low_ic",
                signal=signal_name,
                ic=round(ic, 4),
                threshold=IC_MIN_THRESHOLD,
            )
        elif ic < IC_SOFT_WARNING:
            flag = "ok"
            log.warning(
                "alpha_decay.soft_warning",
                signal=signal_name,
                ic=round(ic, 4),
                threshold=IC_SOFT_WARNING,
            )
        else:
            flag = "ok"

        return ic, flag

    def get_weight_multiplier(self, signal_name: str) -> float:
        """Return weight multiplier [0.1, 1.0] based on current IC.

        IC ≥ IC_SOFT_WARNING  → 1.0  (full weight)
        IC ∈ [IC_MIN, SOFT)   → 0.5  (reduced)
        IC < IC_MIN           → 0.1  (nearly zeroed, signal in decay)
        not yet estimated     → 1.0  (benefit of the doubt)
        """
        ic, flag = self.check_decay(signal_name)
        if ic is None:
            return 1.0
        if ic >= IC_SOFT_WARNING:
            return 1.0
        if ic >= IC_MIN_THRESHOLD:
            return _WEIGHT_LOW_IC
        return _WEIGHT_DEGRADED

    def all_signals(self) -> list[str]:
        with self._lock:
            return list(self._observations.keys())

    def observation_count(self, signal_name: str) -> int:
        with self._lock:
            buf = self._observations.get(signal_name)
            return len(buf) if buf else 0
