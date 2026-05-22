"""Vol Regime Markov Chain su stati VIX.

Stati: calm(<15) | normal(15-25) | high(25-35) | extreme(>35)
Matrice di transizione stimata su storia VIX 2000-presente.

Il modello permette di:
1. Classificare il regime corrente da VIX spot
2. Stimare la matrice di transizione da dati storici (fit)
3. Prevedere la distribuzione di probabilità del regime futuro
4. Suggerire strategie opzioni appropriate per il regime
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from shared.logger import get_logger

__version__ = "11.0.0"

__all__ = ["VolRegimeMarkov", "VolRegime", "VolRegimeState", "RegimeTransition"]

log = get_logger(__name__)

# Soglie VIX per classificazione regime
VIX_CALM_THRESHOLD: float = 15.0
VIX_NORMAL_THRESHOLD: float = 25.0
VIX_HIGH_THRESHOLD: float = 35.0

# Mediane VIX tipiche per ogni regime (per calcolo expected VIX next period)
VIX_REGIME_MEDIANS: dict[str, float] = {
    "calm": 12.0,
    "normal": 19.5,
    "high": 29.0,
    "extreme": 42.0,
}


class VolRegime(str, Enum):
    """Regime di volatilità basato su livello VIX."""

    CALM    = "calm"      # VIX < 15
    NORMAL  = "normal"   # 15 ≤ VIX < 25
    HIGH    = "high"     # 25 ≤ VIX < 35
    EXTREME = "extreme"  # VIX ≥ 35


@dataclass
class RegimeTransition:
    """Probabilità di transizione tra due regimi."""

    from_regime: VolRegime
    to_regime: VolRegime
    probability: float


@dataclass
class VolRegimeState:
    """Stato completo del regime di volatilità corrente."""

    current_regime: VolRegime
    current_vix: float
    transition_probs: dict[VolRegime, float]   # probabilità per periodo successivo
    expected_next_vix: float
    regime_strategy: str   # 'short_vol'|'neutral'|'long_vol'|'protective'


class VolRegimeMarkov:
    """Modello Markov discreto per regime di volatilità.

    La matrice di transizione di default è calibrata su dati VIX storici
    2000-2024. Può essere aggiornata con `fit()` su dati più recenti.
    """

    DEFAULT_TRANSITION: dict[str, dict[str, float]] = {
        "calm":    {"calm": 0.85, "normal": 0.13, "high": 0.02, "extreme": 0.00},
        "normal":  {"calm": 0.20, "normal": 0.65, "high": 0.14, "extreme": 0.01},
        "high":    {"calm": 0.05, "normal": 0.35, "high": 0.50, "extreme": 0.10},
        "extreme": {"calm": 0.02, "normal": 0.20, "high": 0.45, "extreme": 0.33},
    }

    REGIME_STRATEGIES: dict[str, str] = {
        "calm":    "short_vol",   # Vendi vol cara in regime tranquillo
        "normal":  "neutral",     # Strategie bilanciate
        "high":    "long_vol",    # Compra vol: opportunità di protezione
        "extreme": "protective",  # Hedging puro: priorità sulla copertura
    }

    def __init__(self) -> None:
        self._transition: dict[str, dict[str, float]] = {
            k: dict(v) for k, v in self.DEFAULT_TRANSITION.items()
        }

    def classify(self, vix: float) -> VolRegime:
        """Classifica il regime corrente in base al livello VIX."""
        if vix < VIX_CALM_THRESHOLD:
            return VolRegime.CALM
        elif vix < VIX_NORMAL_THRESHOLD:
            return VolRegime.NORMAL
        elif vix < VIX_HIGH_THRESHOLD:
            return VolRegime.HIGH
        else:
            return VolRegime.EXTREME

    def fit(self, vix_series: pd.Series) -> "VolRegimeMarkov":
        """Stima matrice di transizione da serie VIX storica.

        Conta le transizioni osservate tra regimi e normalizza per riga.
        Regimesi con meno di 5 osservazioni usano i valori di default.

        Parameters
        ----------
        vix_series:
            Serie VIX giornaliera (index=date, values=float).
        """
        vix_clean = vix_series.dropna()
        if len(vix_clean) < 2:
            log.warning("vol_regime_markov.insufficient_data_for_fit")
            return self

        regime_list = VolRegime._member_names_  # ['CALM','NORMAL','HIGH','EXTREME']
        regime_values = [r.lower() for r in regime_list]  # ['calm','normal','high','extreme']

        # Conta transizioni
        counts: dict[str, dict[str, float]] = {
            r: {r2: 0.0 for r2 in regime_values} for r in regime_values
        }

        regimes = [self.classify(float(v)).value for v in vix_clean]
        for i in range(len(regimes) - 1):
            from_r = regimes[i]
            to_r = regimes[i + 1]
            counts[from_r][to_r] += 1.0

        # Normalizza per riga — fallback su default se troppo poche osservazioni
        new_transition: dict[str, dict[str, float]] = {}
        for from_r, to_dict in counts.items():
            total = sum(to_dict.values())
            if total < 5:
                # Usa default: troppo poche osservazioni in questo regime
                new_transition[from_r] = dict(self.DEFAULT_TRANSITION[from_r])
            else:
                new_transition[from_r] = {to_r: cnt / total for to_r, cnt in to_dict.items()}

        self._transition = new_transition
        log.info(
            "vol_regime_markov.fitted",
            n_obs=len(vix_clean),
            regimes_found=list(set(regimes)),
        )
        return self

    def predict_state(self, current_vix: float) -> VolRegimeState:
        """Calcola stato corrente e distribuzione di probabilità transizioni.

        Parameters
        ----------
        current_vix:
            Livello VIX spot corrente.
        """
        current_regime = self.classify(current_vix)
        trans_row = self._transition.get(current_regime.value, {})

        # Converti in dict[VolRegime, float]
        transition_probs: dict[VolRegime, float] = {}
        for regime_str, prob in trans_row.items():
            try:
                regime_enum = VolRegime(regime_str)
                transition_probs[regime_enum] = float(prob)
            except ValueError:
                log.warning("vol_regime_markov.unknown_regime", regime=regime_str)

        # Normalizza (sicurezza)
        total_prob = sum(transition_probs.values())
        if total_prob > 1e-10:
            transition_probs = {r: p / total_prob for r, p in transition_probs.items()}

        expected_next_vix = self.expected_vix_next_period(current_regime)
        strategy = self.strategy_for_regime(current_regime)

        return VolRegimeState(
            current_regime=current_regime,
            current_vix=float(current_vix),
            transition_probs=transition_probs,
            expected_next_vix=expected_next_vix,
            regime_strategy=strategy,
        )

    def strategy_for_regime(
        self,
        regime: VolRegime,
        macro_outlook: str = "neutral",
    ) -> str:
        """Suggerisce strategia opzioni per regime corrente.

        Parameters
        ----------
        regime:
            Regime di volatilità corrente.
        macro_outlook:
            Outlook macro ('bullish'|'neutral'|'bearish'). Attualmente
            usato per logging; override futuro per strategie asimmetriche.
        """
        base_strategy = self.REGIME_STRATEGIES.get(regime.value, "neutral")
        log.debug(
            "vol_regime_markov.strategy",
            regime=regime.value,
            macro_outlook=macro_outlook,
            strategy=base_strategy,
        )
        return base_strategy

    def expected_vix_next_period(
        self,
        current_regime: VolRegime,
        vix_medians: dict[VolRegime, float] | None = None,
    ) -> float:
        """Calcola VIX atteso nel prossimo periodo.

        E[VIX_t+1] = Σ P(regime_j | regime_i) × median_VIX(j)
        """
        medians = vix_medians or {
            VolRegime(r): v for r, v in VIX_REGIME_MEDIANS.items()
        }
        trans_row = self._transition.get(current_regime.value, {})
        expected_vix = 0.0
        total_weight = 0.0
        for regime_str, prob in trans_row.items():
            try:
                regime_enum = VolRegime(regime_str)
                median = medians.get(regime_enum, 20.0)
                expected_vix += prob * median
                total_weight += prob
            except ValueError:
                continue

        if total_weight < 1e-10:
            return VIX_REGIME_MEDIANS.get(current_regime.value, 20.0)

        return expected_vix / total_weight
