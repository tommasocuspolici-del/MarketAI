"""Tail Hedge Advisor — suggerisce coperture per scenari di tail risk.

Basato su regime di volatilità corrente e CVaR del portafoglio,
suggerisce strumenti di copertura (put OTM, inverse ETF, VIX call).

Feature flag: tail_hedge_advisor (default: false).
"""
from __future__ import annotations
from dataclasses import dataclass
from shared.logger import get_logger
from shared.feature_flags import is_enabled

log = get_logger(__name__)

FEATURE_FLAG = "tail_hedge_advisor"

@dataclass
class HedgeRecommendation:
    instrument: str           # es. "SPY put OTM 5%", "SH (inverse S&P)", "VIX call"
    rationale: str
    estimated_cost_pct: float  # % del portafoglio
    protection_level: str     # "partial" | "substantial" | "full"
    regime_trigger: str       # regime che ha attivato la raccomandazione

class TailHedgeAdvisor:
    """Suggerisce strumenti di copertura per tail risk.

    Logica:
    - CVaR_blended_95 > 0.15 (15%): raccomanda protezione
    - Vol regime "high" o "extreme": priorità put OTM e VIX call
    - Vol regime "calm" o "normal": copertura leggera (collar o put spread)
    """

    CVAR_THRESHOLD: float = 0.15

    def recommend(
        self,
        cvar_blended_95: float,
        vol_regime: str,           # calm|normal|high|extreme
        portfolio_value_usd: float,
        current_regime: str = "expansion",
    ) -> list[HedgeRecommendation]:
        """Restituisce lista di raccomandazioni hedge ordinate per priorità."""
        if not is_enabled(FEATURE_FLAG):
            log.debug("tail_hedge_advisor.disabled")
            return []

        recommendations: list[HedgeRecommendation] = []

        if (cvar_blended_95 < self.CVAR_THRESHOLD
                and vol_regime in ("calm", "normal")
                and current_regime not in ("contraction", "stress")):
            return recommendations

        if vol_regime in ("high", "extreme"):
            recommendations.append(HedgeRecommendation(
                instrument="SPY put OTM 5%",
                rationale=f"Vol regime {vol_regime}: protezione downside immediata",
                estimated_cost_pct=0.5,
                protection_level="substantial",
                regime_trigger=vol_regime,
            ))
            recommendations.append(HedgeRecommendation(
                instrument="VIX call 25-strike",
                rationale="Copertura spike volatilità in regime ad alto stress",
                estimated_cost_pct=0.3,
                protection_level="partial",
                regime_trigger=vol_regime,
            ))

        if current_regime == "contraction" or cvar_blended_95 > self.CVAR_THRESHOLD:
            recommendations.append(HedgeRecommendation(
                instrument="SH (ProShares Short S&P500)",
                rationale=f"CVaR={cvar_blended_95:.1%} > soglia; regime {current_regime}",
                estimated_cost_pct=2.0,
                protection_level="substantial",
                regime_trigger=current_regime,
            ))

        if vol_regime == "normal" and cvar_blended_95 > self.CVAR_THRESHOLD:
            recommendations.append(HedgeRecommendation(
                instrument="SPY collar (sell call OTM 5%, buy put OTM 5%)",
                rationale="Copertura a basso costo netto in regime normale",
                estimated_cost_pct=0.1,
                protection_level="partial",
                regime_trigger=vol_regime,
            ))

        log.info(
            "tail_hedge_advisor.recommended",
            n=len(recommendations),
            cvar=round(cvar_blended_95, 3),
            vol_regime=vol_regime,
        )
        return recommendations
