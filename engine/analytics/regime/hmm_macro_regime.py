"""HMM Macro Regime — 4 stati su 12 variabili osservate (Convenzione HMM v2).

Usa hmmlearn se disponibile; altrimenti cade in un classificatore rule-based
basato su percentili delle feature chiave (VIX, yield curve, NFCI).
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from shared.logger import get_logger
from shared.exceptions import AnalysisError

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

log = get_logger(__name__)

# ── Costanti ──────────────────────────────────────────────────────────────────
CONFIDENCE_THRESHOLD: float = 0.80
MIN_PROB_FLOOR: float = 0.01       # Probabilità minima per evitare collasso numerico
_HMM_AVAILABLE: bool = False

try:
    from hmmlearn import hmm as _hmmlearn_hmm  # type: ignore[import-untyped]
    _HMM_AVAILABLE = True
    log.info("hmm_macro_regime.hmmlearn_available")
except ImportError:
    log.warning("hmm_macro_regime.hmmlearn_not_available", fallback="rule_based_classifier")


class RegimeState(str, Enum):
    EXPANSION    = "expansion"
    SLOWDOWN     = "slowdown"
    CONTRACTION  = "contraction"
    RECOVERY     = "recovery"


@dataclass
class RegimeOutput:
    current_regime: RegimeState
    prob_expansion:   float
    prob_slowdown:    float
    prob_contraction: float
    prob_recovery:    float
    confidence:       float    # max(prob_i)
    model_version:    str


REGIME_FEATURE_COLUMNS: list[str] = [
    "INDPRO_MOM", "RSAFS_MOM", "PAYEMS_MOM", "NAPM",
    "T10Y3M", "BAMLH0A0HYM2", "NFCI", "VIX_LEVEL",
    "CPIAUCSL_YOY", "UNRATE", "JTSJOL_LEVEL", "OECD_CLI_US",
]

# Mapping state index → RegimeState (ordine basato su interpretazione economica)
_STATE_MAP: dict[int, RegimeState] = {
    0: RegimeState.EXPANSION,
    1: RegimeState.SLOWDOWN,
    2: RegimeState.CONTRACTION,
    3: RegimeState.RECOVERY,
}


class HMMRegimeModel:
    """HMM Gaussiano 4 stati su 12 variabili macro.

    Se hmmlearn non è disponibile, usa un classificatore rule-based basato
    su percentili delle variabili chiave.
    """

    N_STATES: int = 4
    N_ITER: int = 200
    MIN_SAMPLES: int = 36   # 3 anni mensili minimi per training

    def __init__(self) -> None:
        self._model: object | None = None
        self._scaler_mean: np.ndarray | None = None
        self._scaler_std: np.ndarray | None = None
        self._fitted: bool = False
        self._model_version: str = "rule_based_v1.0" if not _HMM_AVAILABLE else "hmm_v2.0"

    def _normalize(self, features: pd.DataFrame) -> np.ndarray:
        """Standardizza le feature (z-score). Usa mean/std del training se fitted."""
        X = features.reindex(columns=REGIME_FEATURE_COLUMNS).fillna(0.0).values.astype(float)
        if self._scaler_mean is not None and self._scaler_std is not None:
            std_safe = np.where(self._scaler_std > 1e-9, self._scaler_std, 1.0)
            return (X - self._scaler_mean) / std_safe
        mean = X.mean(axis=0)
        std = X.std(axis=0, ddof=1)
        std_safe = np.where(std > 1e-9, std, 1.0)
        return (X - mean) / std_safe

    def fit(self, features: pd.DataFrame) -> "HMMRegimeModel":
        """Addestra HMM su features normalizzate. Richiede hmmlearn.

        Args:
            features: DataFrame con colonne REGIME_FEATURE_COLUMNS, index=date.
                      Almeno MIN_SAMPLES righe richieste.

        Returns:
            self (per chaining).

        Raises:
            ValueError: Se il numero di campioni è insufficiente.
        """
        if len(features) < self.MIN_SAMPLES:
            raise AnalysisError(
                f"Insufficient samples for HMM training: {len(features)} < {self.MIN_SAMPLES}"
            )

        X = features.reindex(columns=REGIME_FEATURE_COLUMNS).fillna(0.0).values.astype(float)

        # Salva parametri di normalizzazione
        self._scaler_mean = X.mean(axis=0)
        self._scaler_std = X.std(axis=0, ddof=1)
        X_norm = self._normalize(features)

        if _HMM_AVAILABLE:
            model = _hmmlearn_hmm.GaussianHMM(
                n_components=self.N_STATES,
                covariance_type="diag",
                n_iter=self.N_ITER,
                random_state=42,
            )
            model.fit(X_norm)
            self._model = model
            self._model_version = "hmm_v2.0"
            log.info("hmm_macro_regime.fitted", n_samples=len(features), n_states=self.N_STATES)
        else:
            # Rule-based: calcola percentili per classificazione
            self._rule_percentiles = np.percentile(X_norm, [25, 50, 75], axis=0)
            self._model_version = "rule_based_v1.0"
            log.info("hmm_macro_regime.fitted_rule_based", n_samples=len(features))

        self._fitted = True
        return self

    def _rule_based_classify(self, x_norm: np.ndarray) -> np.ndarray:
        """Classificatore rule-based basato su VIX, yield curve, NFCI.

        Restituisce un array di probabilità [expansion, slowdown, contraction, recovery].
        Usa colonne: T10Y3M (idx 4), NFCI (idx 6), VIX_LEVEL (idx 7).
        """
        # Indici delle feature chiave
        T10Y3M_IDX = 4
        NFCI_IDX = 6
        VIX_IDX = 7
        INDPRO_IDX = 0
        PAYEMS_IDX = 2

        probs_list: list[np.ndarray] = []

        for row in x_norm:
            vix = row[VIX_IDX] if len(row) > VIX_IDX else 0.0
            nfci = row[NFCI_IDX] if len(row) > NFCI_IDX else 0.0
            yc = row[T10Y3M_IDX] if len(row) > T10Y3M_IDX else 0.0
            indpro = row[INDPRO_IDX] if len(row) > INDPRO_IDX else 0.0
            payems = row[PAYEMS_IDX] if len(row) > PAYEMS_IDX else 0.0

            # Score euristici per ogni regime
            # Expansion: crescita forte, VIX basso, yield curve positiva
            p_exp = float(np.clip(0.5 + 0.15 * indpro + 0.10 * payems - 0.10 * vix + 0.10 * yc, 0.05, 0.90))
            # Slowdown: crescita in rallentamento
            p_slow = float(np.clip(0.25 - 0.05 * indpro + 0.05 * vix - 0.05 * yc, 0.05, 0.90))
            # Contraction: VIX alto, NFCI stressato, yield curve invertita
            p_contr = float(np.clip(0.15 + 0.15 * vix + 0.10 * nfci - 0.10 * yc - 0.05 * payems, 0.05, 0.90))
            # Recovery: dopo contrazione, crescita riprende
            p_rec = float(np.clip(0.10 + 0.05 * indpro - 0.05 * vix + 0.05 * payems, 0.05, 0.90))

            raw = np.array([p_exp, p_slow, p_contr, p_rec])
            probs = raw / raw.sum()
            probs_list.append(probs)

        return np.array(probs_list)

    def predict(self, features: pd.DataFrame) -> list[RegimeOutput]:
        """Predice il regime per ogni riga del DataFrame.

        Args:
            features: DataFrame con colonne REGIME_FEATURE_COLUMNS.

        Returns:
            Lista di RegimeOutput, uno per riga.
        """
        X_norm = self._normalize(features)

        if _HMM_AVAILABLE and self._fitted and self._model is not None:
            probs_matrix = self._model.predict_proba(X_norm)  # type: ignore[union-attr]
        else:
            probs_matrix = self._rule_based_classify(X_norm)

        outputs: list[RegimeOutput] = []
        for probs in probs_matrix:
            # Clip floor per evitare probabilità nulle
            probs = np.maximum(probs, MIN_PROB_FLOOR)
            probs = probs / probs.sum()

            state_idx = int(np.argmax(probs))
            regime = self.label_regime(state_idx, probs)
            confidence = float(np.max(probs))

            outputs.append(RegimeOutput(
                current_regime=regime,
                prob_expansion=float(probs[0]),
                prob_slowdown=float(probs[1]),
                prob_contraction=float(probs[2]),
                prob_recovery=float(probs[3]),
                confidence=confidence,
                model_version=self._model_version,
            ))

        return outputs

    def predict_current(self, latest_features: pd.DataFrame) -> RegimeOutput:
        """Predice il regime corrente dall'ultima riga delle feature.

        Args:
            latest_features: DataFrame con almeno una riga.

        Returns:
            RegimeOutput per il periodo più recente.
        """
        if latest_features.empty:
            log.warning("hmm_macro_regime.predict_current_empty_input")
            return RegimeOutput(
                current_regime=RegimeState.SLOWDOWN,
                prob_expansion=0.25,
                prob_slowdown=0.25,
                prob_contraction=0.25,
                prob_recovery=0.25,
                confidence=0.25,
                model_version=self._model_version,
            )

        outputs = self.predict(latest_features.tail(1))
        return outputs[0]

    def label_regime(self, state_idx: int, probs: np.ndarray) -> RegimeState:
        """Mappa un indice di stato HMM al RegimeState semantico.

        Args:
            state_idx: Indice dello stato HMM (0-3).
            probs: Array di probabilità per tutti gli stati.

        Returns:
            RegimeState corrispondente.
        """
        return _STATE_MAP.get(state_idx % self.N_STATES, RegimeState.SLOWDOWN)

    def is_fitted(self) -> bool:
        """Restituisce True se il modello è stato addestrato."""
        return self._fitted

    def save(self, path: str) -> None:
        """Serializza il modello in un file pickle.

        Args:
            path: Percorso del file di output.
        """
        payload = {
            "model": self._model,
            "scaler_mean": self._scaler_mean,
            "scaler_std": self._scaler_std,
            "fitted": self._fitted,
            "model_version": self._model_version,
        }
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        log.info("hmm_macro_regime.saved", path=path)

    def load(self, path: str) -> "HMMRegimeModel":
        """Carica un modello serializzato da file pickle.

        Args:
            path: Percorso del file salvato con save().

        Returns:
            self (modello caricato).
        """
        with open(path, "rb") as f:
            payload = pickle.load(f)  # noqa: S301  # trusted internal file

        self._model = payload.get("model")
        self._scaler_mean = payload.get("scaler_mean")
        self._scaler_std = payload.get("scaler_std")
        self._fitted = payload.get("fitted", False)
        self._model_version = payload.get("model_version", "unknown")
        log.info("hmm_macro_regime.loaded", path=path, model_version=self._model_version)
        return self
