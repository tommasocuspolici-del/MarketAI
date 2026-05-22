"""Benjamini-Hochberg FDR Correction per multiple testing."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from shared.logger import get_logger

log = get_logger(__name__)

DEFAULT_FDR_ALPHA: float = 0.05


@dataclass
class FDRResult:
    strategy_ids: list[str]
    p_values: list[float]
    adjusted_p_values: list[float]
    rejected: list[bool]    # True = strategia significativa (sopravvive FDR)
    n_significant: int
    fdr_alpha: float


def fdr_benjamini_hochberg(
    strategy_ids: list[str],
    p_values: list[float],
    alpha: float = DEFAULT_FDR_ALPHA,
) -> FDRResult:
    """Applica correzione Benjamini-Hochberg alle p-value di N strategie.

    Procedura BH:
    1. Ordina le p-value in ordine crescente: p_(1) ≤ p_(2) ≤ ... ≤ p_(m)
    2. Calcola soglia per ogni rank k: soglia_k = k/m * alpha
    3. Trova il massimo k* tale che p_(k*) ≤ k*/m * alpha
    4. Rifiuta tutte le ipotesi con rank ≤ k* (H0 rifiutata = strategia significativa)

    Args:
        strategy_ids: Identificatori delle strategie.
        p_values:     P-value corrispondenti (stessa lunghezza di strategy_ids).
        alpha:        Livello FDR desiderato (default 0.05).

    Returns:
        FDRResult con p-value aggiustate (BH) e vettore di rejected.

    Una strategia con `rejected=True` = H0 rifiutata = risultato statisticamente
    significativo dopo correzione per test multipli.
    """
    if len(strategy_ids) != len(p_values):
        raise ValueError(
            f"strategy_ids and p_values must have same length, "
            f"got {len(strategy_ids)} vs {len(p_values)}"
        )

    m = len(p_values)
    if m == 0:
        return FDRResult(
            strategy_ids=[],
            p_values=[],
            adjusted_p_values=[],
            rejected=[],
            n_significant=0,
            fdr_alpha=alpha,
        )

    p_arr = np.asarray(p_values, dtype=float)

    # Ordina per p-value crescente; mantieni mapping agli indici originali
    sort_idx = np.argsort(p_arr)
    ranks = np.arange(1, m + 1, dtype=float)  # 1-based

    # Soglie BH: k/m * alpha
    bh_thresholds = ranks / m * alpha

    # Trova k_hat: massimo rank k tale che p_(k) ≤ k/m * alpha
    sorted_p = p_arr[sort_idx]
    satisfies = sorted_p <= bh_thresholds

    if satisfies.any():
        k_hat = int(np.max(np.where(satisfies)[0])) + 1  # 1-based
    else:
        k_hat = 0  # nessuna ipotesi rifiutata

    # Rejected: tutti i rank ≤ k_hat
    rejected_sorted = np.arange(1, m + 1) <= k_hat

    # P-value aggiustate BH (metodo Benjamini-Yekutieli classico: step-up)
    # adj_p_(k) = min(p_(j) * m/j) per j da k a m, poi clippa a 1
    adj_p_sorted = np.minimum.accumulate((p_arr[sort_idx] * m / ranks)[::-1])[::-1]
    adj_p_sorted = np.minimum(adj_p_sorted, 1.0)

    # Riporta all'ordine originale
    adj_p = np.empty(m)
    rejected = np.zeros(m, dtype=bool)
    adj_p[sort_idx] = adj_p_sorted
    rejected[sort_idx] = rejected_sorted

    n_significant = int(rejected.sum())

    log.info(
        "fdr.benjamini_hochberg",
        m=m,
        k_hat=k_hat,
        n_significant=n_significant,
        alpha=alpha,
    )

    return FDRResult(
        strategy_ids=list(strategy_ids),
        p_values=list(p_values),
        adjusted_p_values=adj_p.tolist(),
        rejected=rejected.tolist(),
        n_significant=n_significant,
        fdr_alpha=alpha,
    )
