"""DSL safe namespace — functions callable from custom indicator expressions.

All functions here are pure (no side effects) or read-only (signal registry).
The evaluator injects this dict as the execution namespace, with __builtins__={}
so no built-in Python functions are accessible.

Functions available in DSL expressions:
    EMA(values, period)           — Exponential moving average of last value
    SMA(values, period)           — Simple moving average of last value
    RSI(values, period)           — RSI of a signal series (approximated)
    ATR(highs, lows, closes, p)   — ATR (approximated from vols)
    ZSCORE(value, mean, std)      — Z-score normalisation
    signal(name)                  — Get latest signal value from registry [-1,1]
    macro(name)                   — Alias for signal(name)
    regime()                      — Current regime label string
    n_agreeing(threshold)         — Count signals above |threshold|
    ic(signal_name)               — IC estimate of a signal (float | None)
    quality(signal_name)          — quality_flag of a signal
    regime_weight(component)      — Current regime weight for a component
    cash_reserve_months()         — Portfolio cash reserve in months (injected)
    portfolio_beta()              — Portfolio beta vs SPY (injected)
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from shared.alpha_decay_monitor import AlphaDecayMonitor
from shared.signal_registry import get_signal_registry

__version__ = "10.0.0"

__all__ = [
    "build_namespace",
]

# ── Technical helpers (stateless) ─────────────────────────────────────────

def _ema(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    arr = np.array(values, dtype=np.float64)
    alpha = 2.0 / (period + 1)
    ema = arr[0]
    for v in arr[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return float(ema)


def _sma(values: list[float], period: int) -> float:
    if not values:
        return 0.0
    return float(np.mean(values[-period:]))


def _rsi(values: list[float], period: int = 14) -> float:
    if len(values) < 2:
        return 50.0
    arr = np.array(values, dtype=np.float64)
    deltas = np.diff(arr)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = float(np.mean(gains[-period:]))
    avg_loss = float(np.mean(losses[-period:]))
    if avg_loss < 1e-9:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def _atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> float:
    if len(highs) < 2:
        return 0.0
    trs: list[float] = []
    for i in range(1, len(highs)):
        hl  = highs[i]  - lows[i]
        hc  = abs(highs[i]  - closes[i - 1])
        lc  = abs(lows[i]   - closes[i - 1])
        trs.append(max(hl, hc, lc))
    return float(np.mean(trs[-period:]))


def _zscore(value: float, mean: float, std: float) -> float:
    if std < 1e-9:
        return 0.0
    return float((value - mean) / std)


# ── Signal-aware helpers (read from SignalRegistry) ────────────────────────

def _get_signal(name: str) -> float:
    registry = get_signal_registry()
    value = registry.snapshot().get(name)
    return float(value) if value is not None else 0.0


def _get_macro(name: str) -> float:
    return _get_signal(name)


def _get_regime() -> str:
    registry = get_signal_registry()
    snap = registry.snapshot()
    for rname in ("regime_label", "hmm_regime", "current_regime"):
        v = snap.get(rname)
        if v is not None:
            return str(v)
    return "transition"


def _count_agreeing(threshold: float = 0.2) -> int:
    registry = get_signal_registry()
    snap = registry.snapshot()
    core = [
        "technical_composite", "macro_conviction", "labour_regime_signal",
        "sentiment_composite", "valuation_signal", "economic_surprise_index", "vix_signal",
    ]
    return sum(1 for n in core if abs(snap.get(n, 0.0)) >= threshold)


def _make_ic_fn(
    decay_monitor: AlphaDecayMonitor | None,
) -> "Callable[[str], float]":
    def _get_ic(signal_name: str) -> float:
        if decay_monitor is None:
            return 0.0
        ic, _ = decay_monitor.check_decay(signal_name)
        return float(ic) if ic is not None else 0.0
    return _get_ic


def _make_quality_fn(
    decay_monitor: AlphaDecayMonitor | None,
) -> "Callable[[str], str]":
    def _get_quality_flag(signal_name: str) -> str:
        if decay_monitor is None:
            return "insufficient_data"
        _, flag = decay_monitor.check_decay(signal_name)
        return flag
    return _get_quality_flag


def _make_regime_weight_fn(
    weights_config: dict[str, Any],
) -> "Callable[[str], float]":
    def _get_regime_weight(component: str) -> float:
        regime = _get_regime()
        regime_weights = weights_config.get("regime_signal_weights", {})
        current = regime_weights.get(regime, regime_weights.get("transition", {}))
        return float(current.get(component, 0.0))
    return _get_regime_weight


# ── Namespace builder ──────────────────────────────────────────────────────

def build_namespace(
    decay_monitor: AlphaDecayMonitor | None = None,
    weights_config: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the safe execution namespace for DSL expression evaluation.

    Args:
        decay_monitor:  AlphaDecayMonitor for ic() and quality() functions.
                        If None, ic() returns 0.0 and quality() returns "insufficient_data".
        weights_config: Parsed regime_weights.yaml dict for regime_weight().
        extra:          Additional context values (e.g. portfolio_beta, cash_reserve_months).

    Returns:
        dict suitable for eval(..., namespace).
    """
    ns: dict[str, Any] = {
        "__builtins__": {},      # CRITICAL: block all built-ins
        # Math constants
        "True":  True,
        "False": False,
        "None":  None,
        # Technical
        "EMA":   _ema,
        "SMA":   _sma,
        "RSI":   _rsi,
        "ATR":   _atr,
        "ZSCORE": _zscore,
        # Signals
        "signal":  _get_signal,
        "macro":   _get_macro,
        "regime":  _get_regime,
        "n_agreeing": _count_agreeing,
        # Quality (QC)
        "ic":            _make_ic_fn(decay_monitor),
        "quality":       _make_quality_fn(decay_monitor),
        "regime_weight": _make_regime_weight_fn(weights_config or {}),
        # Portfolio defaults (overridden by extra)
        "cash_reserve_months": lambda: 0.0,
        "portfolio_beta":      lambda: 1.0,
    }
    if extra:
        ns.update(extra)
    return ns
