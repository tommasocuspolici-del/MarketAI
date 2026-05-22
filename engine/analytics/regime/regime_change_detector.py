"""Regime Change Detector — CUSUM + Bai-Perron structural break."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from shared.logger import get_logger

log = get_logger(__name__)

CUSUM_THRESHOLD: float = 5.0
MIN_SERIES_LENGTH: int = 10   # Minimo punti per CUSUM


@dataclass
class ChangePoint:
    detected_date: date
    signal_series: str
    cusum_value: float
    is_significant: bool


class RegimeChangeDetector:
    """Detecta breakpoint strutturali con CUSUM.

    L'algoritmo CUSUM accumula le deviazioni dalla media della serie.
    Un changepoint viene rilevato quando il CUSUM supera una soglia
    pari a `threshold` deviazioni standard della serie.
    """

    def __init__(self, threshold: float = CUSUM_THRESHOLD) -> None:
        self._threshold = threshold

    def cusum_detect(
        self,
        series: pd.Series,
        series_name: str = "",
    ) -> list[ChangePoint]:
        """Applica CUSUM alla serie e restituisce i changepoint.

        Algoritmo:
        1. Calcola la deviazione media della serie (mu).
        2. Accumula CUSUM_pos = max(0, prev + x - mu - k) e CUSUM_neg.
        3. Un changepoint viene rilevato quando CUSUM > threshold * sigma.

        Args:
            series: Serie temporale con DatetimeIndex.
            series_name: Nome della serie (per logging e output).

        Returns:
            Lista di ChangePoint rilevati.
        """
        clean = series.dropna()

        if len(clean) < MIN_SERIES_LENGTH:
            log.warning(
                "cusum.insufficient_data",
                series=series_name,
                n=len(clean),
                min_required=MIN_SERIES_LENGTH,
            )
            return []

        values = clean.values.astype(float)
        mu = float(np.mean(values))
        sigma = float(np.std(values, ddof=1))

        if sigma < 1e-9:
            return []  # Serie costante, nessun changepoint possibile

        slack = sigma * 0.5   # k = sigma/2 (standard CUSUM parametrization)
        threshold_abs = self._threshold * sigma

        cusum_pos = 0.0
        cusum_neg = 0.0
        changepoints: list[ChangePoint] = []

        for i, (idx, val) in enumerate(zip(clean.index, values)):
            cusum_pos = max(0.0, cusum_pos + (val - mu) - slack)
            cusum_neg = max(0.0, cusum_neg - (val - mu) - slack)

            # Usa il valore assoluto massimo
            cusum_value = max(cusum_pos, cusum_neg)
            is_significant = cusum_value >= threshold_abs

            if is_significant:
                # Converte l'indice in date
                if hasattr(idx, "date"):
                    detected_date = idx.date()
                elif isinstance(idx, date):
                    detected_date = idx
                else:
                    detected_date = pd.Timestamp(idx).date()

                changepoints.append(ChangePoint(
                    detected_date=detected_date,
                    signal_series=series_name,
                    cusum_value=float(cusum_value),
                    is_significant=True,
                ))

                # Reset CUSUM dopo rilevazione per evitare trigger multipli
                cusum_pos = 0.0
                cusum_neg = 0.0

        log.info(
            "cusum.detected",
            series=series_name,
            n_changepoints=len(changepoints),
            threshold=round(threshold_abs, 4),
        )
        return changepoints

    def detect_on_regime_probs(self, regime_df: pd.DataFrame) -> list[ChangePoint]:
        """Applica CUSUM sulla serie di probabilità del regime dominante.

        Args:
            regime_df: DataFrame con colonne snapshot_date e prob_* o regime_label.
                       Si aspetta colonna 'prob_expansion' o simile.

        Returns:
            Lista di ChangePoint sui cambi di probabilità dominante.
        """
        if regime_df.empty:
            return []

        # Identifica la colonna di probabilità dominante per ogni riga
        prob_cols = [c for c in regime_df.columns if c.startswith("prob_")]
        if not prob_cols:
            log.warning("cusum.no_prob_columns", cols=list(regime_df.columns))
            return []

        # Usa la probabilità massima come "confidence del regime dominante"
        if "snapshot_date" in regime_df.columns:
            df = regime_df.set_index("snapshot_date")
        else:
            df = regime_df.copy()

        # Serie della probabilità massima (confidence nel regime corrente)
        max_prob = df[prob_cols].max(axis=1)
        max_prob.index = pd.to_datetime(max_prob.index)

        all_changepoints: list[ChangePoint] = []
        for col in prob_cols:
            regime_name = col.replace("prob_", "")
            series = df[col].copy()
            series.index = pd.to_datetime(series.index)
            cps = self.cusum_detect(series, series_name=f"regime_prob_{regime_name}")
            all_changepoints.extend(cps)

        return all_changepoints
