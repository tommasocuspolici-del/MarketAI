"""VixSignalCalculator — Settimana 4 Roadmap Unificata.

Calcola il segnale VIX (timing signal) con adjustment per il regime HMM corrente.

Logica:
  Il VIX misura la volatilità implicita delle opzioni S&P 500 a 30 giorni.
  Un VIX molto alto = paura di mercato elevata = segnale contrarian BUY.
  Un VIX molto basso = compiacenza = segnale di cautela.

  Z-Score del VIX rispetto alla sua distribuzione storica:
    Z > soglia  → panico → segnale BUY
    Z < -soglia → euforia → segnale REDUCE
    Altrimenti  → HOLD

  Regime adjustment (da Roadmap Unificata §Settimana 4):
    bull:       +0.5  (soglia più alta — servono segnali più forti per tradare)
    transition:  0.0  (nessun aggiustamento)
    bear:       -0.3  (soglia più bassa — segnali deboli contano di più)
    stress:     -0.5  (massima sensitivity — ogni segnale viene amplificato)

  VIX/VXV ratio (term structure):
    < 1.0 → backwardation (panico immediato > atteso) → conferma segnale BUY
    > 1.0 → contango (stress atteso > immediato) → struttura normale

Regola 2 (SRP): solo segnale VIX — non fa macro o credit.
Regola 8: numpy per tutti i calcoli.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np

from shared.logger import get_logger

__version__ = "1.0.0"
__all__ = ["VixSignal", "VixSignalCalculator"]

log = get_logger(__name__)

# Soglia base Z-Score per segnale
_BASE_ZSCORE_THRESHOLD = 1.5

# Adjustment per regime HMM
_REGIME_ADJUSTMENTS: dict[str, float] = {
    "bull":       +0.5,
    "transition":  0.0,
    "bear":       -0.3,
    "stress":     -0.5,
}

# Classificazione regime VIX (livello assoluto)
_VIX_CALM        = 15.0
_VIX_ELEVATED    = 20.0
_VIX_HIGH_STRESS = 30.0
# > 30 → panic


@dataclass(frozen=True)
class VixSignal:
    """Output del VixSignalCalculator.

    Attributes:
        computed_at:       Timestamp UTC del calcolo.
        vix_level:         Valore VIX corrente.
        vix_zscore:        Z-Score rispetto a lookback giorni.
        vix_pct_rank:      Percentile rank [0, 1] nel lookback.
        vix_vxv_ratio:     VIX / VXV (term structure ratio), None se VXV non disponibile.
        spike_detected:    True se Z-Score > 2.0.
        vix_regime:        'calm' | 'elevated' | 'high_stress' | 'panic'.
        zscore_signal:     'buy' | 'sell' | 'hold' (raw, prima del regime adjustment).
        action:            'BUY' | 'HOLD' | 'REDUCE' (finale, post regime adjustment).
        vix_signal_score:  [0, 1] intensità segnale BUY (0 = no signal, 1 = max).
        confidence:        'HIGH' | 'MEDIUM' | 'LOW'.
        regime_used:       Regime HMM usato per il threshold adjustment.
        threshold_used:    Soglia Z-Score effettiva dopo aggiustamento.
        lookback_bars:     Numero di barre usate per il calcolo dello Z-Score.
    """
    computed_at:      datetime
    vix_level:        float
    vix_zscore:       float
    vix_pct_rank:     float
    vix_vxv_ratio:    float | None
    spike_detected:   bool
    vix_regime:       str
    zscore_signal:    str
    action:           str
    vix_signal_score: float
    confidence:       str
    regime_used:      str | None
    threshold_used:   float
    lookback_bars:    int


class VixSignalCalculator:
    """Calcola il segnale VIX regime-aware dal DB dei prezzi.

    Legge ^VIX (e opzionalmente ^VXV) da DuckDB via PricesRepository.
    Non fa fetch API — i dati vengono aggiornati dallo scheduler.

    Usage::

        calc = VixSignalCalculator(prices_repo=get_prices_repository())
        signal = calc.compute(current_regime="bear")
    """

    def __init__(
        self,
        prices_repo: Any,  # PricesRepository — injected at runtime
        lookback_days: int = 252,
    ) -> None:
        self._repo      = prices_repo
        self._lookback  = lookback_days

    def compute(self, current_regime: str | None = None) -> VixSignal:
        """Calcola il segnale VIX con regime adjustment.

        Args:
            current_regime: Regime HMM corrente ('bull'|'bear'|'transition'|'stress').
                            None → nessun aggiustamento (usa threshold base).

        Returns:
            VixSignal con action e score.

        Raises:
            ValueError: Se ^VIX non ha dati sufficienti nel DB.
        """
        from shared.types import TimeFrame

        # Leggi prezzi VIX
        vix_df = self._repo.read_prices(
            ticker="^VIX", timeframe=TimeFrame.D1,
        )
        if vix_df is None or vix_df.empty or len(vix_df) < 20:
            raise ValueError("^VIX: dati insufficienti nel DB (< 20 barre)")

        closes = vix_df["close"].dropna().to_numpy(dtype=np.float64)
        # Usa al massimo lookback_days barre
        closes = closes[-self._lookback:]

        current_vix = float(closes[-1])
        mu  = float(np.mean(closes))
        std = float(np.std(closes, ddof=1))
        zscore = float((current_vix - mu) / std) if std > 0 else 0.0

        # Percentile rank
        pct_rank = float(np.mean(closes <= current_vix))

        # VIX/VXV ratio (opzionale)
        vix_vxv_ratio = self._compute_vxv_ratio(current_vix)

        # Spike detection
        spike = zscore > 2.0

        # Regime del VIX (valore assoluto)
        vix_regime = _classify_vix_regime(current_vix)

        # Threshold con regime adjustment
        regime_adj = _REGIME_ADJUSTMENTS.get(current_regime or "transition", 0.0)
        threshold  = _BASE_ZSCORE_THRESHOLD + regime_adj

        # Segnale raw (pre-adjustment)
        if zscore > _BASE_ZSCORE_THRESHOLD:
            zscore_signal = "buy"
        elif zscore < -_BASE_ZSCORE_THRESHOLD * 0.7:
            zscore_signal = "sell"
        else:
            zscore_signal = "hold"

        # Azione finale (post regime adjustment)
        if zscore > threshold:
            action = "BUY"
            # Normalizza [threshold, threshold*3] → [0, 1]
            raw_score = (zscore - threshold) / max(threshold, 0.5)
            vix_signal_score = float(min(1.0, raw_score))
        elif zscore < -(threshold * 0.7):
            action = "REDUCE"
            vix_signal_score = 0.0
        else:
            action = "HOLD"
            # Score proporzionale a quanto ci si avvicina alla soglia
            vix_signal_score = float(max(0.0, zscore / threshold)) if threshold > 0 else 0.0

        # Confidence basata su numero di barre disponibili
        if len(closes) >= 200:
            confidence = "HIGH"
        elif len(closes) >= 60:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        now = datetime.now(UTC)

        log.info(
            "vix_signal.computed",
            vix=round(current_vix, 2),
            zscore=round(zscore, 3),
            action=action,
            regime=current_regime,
            threshold=round(threshold, 2),
            vix_regime=vix_regime,
            score=round(vix_signal_score, 3),
        )

        return VixSignal(
            computed_at=now,
            vix_level=current_vix,
            vix_zscore=zscore,
            vix_pct_rank=pct_rank,
            vix_vxv_ratio=vix_vxv_ratio,
            spike_detected=spike,
            vix_regime=vix_regime,
            zscore_signal=zscore_signal,
            action=action,
            vix_signal_score=vix_signal_score,
            confidence=confidence,
            regime_used=current_regime,
            threshold_used=threshold,
            lookback_bars=len(closes),
        )

    def _compute_vxv_ratio(self, current_vix: float) -> float | None:
        """Calcola il ratio VIX/VXV per la term structure.

        VXV = volatilità implicita 3 mesi (ticker: ^VXV su yfinance).
        ratio < 1 → backwardation (stress immediato > lungo termine).
        ratio > 1 → contango (struttura normale).
        """
        from shared.types import TimeFrame
        try:
            vxv_df = self._repo.read_prices(
                    ticker="^VXV", timeframe=TimeFrame.D1)
            if vxv_df is None or vxv_df.empty:
                return None
            vxv_close = float(vxv_df["close"].dropna().iloc[-1])
            if vxv_close <= 0:
                return None
            return float(current_vix / vxv_close)
        except Exception:
            return None


# ─── Helpers puri ────────────────────────────────────────────────────────────

def _classify_vix_regime(vix: float) -> str:
    """Classifica il VIX per livello assoluto."""
    if vix < _VIX_CALM:
        return "calm"
    if vix < _VIX_ELEVATED:
        return "elevated"
    if vix < _VIX_HIGH_STRESS:
        return "high_stress"
    return "panic"
