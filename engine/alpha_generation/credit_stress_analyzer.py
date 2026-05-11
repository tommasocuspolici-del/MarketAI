"""CreditStressAnalyzer — Settimana 3 Roadmap Unificata.

Classifica il livello di stress sui mercati del credito in quattro stati:
low, moderate, elevated, crisis.

Serie FRED usate:
  BAMLH0A0HYM2 — ICE BofA US High Yield OAS (bps) ← primario
  BAMLC0A0CM   — ICE BofA US Corporate IG OAS (bps)
  TEDRATE      — TED Spread (bps): liquidità interbancaria
  NFCI         — Chicago Fed National Financial Conditions Index

Regola 2 (SRP): solo classificazione stress creditizio.
Regola 8: numpy per i calcoli.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from engine.alpha_generation.schemas import CreditStressLevel, CreditStressOutput
from shared.logger import get_logger

if TYPE_CHECKING:
    import pandas as pd

__version__ = "1.0.0"
__all__ = ["CreditStressAnalyzer"]

log = get_logger(__name__)

# Soglie HY OAS calibrate su dati storici ICE BofA 2000-2024
# GFC 2008-09: peak ~1800 bps | COVID 2020: ~1100 bps | Normal: 300-400 bps
_HY_LOW_THRESHOLD      = 350   # bps: mercato creditizio sano
_HY_MODERATE_THRESHOLD = 500   # bps: stress inizia a salire
_HY_ELEVATED_THRESHOLD = 700   # bps: stress significativo (soglia sell-off)
# > 700 bps → crisis

# Soglie secondarie per override con TED e NFCI
_TED_ELEVATED    = 50    # bps: TED > 50 suggerisce stress liquidità
_TED_CRISIS      = 100   # bps: TED > 100 (GFC peak ~ 463 bps)
_NFCI_TIGHT      = 0.5   # NFCI > 0.5 → condizioni finanziarie restrittive
_NFCI_VERY_TIGHT = 1.0   # NFCI > 1.0 → molto restrittive


class CreditStressAnalyzer:
    """Classifica il livello di stress creditizio corrente.

    Usa HY OAS come indicatore primario con TED spread e NFCI come
    conferma/override per maggiore accuratezza nei periodi di transizione.

    Usage::

        analyzer = CreditStressAnalyzer()
        output = analyzer.analyze(
            hy_oas_df=hy_df, ig_oas_df=ig_df, ted_df=ted_df, nfci_df=nfci_df
        )
    """

    def analyze(
        self,
        hy_oas_df:  pd.DataFrame,
        ig_oas_df:  pd.DataFrame | None = None,
        ted_df:     pd.DataFrame | None = None,
        nfci_df:    pd.DataFrame | None = None,
    ) -> CreditStressOutput:
        """Calcola il livello di stress creditizio e il contributo al macro_score.

        Args:
            hy_oas_df:  DataFrame HY OAS (BAMLH0A0HYM2) — obbligatorio.
            ig_oas_df:  DataFrame IG OAS (BAMLC0A0CM) — opzionale.
            ted_df:     DataFrame TED Spread (TEDRATE) — opzionale.
            nfci_df:    DataFrame NFCI — opzionale.

        Returns:
            CreditStressOutput con stress_level e stress_score.
        """
        hy_oas  = _latest(hy_oas_df)
        ig_oas  = _latest(ig_oas_df)
        ted     = _latest(ted_df)
        nfci    = _latest(nfci_df)

        # HY/IG ratio: misura il risk premium relativo (spread creditizio puro)
        hy_ig_ratio: float | None = None
        if hy_oas is not None and ig_oas is not None and ig_oas > 0:
            hy_ig_ratio = hy_oas / ig_oas

        # Classificazione primaria da HY OAS
        if hy_oas is None:
            primary_level = CreditStressLevel.MODERATE  # fallback conservativo
        elif hy_oas < _HY_LOW_THRESHOLD:
            primary_level = CreditStressLevel.LOW
        elif hy_oas < _HY_MODERATE_THRESHOLD:
            primary_level = CreditStressLevel.MODERATE
        elif hy_oas < _HY_ELEVATED_THRESHOLD:
            primary_level = CreditStressLevel.ELEVATED
        else:
            primary_level = CreditStressLevel.CRISIS

        # Override con TED spread (liquidità interbancaria — segnale rapido)
        ted_override = _credit_stress_from_ted(ted)
        nfci_override = _credit_stress_from_nfci(nfci)

        # Livello finale: il peggiore tra i segnali disponibili
        # (approccio conservativo: meglio false positives che false negatives)
        all_levels = [primary_level]
        if ted_override is not None:
            all_levels.append(ted_override)
        if nfci_override is not None:
            all_levels.append(nfci_override)

        final_level = max(all_levels, key=_level_severity)

        # Score in [-1, +1]: negativo = stress (cattivo per equity/BUY)
        score = _level_to_score(final_level)

        log.info(
            "credit_stress_analyzer.done",
            stress_level=final_level.value,
            score=round(score, 3),
            hy_oas=round(hy_oas) if hy_oas else None,
            ig_oas=round(ig_oas) if ig_oas else None,
            ted=round(ted, 1) if ted else None,
            nfci=round(nfci, 3) if nfci else None,
        )

        return CreditStressOutput(
            stress_level=final_level,
            stress_score=score,
            hy_oas=hy_oas,
            ig_oas=ig_oas,
            hy_ig_ratio=hy_ig_ratio,
            ted_spread=ted,
            nfci=nfci,
        )


# ─── Helpers privati ─────────────────────────────────────────────────────────

def _latest(df: pd.DataFrame | None) -> float | None:
    if df is None or df.empty:
        return None
    col = "value" if "value" in df.columns else df.columns[-1]
    vals = df[col].dropna()
    return float(vals.iloc[-1]) if not vals.empty else None


def _credit_stress_from_ted(ted: float | None) -> CreditStressLevel | None:
    """Mappa TED spread in CreditStressLevel.

    TED spread = LIBOR 3M - T-Bill 3M: misura il risk premium interbancario.
    Normale: 10-30 bps | Stress: 50+ bps | Crisi: 100+ bps (GFC: 463 bps).
    """
    if ted is None:
        return None
    if ted < _TED_ELEVATED:
        return CreditStressLevel.LOW
    if ted < _TED_CRISIS:
        return CreditStressLevel.ELEVATED
    return CreditStressLevel.CRISIS


def _credit_stress_from_nfci(nfci: float | None) -> CreditStressLevel | None:
    """Mappa Chicago Fed NFCI in CreditStressLevel.

    NFCI > 0 → condizioni finanziarie più restrittive della media storica.
    NFCI < 0 → condizioni accomodanti.
    """
    if nfci is None:
        return None
    if nfci < 0:
        return CreditStressLevel.LOW
    if nfci < _NFCI_TIGHT:
        return CreditStressLevel.MODERATE
    if nfci < _NFCI_VERY_TIGHT:
        return CreditStressLevel.ELEVATED
    return CreditStressLevel.CRISIS


_SEVERITY_MAP: dict[CreditStressLevel, int] = {
    CreditStressLevel.LOW:      0,
    CreditStressLevel.MODERATE: 1,
    CreditStressLevel.ELEVATED: 2,
    CreditStressLevel.CRISIS:   3,
}


def _level_severity(level: CreditStressLevel) -> int:
    return _SEVERITY_MAP[level]


def _level_to_score(level: CreditStressLevel) -> float:
    """Mappa stress_level in score numerico [-1, +1]."""
    return {
        CreditStressLevel.LOW:      0.3,
        CreditStressLevel.MODERATE: 0.0,
        CreditStressLevel.ELEVATED:-0.5,
        CreditStressLevel.CRISIS:  -1.0,
    }[level]
