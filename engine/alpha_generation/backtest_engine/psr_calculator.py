"""Probabilistic Sharpe Ratio (Bailey & López de Prado, 2012) — Convenzione PSR."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

MIN_SAMPLES: int = 30
DEFAULT_BENCHMARK: float = 0.0
PERIODS_YEAR_DAILY: int = 252


@dataclass
class PSRResult:
    observed_sharpe: float
    psr: float                # in [0, 1]
    is_significant: bool      # PSR > 0.90
    skewness: float
    excess_kurtosis: float
    n_samples: int


def probabilistic_sharpe_ratio(
    returns: np.ndarray,
    sr_benchmark: float = DEFAULT_BENCHMARK,
    periods_per_year: int = PERIODS_YEAR_DAILY,
) -> PSRResult:
    """Calcola il Probabilistic Sharpe Ratio secondo Bailey & López de Prado (2012).

    Il PSR stima la probabilità che lo Sharpe Ratio osservato sia superiore a un
    benchmark `sr_benchmark`, tenendo conto di skewness ed excess kurtosis.

    Formula:
        SR* = (SR_obs - SR_bench) * sqrt(n - 1) / sqrt(1 - skew*SR_obs + (kurt-1)/4 * SR_obs^2)
        PSR = Phi(SR*)

    Args:
        returns:         Array di rendimenti (non annualizzati).
        sr_benchmark:    Sharpe Ratio benchmark (default = 0).
        periods_per_year: Fattore di annualizzazione (default 252 per dati giornalieri).

    Returns:
        PSRResult con tutti i campi calcolati.
    """
    returns = np.asarray(returns, dtype=float)
    n = len(returns)

    # Calcola statistiche di base
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1))

    if sigma <= 0.0 or n < MIN_SAMPLES:
        # Non abbastanza dati o rendimenti costanti: PSR indefinito
        sr_obs = float(mu / sigma) if sigma > 0.0 else 0.0
        return PSRResult(
            observed_sharpe=sr_obs * np.sqrt(periods_per_year),
            psr=0.5,
            is_significant=False,
            skewness=0.0,
            excess_kurtosis=0.0,
            n_samples=n,
        )

    # Sharpe Ratio osservato (periodico, non annualizzato)
    sr_obs_periodic = mu / sigma

    # Skewness ed excess kurtosis dei rendimenti
    skew = float(stats.skew(returns))
    ex_kurt = float(stats.kurtosis(returns))  # scipy restituisce excess kurtosis

    # Numeratore: (SR_obs - SR_bench) * sqrt(n - 1)
    # Nota: il benchmark deve essere periodico per confrontarlo con sr_obs_periodic
    sr_bench_periodic = sr_benchmark / np.sqrt(periods_per_year) if periods_per_year > 0 else sr_benchmark
    numerator = (sr_obs_periodic - sr_bench_periodic) * np.sqrt(n - 1)

    # Denominatore: sqrt(1 - skew * SR_obs + (kurt-1)/4 * SR_obs^2)
    # Dove kurt = excess kurtosis + 3 → (kurt-1) = excess kurtosis + 2
    term_skew = skew * sr_obs_periodic
    term_kurt = ((ex_kurt + 2.0) / 4.0) * (sr_obs_periodic ** 2)
    denom_sq = 1.0 - term_skew + term_kurt

    if denom_sq <= 0.0:
        # Caso degenere: imposta PSR = 0.5
        psr = 0.5
    else:
        z_stat = numerator / np.sqrt(denom_sq)
        psr = float(stats.norm.cdf(z_stat))

    # Sharpe annualizzato per reporting
    sr_annualized = sr_obs_periodic * np.sqrt(periods_per_year)

    return PSRResult(
        observed_sharpe=sr_annualized,
        psr=min(max(psr, 0.0), 1.0),  # clamp in [0, 1]
        is_significant=psr > 0.90,
        skewness=skew,
        excess_kurtosis=ex_kurt,
        n_samples=n,
    )
