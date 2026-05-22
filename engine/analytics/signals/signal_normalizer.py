"""Signal Normalizer — cross-sectional + time-series z-scoring."""
from __future__ import annotations

import numpy as np
import pandas as pd

from shared.logger import get_logger

log = get_logger(__name__)

CLIP_SIGMA: float = 3.0        # Clip outliers a ±3σ
MIN_STD_THRESHOLD: float = 1e-9  # Evita divisione per zero


class SignalNormalizer:
    """Normalizza segnali in z-score cross-sectional o time-series."""

    CLIP_SIGMA: float = CLIP_SIGMA

    def cross_sectional_zscore(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Z-score cross-sectional per ogni timestamp (riga).

        Per ogni riga (timestamp), calcola la media e std tra tutti i segnali
        (colonne) e normalizza. Utile per confrontare segnali in uno stesso
        universo di asset.

        Args:
            signals: DataFrame con colonne=signal_ids, index=timestamp.

        Returns:
            DataFrame normalizzato con stessa forma dell'input.
        """
        if signals.empty:
            return signals.copy()

        row_mean = signals.mean(axis=1)
        row_std = signals.std(axis=1, ddof=1)

        # Evita divisione per zero su righe con std = 0
        row_std = row_std.replace(0.0, float("nan"))
        row_std = row_std.where(row_std > MIN_STD_THRESHOLD, other=float("nan"))

        normalized = signals.sub(row_mean, axis=0).div(row_std, axis=0)

        log.debug(
            "signal_normalizer.cross_sectional_zscore",
            n_rows=len(signals),
            n_cols=len(signals.columns),
        )
        return normalized

    def time_series_zscore(self, signal: pd.Series, window: int = 252) -> pd.Series:
        """Z-score rolling per una singola serie temporale.

        Calcola la media e deviazione standard rolling e normalizza il valore
        corrente rispetto alla finestra storica.

        Args:
            signal: Serie temporale del segnale.
            window: Finestra rolling in periodi (default: 252 giorni lavorativi).

        Returns:
            Serie z-scored con stesso indice dell'input.
        """
        if signal.empty:
            return signal.copy()

        rolling_mean = signal.rolling(window=window, min_periods=max(2, window // 10)).mean()
        rolling_std = signal.rolling(window=window, min_periods=max(2, window // 10)).std(ddof=1)

        # Sostituisce std = 0 con NaN per evitare inf
        rolling_std = rolling_std.where(rolling_std > MIN_STD_THRESHOLD, other=float("nan"))

        zscored = (signal - rolling_mean) / rolling_std

        log.debug(
            "signal_normalizer.time_series_zscore",
            n_obs=len(signal),
            window=window,
            non_null=int(zscored.notna().sum()),
        )
        return zscored

    def clip_outliers(self, signal: pd.Series) -> pd.Series:
        """Clipping a ±CLIP_SIGMA sigma.

        Calcola media e std della serie e clippa i valori estremi.
        Utile da applicare dopo la normalizzazione.

        Args:
            signal: Serie temporale.

        Returns:
            Serie con outlier clippati a ±CLIP_SIGMA * std dalla media.
        """
        if signal.empty or signal.dropna().empty:
            return signal.copy()

        mean = float(signal.mean())
        std = float(signal.std(ddof=1))

        if std < MIN_STD_THRESHOLD:
            return signal.copy()

        lower = mean - self.CLIP_SIGMA * std
        upper = mean + self.CLIP_SIGMA * std

        clipped = signal.clip(lower=lower, upper=upper)

        n_clipped = int((signal < lower).sum() + (signal > upper).sum())
        if n_clipped > 0:
            log.debug(
                "signal_normalizer.clip_outliers",
                n_clipped=n_clipped,
                lower=round(lower, 4),
                upper=round(upper, 4),
            )
        return clipped

    def normalize_to_unit_interval(self, signal: pd.Series) -> pd.Series:
        """Normalizza in [-1, 1] tramite tanh.

        La funzione tanh comprime i valori in (-1, 1) mantenendo la
        monotonicità. Utile come output layer per segnali combinati.

        Args:
            signal: Serie temporale (idealmente già z-scored).

        Returns:
            Serie con valori in (-1, 1).
        """
        if signal.empty:
            return signal.copy()

        normalized = np.tanh(signal)
        result = pd.Series(normalized, index=signal.index, name=signal.name)

        log.debug(
            "signal_normalizer.normalize_to_unit_interval",
            n_obs=len(signal),
            value_range=(
                round(float(result.min()), 4),
                round(float(result.max()), 4),
            ),
        )
        return result
