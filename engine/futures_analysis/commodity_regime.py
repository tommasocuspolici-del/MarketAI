"""CommodityRegimeClassifier — Settimana 5 Roadmap Unificata.

Aggrega roll_yield, basis e OI in un regime commodity e un score numerico
per il composite signal dell'engine.

Matrice di classificazione:
  ┌──────────────────┬───────────────┬───────────────┬─────────────────────┐
  │ Term Structure   │ OI Signal     │ Basis Signal  │ Regime              │
  ├──────────────────┼───────────────┼───────────────┼─────────────────────┤
  │ BACKWARDATION    │ TREND_BULLISH │ qualsiasi     │ BACKWARDATION_SQUEEZE│
  │ BACKWARDATION    │ SHORTCOVERING │ qualsiasi     │ BULLISH             │
  │ CONTANGO         │ DISTRIBUTION  │ divergence    │ CONTANGO_TRAP       │
  │ FLAT/CONTANGO    │ DISTRIBUTION  │ qualsiasi     │ BEARISH             │
  │ qualsiasi        │ LIQUIDATION   │ qualsiasi     │ BULLISH (exhaustion)│
  │ qualsiasi        │ altri         │ qualsiasi     │ NEUTRAL             │
  └──────────────────┴───────────────┴───────────────┴─────────────────────┘

Score numerico [-1, +1] per il composite signal (Settimana 8):
  BACKWARDATION_SQUEEZE: +0.8  (segnale più forte)
  BULLISH:               +0.5
  NEUTRAL:                0.0
  BEARISH:               -0.5
  CONTANGO_TRAP:         -0.7

Regola 2 (SRP): aggrega roll/basis/OI — non implementa nessuno dei tre.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np

from engine.futures_analysis.schemas import (
    BasisResult,
    CommodityAnalysis,
    CommodityRegime,
    OISignal,
    OpenInterestResult,
    RollYieldResult,
    TermStructure,
)
from shared.logger import get_logger

if TYPE_CHECKING:
    from engine.futures_analysis.basis_analyzer import BasisAnalyzer
    from engine.futures_analysis.open_interest_analyzer import OpenInterestAnalyzer
    from engine.futures_analysis.roll_analyzer import RollAnalyzer
    pass

__version__ = "1.0.0"
__all__ = ["CommodityRegimeClassifier"]

log = get_logger(__name__)

# Score per ogni regime
_REGIME_SCORES: dict[CommodityRegime, float] = {
    CommodityRegime.BACKWARDATION_SQUEEZE:  0.8,
    CommodityRegime.BULLISH:                0.5,
    CommodityRegime.NEUTRAL:                0.0,
    CommodityRegime.BEARISH:               -0.5,
    CommodityRegime.CONTANGO_TRAP:         -0.7,
}


class CommodityRegimeClassifier:
    """Classifica il regime commodity aggregando roll, basis e OI.

    Usato dal composite signal aggregator (Settimana 8) per includere
    le commodity nel macro_score via peso aggiuntivo.

    Usage::

        classifier = CommodityRegimeClassifier(
            roll_analyzer=roll_analyzer,
            basis_analyzer=basis_analyzer,
            oi_analyzer=oi_analyzer,
        )
        analysis = classifier.classify("CL=F")
    """

    def __init__(
        self,
        roll_analyzer: RollAnalyzer,
        basis_analyzer: BasisAnalyzer,
        oi_analyzer: OpenInterestAnalyzer,
    ) -> None:
        self._roll  = roll_analyzer
        self._basis = basis_analyzer
        self._oi    = oi_analyzer

    def classify(self, ticker: str) -> CommodityAnalysis:
        """Classifica il regime commodity per un ticker.

        Args:
            ticker: Simbolo futures (es. 'CL=F', 'GC=F').

        Returns:
            CommodityAnalysis con regime, score e sub-output.
        """
        # Calcola i tre sub-segnali
        roll_result:  RollYieldResult | None  = None
        basis_result: BasisResult | None      = None
        oi_result:    OpenInterestResult | None = None

        try:
            roll_result = self._roll.analyze(ticker)
        except Exception as exc:
            log.warning("commodity_classifier.roll_failed",
                        ticker=ticker, error=str(exc)[:80])

        try:
            basis_result = self._basis.analyze(ticker)
        except Exception as exc:
            log.warning("commodity_classifier.basis_failed",
                        ticker=ticker, error=str(exc)[:80])

        try:
            oi_result = self._oi.analyze(ticker)
        except Exception as exc:
            log.warning("commodity_classifier.oi_failed",
                        ticker=ticker, error=str(exc)[:80])

        # Classificazione regime
        regime = _classify_regime(roll_result, basis_result, oi_result)
        score  = float(np.clip(_REGIME_SCORES.get(regime, 0.0), -1.0, 1.0))

        # Confidence: dipende da quanti segnali erano disponibili
        n_available = sum(1 for r in [roll_result, basis_result, oi_result]
                          if r is not None)
        confidence = "HIGH" if n_available == 3 else ("MEDIUM" if n_available >= 2 else "LOW")

        # Fallback per sub-output mancanti (per output sempre completo)
        if roll_result is None:
            roll_result = _null_roll(ticker)
        if basis_result is None:
            basis_result = _null_basis(ticker)
        if oi_result is None:
            oi_result = _null_oi(ticker)

        summary = _build_summary(ticker, regime, score, roll_result, basis_result, oi_result)

        log.info(
            "commodity_classifier.done",
            ticker=ticker,
            regime=regime.value,
            score=round(score, 3),
            confidence=confidence,
            n_signals=n_available,
        )

        return CommodityAnalysis(
            ticker=ticker,
            computed_at=datetime.now(UTC),
            regime=regime,
            score=score,
            roll_result=roll_result,
            basis_result=basis_result,
            oi_result=oi_result,
            confidence=confidence,
            summary=summary,
        )

    def classify_from_results(
        self,
        ticker:       str,
        roll_result:  RollYieldResult,
        basis_result: BasisResult,
        oi_result:    OpenInterestResult,
    ) -> CommodityAnalysis:
        """Classifica da sub-risultati già calcolati (per test senza DB)."""
        regime = _classify_regime(roll_result, basis_result, oi_result)
        score  = float(np.clip(_REGIME_SCORES.get(regime, 0.0), -1.0, 1.0))
        confidence = "HIGH"
        summary = _build_summary(ticker, regime, score, roll_result, basis_result, oi_result)

        return CommodityAnalysis(
            ticker=ticker,
            computed_at=datetime.now(UTC),
            regime=regime, score=score,
            roll_result=roll_result, basis_result=basis_result,
            oi_result=oi_result, confidence=confidence, summary=summary,
        )


# ─── Funzioni pure di classificazione ────────────────────────────────────────

def _classify_regime(
    roll:  RollYieldResult | None,
    basis: BasisResult | None,
    oi:    OpenInterestResult | None,
) -> CommodityRegime:
    """Classifica il regime da combinazione dei tre segnali."""
    ts     = roll.term_structure    if roll  else None
    oi_sig = oi.oi_signal           if oi    else None
    b_sig  = basis.signal           if basis else None

    # Backwardation + trend confermato OI → squeeze (segnale più forte)
    if (ts == TermStructure.BACKWARDATION and
            oi_sig == OISignal.TREND_CONFIRMED_BULLISH):
        return CommodityRegime.BACKWARDATION_SQUEEZE

    # Contango profondo + distribuzione OI + divergenza basis → trappola
    if (ts == TermStructure.CONTANGO and
            oi_sig == OISignal.DISTRIBUTION_BEARISH and
            b_sig == "divergence"):
        return CommodityRegime.CONTANGO_TRAP

    # Backwardation + short covering (debole) → bullish
    if (ts == TermStructure.BACKWARDATION and
            oi_sig in (OISignal.SHORT_COVERING_WEAK_BUY, OISignal.INSUFFICIENT_DATA)):
        return CommodityRegime.BULLISH

    # Liquidazione + prezzi in discesa → possibile bottom (bullish contrarian)
    if oi_sig == OISignal.LIQUIDATION_POSSIBLE_BTM:
        return CommodityRegime.BULLISH

    # Distribuzione OI + trend ribassista
    if oi_sig == OISignal.DISTRIBUTION_BEARISH:
        return CommodityRegime.BEARISH

    # Solo term structure (OI non disponibile)
    if ts == TermStructure.BACKWARDATION:
        return CommodityRegime.BULLISH
    if ts == TermStructure.CONTANGO:
        return CommodityRegime.BEARISH

    return CommodityRegime.NEUTRAL


def _build_summary(
    ticker: str, regime: CommodityRegime, score: float,
    roll: RollYieldResult, basis: BasisResult, oi: OpenInterestResult,
) -> str:
    ts_str = roll.term_structure.value if roll else "N/D"
    oi_str = oi.oi_signal.value if oi else "N/D"
    b_str  = basis.signal if basis else "N/D"
    return (
        f"{ticker} {regime.value} (score={score:+.2f}) | "
        f"term={ts_str} | OI={oi_str} | basis={b_str}"
    )


# ─── Fallback null objects ────────────────────────────────────────────────────

def _null_roll(ticker: str) -> RollYieldResult:
    from engine.futures_analysis.schemas import TermStructure
    return RollYieldResult(
        ticker=ticker, computed_at=datetime.now(UTC),
        roll_yield_22d=0.0, roll_yield_annual=0.0,
        term_structure=TermStructure.FLAT, front_close=0.0,
        second_proxy=0.0, roll_pct_rank=None, signal="neutral",
    )


def _null_basis(ticker: str) -> BasisResult:
    return BasisResult(
        ticker=ticker, spot_ticker="N/A",
        computed_at=datetime.now(UTC),
        basis=None, basis_pct=None, basis_zscore=None, signal="neutral",
    )


def _null_oi(ticker: str) -> OpenInterestResult:
    return OpenInterestResult(
        ticker=ticker, computed_at=datetime.now(UTC),
        oi_signal=OISignal.INSUFFICIENT_DATA, oi_current=None,
        oi_change_pct=None, price_change_pct=None,
        oi_pct_rank=None, institutional_bias="neutral",
    )
