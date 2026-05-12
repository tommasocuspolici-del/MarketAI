"""Surprise Momentum: accelerazione/decelerazione del flusso di sorprese.

Misura se le sorprese economiche stanno migliorando (momentum positivo)
o peggiorando (momentum negativo) rispetto al trend recente.

Regola 8: numpy per tutti i calcoli.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
import structlog

__version__ = "1.0.0"
__all__ = ["SurpriseMomentum", "MomentumSignal"]
log = structlog.get_logger(__name__)

_ACCEL_THRESHOLD = 0.20   # Variazione > 20% del range → accelerazione


@dataclass(frozen=True)
class MomentumSignal:
    """Segnale di momentum per un settore."""
    sector:          str
    momentum_1m:     float   # Variazione indice rispetto a 1 mese fa
    momentum_3m:     float   # Variazione rispetto a 3 mesi fa
    acceleration:    float   # Seconda derivata (momentum del momentum)
    regime:          str     # 'accelerating'|'decelerating'|'stable'


class SurpriseMomentum:
    """Calcola il momentum delle sorprese settoriali."""

    def compute(
        self,
        sector_history: pd.DataFrame,  # sector, snapshot_date, surprise_index
    ) -> list[MomentumSignal]:
        """Calcola momentum per ogni settore.

        Args:
            sector_history: DataFrame con colonne [sector, snapshot_date, surprise_index].
        """
        results: list[MomentumSignal] = []
        for sector in sector_history["sector"].unique():
            s = (
                sector_history[sector_history["sector"] == sector]
                .sort_values("snapshot_date")
            )
            idx = s["surprise_index"].to_numpy(dtype=np.float64)
            n   = len(idx)

            m1m = float(idx[-1] - idx[-2]) if n >= 2 else 0.0
            m3m = float(idx[-1] - idx[-4]) if n >= 4 else 0.0
            # Accelerazione: differenza tra momentum 1M corrente e precedente
            accel = float(m1m - (idx[-2] - idx[-3])) if n >= 3 else 0.0

            if abs(accel) > _ACCEL_THRESHOLD:
                regime = "accelerating" if accel > 0 else "decelerating"
            else:
                regime = "stable"

            results.append(MomentumSignal(
                sector=sector, momentum_1m=round(m1m, 4),
                momentum_3m=round(m3m, 4), acceleration=round(accel, 4),
                regime=regime,
            ))
        return results
