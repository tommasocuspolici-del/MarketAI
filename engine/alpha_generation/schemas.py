"""Dataclass schemas for the alpha_generation engine module.

All output types are frozen dataclasses (immutable after construction).
Regola 3: type hints completi su tutto.
Regola 8: scores numerici usano float (np.float64 nei calcoli interni).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


class ClaimsRegime(StrEnum):
    """Regime del mercato del lavoro dedotto da Claims/CPI cross."""
    GOLDILOCKS  = "goldilocks"   # Claims basse + CPI moderato → ottimale
    STAGFLATION = "stagflation"  # Claims ↑ + CPI > 3% → worst case
    OVERHEATING = "overheating"  # Claims bassissime + CPI > 4% → Fed hawkish
    RECESSION   = "recession"    # Claims ↑↑ + CPI basso → recessione
    NEUTRAL     = "neutral"      # Nessun segnale netto


class CreditStressLevel(StrEnum):
    """Livello di stress sui mercati del credito (HY OAS + TED + NFCI)."""
    LOW      = "low"       # HY OAS < 350 bps → nessuno stress
    MODERATE = "moderate"  # HY OAS 350-500 bps → stress contenuto
    ELEVATED = "elevated"  # HY OAS 500-700 bps → rischio crescente
    CRISIS   = "crisis"    # HY OAS > 700 bps → mercati sotto pressione


class CurveRegime(StrEnum):
    """Forma della curva dei tassi (spread 10Y-2Y come discriminante principale)."""
    STEEP    = "steep"    # Spread > +150 bps → espansione attesa
    NORMAL   = "normal"   # Spread 0-150 bps → ciclo neutro
    FLAT     = "flat"     # Spread -50-0 bps → late cycle
    INVERTED = "inverted" # Spread < -50 bps → segnale recessione


@dataclass(frozen=True)
class ClaimsInflationOutput:
    """Output del ClaimsInflationCrossAnalyzer.

    Attributes:
        regime:             Regime claims/CPI classificato.
        regime_score:       Contributo numerico a macro_score [-1, +1].
        icsa_4wk_ma:        Media mobile 4 settimane Initial Claims.
        icsa_yoy_pct:       Variazione YoY claims (None se storia < 52 settimane).
        cpi_yoy:            CPI variazione YoY più recente.
        stagflation_signal: True se claims ↑ e CPI > 3%.
        goldilocks_signal:  True se claims basse e CPI moderato.
        overheating_signal: True se claims bassissime e CPI > 4%.
        recession_watch:    True se claims ↑↑ e CPI basso.
    """
    regime:             ClaimsRegime
    regime_score:       float          # [-1, +1]
    icsa_4wk_ma:        float
    icsa_yoy_pct:       float | None
    cpi_yoy:            float | None
    stagflation_signal: bool
    goldilocks_signal:  bool
    overheating_signal: bool
    recession_watch:    bool


@dataclass(frozen=True)
class YieldCurveOutput:
    """Output del YieldCurveAnalyzer.

    Attributes:
        curve_regime:       Forma della curva yield.
        regime_score:       Contributo numerico a macro_score [-1, +1].
        recession_prob_12m: Probabilità recessione a 12 mesi (Estrella-Mishkin 1996).
        spread_10y_2y:      Spread 10Y-2Y (None se serie non disponibile nel DB).
        spread_10y_3m:      Spread 10Y-3M — input primario Estrella-Mishkin.
        y_10y:              Rendimento Treasury 10Y.
        breakeven_10y:      Breakeven inflation 10Y (TIPS).
        inversion_detected: True se spread_10y_2y < 0.
    """
    curve_regime:       CurveRegime
    regime_score:       float          # [-1, +1]
    recession_prob_12m: float | None
    spread_10y_2y:      float | None
    spread_10y_3m:      float | None
    y_10y:              float | None
    breakeven_10y:      float | None
    inversion_detected: bool


@dataclass(frozen=True)
class CreditStressOutput:
    """Output del CreditStressAnalyzer.

    Attributes:
        stress_level:  Livello di stress (LOW/MODERATE/ELEVATED/CRISIS).
        stress_score:  Contributo numerico a macro_score [-1, +1].
        hy_oas:        ICE BofA HY OAS in bps (BAMLH0A0HYM2).
        ig_oas:        ICE BofA IG OAS in bps (BAMLC0A0CM).
        hy_ig_ratio:   HY/IG spread ratio (misura del risk premium relativo).
        ted_spread:    TED spread in bps (liquidità interbancaria).
        nfci:          Chicago Fed NFCI (negative = condizioni accomodanti).
    """
    stress_level: CreditStressLevel
    stress_score: float                # [-1, +1]
    hy_oas:       float | None
    ig_oas:       float | None
    hy_ig_ratio:  float | None
    ted_spread:   float | None
    nfci:         float | None


@dataclass(frozen=True)
class MacroConvictionResult:
    """Output aggregato del MacroConvictionCalculator (15 serie FRED).

    Attributes:
        macro_score:        Score composito in [-1, +1].
                            +1 = macro molto favorevole (BUY).
                            -1 = macro molto sfavorevole (REDUCE).
        confidence:         'HIGH' | 'MEDIUM' | 'LOW' in base al num. di serie disponibili.
        computed_at:        Timestamp UTC del calcolo.
        claims_output:      Dettaglio sub-modulo Claims/Inflation.
        yield_output:       Dettaglio sub-modulo Yield Curve.
        credit_output:      Dettaglio sub-modulo Credit Stress.
        labour_score:       Punteggio categoria lavoro [-1, +1] (peso 25%).
        inflation_score:    Punteggio categoria inflazione [-1, +1] (peso 20%).
        rates_score:        Punteggio categoria tassi [-1, +1] (peso 20%).
        credit_score:       Punteggio categoria credito [-1, +1] (peso 20%).
        growth_score:       Punteggio categoria crescita [-1, +1] (peso 15%).
        series_available:   Quante delle 15 serie erano presenti nel DB.
        series_required:    Minimo di serie richieste per confidence HIGH (default 10).
        weight_breakdown:   Dict con i pesi effettivi usati per ogni categoria.
    """
    macro_score:       float
    confidence:        str             # 'HIGH' | 'MEDIUM' | 'LOW'
    computed_at:       datetime
    claims_output:     ClaimsInflationOutput
    yield_output:      YieldCurveOutput
    credit_output:     CreditStressOutput
    labour_score:      float
    inflation_score:   float
    rates_score:       float
    credit_score:      float
    growth_score:      float
    series_available:  int
    series_required:   int             = 10
    weight_breakdown:  dict[str, float] = field(default_factory=dict)
    is_degraded:       bool            = False

    @classmethod
    def degraded(cls, sources_failed: list[str] | None = None) -> MacroConvictionResult:
        """Costruisce un risultato sentinel quando il calcolo non è possibile."""
        _claims = ClaimsInflationOutput(
            regime=ClaimsRegime.NEUTRAL, regime_score=0.0,
            icsa_4wk_ma=0.0, icsa_yoy_pct=None, cpi_yoy=None,
            stagflation_signal=False, goldilocks_signal=False,
            overheating_signal=False, recession_watch=False,
        )
        _yield = YieldCurveOutput(
            curve_regime=CurveRegime.NORMAL, regime_score=0.0,
            recession_prob_12m=None, spread_10y_2y=None, spread_10y_3m=None,
            y_10y=None, breakeven_10y=None, inversion_detected=False,
        )
        _credit = CreditStressOutput(
            stress_level=CreditStressLevel.LOW, stress_score=0.0,
            hy_oas=None, ig_oas=None, hy_ig_ratio=None, ted_spread=None, nfci=None,
        )
        return cls(
            macro_score=0.0,
            confidence="LOW",
            computed_at=datetime.now(timezone.utc),
            claims_output=_claims,
            yield_output=_yield,
            credit_output=_credit,
            labour_score=0.0,
            inflation_score=0.0,
            rates_score=0.0,
            credit_score=0.0,
            growth_score=0.0,
            series_available=0,
            is_degraded=True,
        )
