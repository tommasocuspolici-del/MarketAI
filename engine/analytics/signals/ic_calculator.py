"""Information Coefficient Calculator — Convenzione 36.

IC rolling Spearman per ogni segnale vs rendimento forward.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from shared.logger import get_logger

log = get_logger(__name__)

WINDOW_DEFAULT: int = 252
IC_WEAK_THRESHOLD: float = 0.05
IC_STRONG_THRESHOLD: float = 0.10
TSTAT_SIGNIFICANCE: float = 2.0
MIN_OBSERVATIONS: int = 20


@dataclass
class ICResult:
    signal_id: str
    horizon_days: int
    ic_mean: float
    ic_std: float
    ic_tstat: float
    ic_ir: float
    hit_rate: float
    is_significant: bool


class ICCalculator:
    """Calcola Information Coefficient (Spearman) rolling per un segnale."""

    def __init__(self, window: int = WINDOW_DEFAULT) -> None:
        self._window = window

    def compute(
        self,
        signal: pd.Series,
        forward_returns: pd.Series,
        signal_id: str,
        horizon_days: int,
    ) -> ICResult:
        """Calcola IC medio, std, t-stat, IR e hit rate sul periodo completo.

        Args:
            signal: Serie temporale del segnale (index: datetime).
            forward_returns: Rendimenti forward allineati con signal.
            signal_id: Identificatore del segnale.
            horizon_days: Orizzonte forward in giorni.

        Returns:
            ICResult con tutte le metriche calcolate.
        """
        aligned = pd.concat([signal.rename("sig"), forward_returns.rename("fwd")], axis=1).dropna()

        if len(aligned) < MIN_OBSERVATIONS:
            log.warning(
                "ic_calculator.insufficient_data",
                signal_id=signal_id,
                n_obs=len(aligned),
                min_required=MIN_OBSERVATIONS,
            )
            return ICResult(
                signal_id=signal_id,
                horizon_days=horizon_days,
                ic_mean=0.0,
                ic_std=0.0,
                ic_tstat=0.0,
                ic_ir=0.0,
                hit_rate=0.5,
                is_significant=False,
            )

        ic_series = self.compute_rolling(signal, forward_returns, signal_id, horizon_days)
        ic_clean = ic_series.dropna()

        if len(ic_clean) == 0:
            ic_mean = float(stats.spearmanr(aligned["sig"], aligned["fwd"])[0])
            ic_std = 0.0
            ic_tstat = 0.0
            ic_ir = 0.0
        else:
            ic_mean = float(ic_clean.mean())
            ic_std = float(ic_clean.std(ddof=1)) if len(ic_clean) > 1 else 0.0
            n = len(ic_clean)
            ic_tstat = float(ic_mean / ic_std * np.sqrt(n)) if ic_std > 0 else 0.0
            ic_ir = float(ic_mean / ic_std) if ic_std > 0 else 0.0

        # Hit rate: fraction of periods where signal and return have same sign
        same_sign = (aligned["sig"] * aligned["fwd"]) > 0
        hit_rate = float(same_sign.mean())

        is_significant = abs(ic_tstat) >= TSTAT_SIGNIFICANCE and abs(ic_mean) >= IC_WEAK_THRESHOLD

        log.info(
            "ic_calculator.computed",
            signal_id=signal_id,
            horizon_days=horizon_days,
            ic_mean=round(ic_mean, 4),
            ic_tstat=round(ic_tstat, 2),
            is_significant=is_significant,
        )

        return ICResult(
            signal_id=signal_id,
            horizon_days=horizon_days,
            ic_mean=ic_mean,
            ic_std=ic_std,
            ic_tstat=ic_tstat,
            ic_ir=ic_ir,
            hit_rate=hit_rate,
            is_significant=is_significant,
        )

    def compute_rolling(
        self,
        signal: pd.Series,
        forward_returns: pd.Series,
        signal_id: str,
        horizon_days: int,
    ) -> pd.Series:
        """Calcola serie rolling dell'IC Spearman con finestra self._window.

        Args:
            signal: Serie temporale del segnale.
            forward_returns: Rendimenti forward allineati.
            signal_id: Identificatore del segnale (usato per logging).
            horizon_days: Orizzonte forward in giorni.

        Returns:
            pd.Series di IC rolling (NaN per le finestre iniziali insufficienti).
        """
        aligned = pd.concat([signal.rename("sig"), forward_returns.rename("fwd")], axis=1).dropna()

        if len(aligned) < MIN_OBSERVATIONS:
            return pd.Series(dtype=float)

        # Explicit rolling Spearman via expanding apply on aligned DataFrame
        results: list[float] = []
        for i in range(len(aligned)):
            start = max(0, i - self._window + 1)
            window_slice = aligned.iloc[start : i + 1]
            if len(window_slice) < MIN_OBSERVATIONS:
                results.append(float("nan"))
            else:
                corr, _ = stats.spearmanr(window_slice["sig"], window_slice["fwd"])
                results.append(float(corr))

        return pd.Series(results, index=aligned.index, name=f"ic_{signal_id}")
