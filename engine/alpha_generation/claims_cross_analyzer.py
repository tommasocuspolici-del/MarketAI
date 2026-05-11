"""ClaimsInflationCrossAnalyzer — Settimana 3 Roadmap Unificata.

Analizza il cross tra Initial Claims (ICSA) e CPI per classificare il regime
macro corrente in quattro stati: goldilocks, stagflation, overheating, recession.

Serie FRED usate:
  ICSA     — Initial Jobless Claims (settimanale)
  CCSA     — Continued Claims (settimanale, opzionale per conferma)
  CPIAUCSL — CPI All Urban Consumers (mensile)

Regola 2 (SRP): questo modulo fa solo claims/inflation cross detection.
Regola 8: calcoli con numpy.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import numpy as np

from engine.alpha_generation.schemas import ClaimsInflationOutput, ClaimsRegime
from shared.logger import get_logger

if TYPE_CHECKING:
    import pandas as pd

__version__ = "1.0.0"
__all__ = ["ClaimsInflationCrossAnalyzer"]

log = get_logger(__name__)

# Soglie calibrate su dati storici 2000-2024
_CLAIMS_LOW_THRESHOLD  = 300_000   # < 300k → labour market forte
_CLAIMS_VERY_LOW       = 250_000   # < 250k → overheating risk
_CLAIMS_HIGH_YOY       = 0.10      # > +10% YoY → labour deteriorating
_CLAIMS_VERY_HIGH_YOY  = 0.20      # > +20% YoY → recession signal
_CPI_MODERATE_HIGH     = 3.5       # > 3.5% → above target
_CPI_HIGH              = 4.0       # > 4.0% → Fed hawkish territory
_CPI_STAGFLATION       = 3.0       # > 3.0% + claims rising → stagflation
_CPI_LOW               = 2.5       # < 2.5% → disinflation/deflation risk


class ClaimsInflationCrossAnalyzer:
    """Classifica il regime macro corrente dal cross Claims/Inflation.

    Legge i DataFrame direttamente (già letti da MacroConvictionCalculator)
    per evitare accessi DB duplicati — Rule 2 (SRP).

    Usage::

        analyzer = ClaimsInflationCrossAnalyzer()
        output = analyzer.analyze(icsa_df=icsa_df, cpi_df=cpi_df)
    """

    def analyze(
        self,
        icsa_df:  pd.DataFrame,
        cpi_df:   pd.DataFrame,
        ccsa_df:  pd.DataFrame | None = None,
    ) -> ClaimsInflationOutput:
        """Classifica il regime Claims/Inflation corrente.

        Args:
            icsa_df:  DataFrame con colonne ['ts', 'value'] per ICSA.
            cpi_df:   DataFrame con colonne ['ts', 'value'] per CPIAUCSL.
            ccsa_df:  DataFrame opzionale per CCSA (Continued Claims).

        Returns:
            ClaimsInflationOutput con regime e score.
        """
        icsa_vals = _extract_series(icsa_df)
        cpi_vals  = _extract_series(cpi_df)

        if len(icsa_vals) < 4:
            log.warning("claims_analyzer.insufficient_icsa", rows=len(icsa_vals))
            return _neutral_output(icsa_vals, cpi_vals)

        # 4-week moving average (riduce rumore settimanale)
        icsa_4wk_ma = float(np.mean(icsa_vals[-4:]))

        # YoY change (52 settimane = ~1 anno)
        icsa_yoy: float | None = None
        if len(icsa_vals) >= 53:
            prev_year = float(icsa_vals[-53])
            if prev_year > 0:
                icsa_yoy = (icsa_4wk_ma - prev_year) / prev_year

        # CPI YoY più recente
        cpi_yoy: float | None = None
        if cpi_vals.size != 0:
            cpi_yoy = float(cpi_vals[-1])

        # Opzionale: CCSA come conferma claims
        if ccsa_df is not None:
            ccsa_vals = _extract_series(ccsa_df)
            if len(ccsa_vals) >= 4:
                ccsa_trend = float(ccsa_vals[-1]) - float(ccsa_vals[-4])
                # Trend CCSA positivo (claims in salita) rafforza segnali negativi
                _ccsa_rising = ccsa_trend > 50_000
            else:
                _ccsa_rising = False
        else:
            _ccsa_rising = False

        # Classificazione regime (priorità: stagflation > goldilocks > overheating > recession)
        stagflation = (
            (icsa_yoy is not None and icsa_yoy > _CLAIMS_HIGH_YOY) and
            (cpi_yoy is not None and cpi_yoy > _CPI_STAGFLATION)
        )
        goldilocks = (
            icsa_4wk_ma < _CLAIMS_LOW_THRESHOLD and
            (cpi_yoy is not None and cpi_yoy < _CPI_MODERATE_HIGH) and
            not stagflation
        )
        overheating = (
            icsa_4wk_ma < _CLAIMS_VERY_LOW and
            (cpi_yoy is not None and cpi_yoy > _CPI_HIGH) and
            not stagflation
        )
        recession_watch = (
            (icsa_yoy is not None and icsa_yoy > _CLAIMS_VERY_HIGH_YOY) and
            (cpi_yoy is not None and cpi_yoy < _CPI_LOW) and
            not stagflation
        )

        # Score e regime finali
        if stagflation:
            regime = ClaimsRegime.STAGFLATION
            score  = -1.0
        elif goldilocks:
            regime = ClaimsRegime.GOLDILOCKS
            # Score più alto se CPI è ben sotto target
            score = 0.8 if (cpi_yoy is not None and cpi_yoy < 2.5) else 0.6
        elif overheating:
            regime = ClaimsRegime.OVERHEATING
            score  = -0.3  # labour forte ma Fed costretta ad alzare
        elif recession_watch:
            regime = ClaimsRegime.RECESSION
            score  = -0.6
        else:
            regime = ClaimsRegime.NEUTRAL
            # Score positivo se claims stabili/basse, negativo se YoY > 5%
            if icsa_yoy is not None and icsa_yoy > 0.05:
                score = -0.2
            elif icsa_4wk_ma < _CLAIMS_LOW_THRESHOLD:
                score = 0.2
            else:
                score = 0.0

        # Clip per sicurezza
        score = float(np.clip(score, -1.0, 1.0))

        log.info(
            "claims_analyzer.done",
            regime=regime.value, score=round(score, 3),
            icsa_4wk_ma=round(icsa_4wk_ma),
            icsa_yoy=round(icsa_yoy * 100, 1) if icsa_yoy else None,
            cpi_yoy=round(cpi_yoy, 2) if cpi_yoy else None,
        )

        return ClaimsInflationOutput(
            regime=regime,
            regime_score=score,
            icsa_4wk_ma=icsa_4wk_ma,
            icsa_yoy_pct=icsa_yoy,
            cpi_yoy=cpi_yoy,
            stagflation_signal=stagflation,
            goldilocks_signal=goldilocks,
            overheating_signal=overheating,
            recession_watch=recession_watch,
        )


# ─── Helpers privati ─────────────────────────────────────────────────────────

def _extract_series(df: pd.DataFrame) -> np.ndarray[Any, np.dtype[np.float64]]:
    """Estrae i valori numerici non-NaN ordinati per data."""
    if df is None or df.empty:
        return np.array([], dtype=np.float64)
    col = "value" if "value" in df.columns else df.columns[-1]
    return cast('np.ndarray[Any, np.dtype[np.float64]]', df[col].dropna().to_numpy(dtype=np.float64))


def _neutral_output(
    icsa_vals: np.ndarray[Any, np.dtype[np.float64]],
    cpi_vals: np.ndarray[Any, np.dtype[np.float64]],
) -> ClaimsInflationOutput:
    """Output neutro di fallback quando i dati sono insufficienti."""
    return ClaimsInflationOutput(
        regime=ClaimsRegime.NEUTRAL,
        regime_score=0.0,
        icsa_4wk_ma=float(icsa_vals[-1]) if len(icsa_vals) > 0 else 0.0,
        icsa_yoy_pct=None,
        cpi_yoy=float(cpi_vals[-1]) if len(cpi_vals) > 0 else None,
        stagflation_signal=False,
        goldilocks_signal=False,
        overheating_signal=False,
        recession_watch=False,
    )
