"""Signal Combiner — ensemble con pesi adattativi."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from shared.logger import get_logger

log = get_logger(__name__)

MIN_IC_WEIGHT: float = 1e-9  # Evita pesi negativi o nulli
RIDGE_MIN_SAMPLES: int = 30  # Minimo campioni per ridge regression


@dataclass
class CombinedSignal:
    value: float            # Segnale aggregato [-1, 1]
    weights_used: dict[str, float]
    n_signals: int
    confidence: float       # media dei |IC| ponderata


class SignalCombiner:
    """Combina N segnali con pesi basati su IC rolling."""

    def combine(
        self,
        signals: dict[str, float],         # signal_id → value
        weights: dict[str, float] | None,  # None → equal weight
    ) -> CombinedSignal:
        """Combina segnali con i pesi specificati (o equal weight se None).

        Args:
            signals: Dizionario {signal_id: valore segnale}.
            weights: Dizionario {signal_id: peso} normalizzati a somma=1,
                     oppure None per equal weighting.

        Returns:
            CombinedSignal con valore aggregato e metadati.
        """
        if not signals:
            log.warning("signal_combiner.empty_signals")
            return CombinedSignal(
                value=0.0,
                weights_used={},
                n_signals=0,
                confidence=0.0,
            )

        signal_ids = list(signals.keys())
        n = len(signal_ids)

        if weights is None:
            # Equal weighting
            w = {sid: 1.0 / n for sid in signal_ids}
        else:
            # Normalizza i pesi forniti
            total = sum(abs(weights.get(sid, 0.0)) for sid in signal_ids)
            if total < MIN_IC_WEIGHT:
                w = {sid: 1.0 / n for sid in signal_ids}
                log.warning("signal_combiner.zero_weights_fallback_equal")
            else:
                w = {sid: abs(weights.get(sid, 0.0)) / total for sid in signal_ids}

        # Calcolo segnale combinato
        combined_value = sum(w[sid] * signals[sid] for sid in signal_ids)

        # Confidence: media pesata dei |valori| come proxy (in assenza di IC espliciti)
        confidence = sum(w[sid] * abs(signals[sid]) for sid in signal_ids)

        log.info(
            "signal_combiner.combined",
            n_signals=n,
            combined_value=round(combined_value, 4),
            confidence=round(confidence, 4),
        )

        return CombinedSignal(
            value=float(np.tanh(combined_value)),  # schiaccia in (-1, 1)
            weights_used=w,
            n_signals=n,
            confidence=float(confidence),
        )

    def ic_proportional_weights(
        self,
        ic_scores: dict[str, float],   # signal_id → IC_mean
    ) -> dict[str, float]:
        """Pesi proporzionali all'IC medio, normalizzati a somma=1.

        I segnali con IC negativo o nullo ricevono peso 0. I pesi sono
        proporzionali al valore assoluto dell'IC (solo IC > 0).

        Args:
            ic_scores: Dizionario {signal_id: IC_mean}.

        Returns:
            Dizionario {signal_id: peso} normalizzato a somma=1.
        """
        if not ic_scores:
            return {}

        # Prendi solo IC positivi
        positive = {sid: ic for sid, ic in ic_scores.items() if ic > 0}

        if not positive:
            # Fallback: equal weight su tutti
            n = len(ic_scores)
            return {sid: 1.0 / n for sid in ic_scores}

        total = sum(positive.values())
        weights = {sid: ic / total for sid, ic in positive.items()}

        # Segnali con IC ≤ 0 ricevono peso 0
        for sid in ic_scores:
            if sid not in weights:
                weights[sid] = 0.0

        return weights

    def ridge_oos_weights(
        self,
        signal_history: pd.DataFrame,   # colonne=signal_ids, index=date
        return_history: pd.Series,       # forward returns allineati
        alpha: float = 1.0,
    ) -> dict[str, float]:
        """Pesi ottimizzati via Ridge Regression out-of-sample.

        Stima i pesi del modello lineare y = X @ w + eps con
        regolarizzazione L2 (Ridge). I pesi negativi sono clippati a 0
        e normalizzati a somma=1.

        Args:
            signal_history: DataFrame con segnali storici.
            return_history: Serie di rendimenti forward allineati.
            alpha: Parametro di regolarizzazione Ridge (default: 1.0).

        Returns:
            Dizionario {signal_id: peso} normalizzato a somma=1.
        """
        signal_ids = list(signal_history.columns)

        # Allineamento e pulizia
        aligned = pd.concat(
            [signal_history, return_history.rename("_ret")], axis=1
        ).dropna()

        if len(aligned) < RIDGE_MIN_SAMPLES:
            log.warning(
                "signal_combiner.ridge_insufficient_data",
                n_samples=len(aligned),
                min_required=RIDGE_MIN_SAMPLES,
            )
            n = len(signal_ids)
            return {sid: 1.0 / n for sid in signal_ids}

        X = aligned[signal_ids].values
        y = aligned["_ret"].values

        try:
            # Ridge: w = (X'X + alpha*I)^{-1} X'y
            n_features = X.shape[1]
            XtX = X.T @ X
            Xty = X.T @ y
            ridge_matrix = XtX + alpha * np.eye(n_features)
            raw_weights = np.linalg.solve(ridge_matrix, Xty)

            # Clip pesi negativi a 0 e normalizza
            clipped = np.maximum(raw_weights, 0.0)
            total = float(clipped.sum())

            if total < MIN_IC_WEIGHT:
                log.warning("signal_combiner.ridge_all_negative_fallback_equal")
                n = len(signal_ids)
                return {sid: 1.0 / n for sid in signal_ids}

            normalized_weights = clipped / total
            weights = {sid: float(normalized_weights[i]) for i, sid in enumerate(signal_ids)}

            log.info(
                "signal_combiner.ridge_weights",
                n_signals=n_features,
                n_samples=len(aligned),
                alpha=alpha,
            )
            return weights

        except (np.linalg.LinAlgError, ValueError) as exc:
            log.warning("signal_combiner.ridge_failed", error=str(exc))
            n = len(signal_ids)
            return {sid: 1.0 / n for sid in signal_ids}
