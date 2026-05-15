"""Regime detector â€” identifies bull/bear/transition/stress regimes.

Uses an HMM-lite approach: K-means clustering on (return, volatility) features,
then mapping clusters to canonical regime labels by sorting on mean return.

This avoids the heavy `hmmlearn` dependency for the default path. The full HMM
implementation is available via `feature_flag.advanced_correlation`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared.exceptions import CorrelationError, InsufficientDataError
from shared.logger import get_logger

__version__ = "6.0.0"

__all__ = ["MarketRegime", "RegimeDetector", "RegimeReport"]

log = get_logger(__name__)

# Canonical labels â€” sorted from worst to best mean return
_CANONICAL_REGIMES = ("stress", "bear", "transition", "bull")


@dataclass(frozen=True, slots=True)
class MarketRegime:
    """Identified regime for a single point in time."""

    timestamp: pd.Timestamp
    label: str            # one of "bull", "bear", "transition", "stress"
    confidence: float     # softmax-like distance-based confidence in [0, 1]


@dataclass(frozen=True, slots=True)
class RegimeReport:
    """Output of RegimeDetector.run()."""

    current_regime: MarketRegime
    regime_history: list[MarketRegime]
    regime_means: dict[str, float]      # mean return per regime
    regime_vols: dict[str, float]       # vol per regime
    n_regimes: int


class RegimeDetector:
    """K-means based regime detector on (return, volatility) features.

    Defaults to 4 regimes: stress / bear / transition / bull.
    """

    MIN_OBS = 60
    MAX_ITER = 100

    def __init__(self, n_regimes: int = 4, vol_window: int = 20) -> None:
        if n_regimes not in (3, 4):
            raise CorrelationError(f"n_regimes must be 3 or 4, got {n_regimes}")
        self._n = n_regimes
        self._vol_window = vol_window

    def run(
        self, prices: pd.Series, seed: int = 42,
    ) -> RegimeReport:
        """Detect regimes from a price series."""
        if not isinstance(prices, pd.Series):
            raise CorrelationError(f"expected pd.Series, got {type(prices)}")
        if len(prices) < self.MIN_OBS:
            raise InsufficientDataError(self.MIN_OBS, len(prices))

        # Build features: log returns + rolling volatility (vectorized)
        returns = np.log(prices / prices.shift(1)).dropna()
        roll_vol = returns.rolling(self._vol_window).std().dropna()
        # Align
        rets_aligned = returns.loc[roll_vol.index]
        features = np.column_stack([rets_aligned.to_numpy(), roll_vol.to_numpy()])

        # Standardize features
        mu = features.mean(axis=0)
        std = features.std(axis=0)
        std[std == 0] = 1.0
        features_std = (features - mu) / std

        # K-means (vectorized, deterministic)
        labels, centroids = self._kmeans(features_std, self._n, seed=seed)

        # Sort regimes by mean return â€” worst (stress) to best (bull)
        regime_means_raw = {
            i: float(rets_aligned.to_numpy()[labels == i].mean())
            for i in range(self._n)
        }
        regime_vols_raw = {
            i: float(roll_vol.to_numpy()[labels == i].mean())
            for i in range(self._n)
        }
        # Order cluster IDs by mean return ascending
        ordered = sorted(regime_means_raw.items(), key=lambda kv: kv[1])
        canonical_names = (
            _CANONICAL_REGIMES if self._n == 4 else ("bear", "transition", "bull")
        )
        cluster_to_label = {
            cluster_id: canonical_names[rank]
            for rank, (cluster_id, _) in enumerate(ordered)
        }

        # Convert features back to MarketRegime objects
        # Compute confidence via inverse distance to assigned cluster
        history: list[MarketRegime] = []
        for idx, (label_id, feat) in enumerate(zip(labels, features_std, strict=True)):
            dist_to_assigned = np.linalg.norm(feat - centroids[label_id])
            other_centroids = np.delete(centroids, label_id, axis=0)
            dist_to_others = np.linalg.norm(feat - other_centroids, axis=1).min()
            # Higher dist_to_others / dist_to_assigned â†’ higher confidence
            ratio = dist_to_others / max(dist_to_assigned, 1e-9)
            confidence = float(min(1.0, max(0.0, 1.0 - 1.0 / max(ratio, 1.0))))
            history.append(MarketRegime(
                timestamp=rets_aligned.index[idx],
                label=cluster_to_label[int(label_id)],
                confidence=confidence,
            ))

        regime_means = {
            cluster_to_label[k]: v for k, v in regime_means_raw.items()
        }
        regime_vols = {
            cluster_to_label[k]: v for k, v in regime_vols_raw.items()
        }

        log.info(
            "regime.detected",
            n_regimes=self._n,
            n_obs=len(history),
            current=history[-1].label,
        )
        return RegimeReport(
            current_regime=history[-1],
            regime_history=history,
            regime_means=regime_means,
            regime_vols=regime_vols,
            n_regimes=self._n,
        )

    def _kmeans(
        self, x: np.ndarray, k: int, seed: int = 42,  # type: ignore[type-arg]
    ) -> tuple[np.ndarray, np.ndarray]:  # type: ignore[type-arg]
        """Vectorized K-means with deterministic seeding."""
        rng = np.random.default_rng(seed)
        n_obs = x.shape[0]
        # Use k-means++ style init with seeded RNG (simplified)
        idx = rng.choice(n_obs, size=k, replace=False)
        centroids = x[idx].copy()
        labels = np.zeros(n_obs, dtype=np.int64)
        for _ in range(self.MAX_ITER):
            # Assign step: nearest centroid
            dists = np.linalg.norm(
                x[:, np.newaxis, :] - centroids[np.newaxis, :, :], axis=2
            )
            new_labels = np.argmin(dists, axis=1)
            if np.array_equal(new_labels, labels):
                break
            labels = new_labels
            # Update step
            for i in range(k):
                mask = labels == i
                if mask.any():
                    centroids[i] = x[mask].mean(axis=0)
        return labels, centroids
