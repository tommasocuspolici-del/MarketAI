"""Options Strategy Scanner — suggerisce strategie per regime vol + outlook.

Mappa regime × outlook → lista di strategie ordinate per adeguatezza.
Ogni strategia include descrizione, max profit/loss, breakeven e livello di rischio.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from shared.logger import get_logger

__version__ = "11.0.0"

__all__ = ["OptionsStrategyScanner", "StrategyRecommendation", "MarketOutlook"]

log = get_logger(__name__)


class MarketOutlook(str, Enum):
    """Outlook direzionale di mercato."""

    BEARISH  = "bearish"
    NEUTRAL  = "neutral"
    BULLISH  = "bullish"


@dataclass
class StrategyRecommendation:
    """Raccomandazione per una strategia opzioni."""

    strategy_name: str
    description: str
    max_profit: str
    max_loss: str
    breakeven: str
    ideal_regime: str
    ideal_outlook: str
    risk_level: str   # low|medium|high


STRATEGY_MATRIX: dict[tuple[str, str], list[str]] = {
    ("calm",    "bullish"):  ["covered_call", "bull_call_spread", "naked_call"],
    ("calm",    "neutral"):  ["iron_condor", "covered_call", "short_strangle"],
    ("calm",    "bearish"):  ["protective_put", "bear_put_spread", "collar"],
    ("normal",  "bullish"):  ["bull_call_spread", "cash_secured_put"],
    ("normal",  "neutral"):  ["iron_condor", "butterfly"],
    ("normal",  "bearish"):  ["bear_put_spread", "long_put"],
    ("high",    "bullish"):  ["bull_put_spread"],
    ("high",    "neutral"):  ["long_straddle", "iron_butterfly"],
    ("high",    "bearish"):  ["long_put", "bear_call_spread", "long_straddle"],
    ("extreme", "bullish"):  ["cash_secured_put"],
    ("extreme", "neutral"):  ["long_strangle", "long_straddle"],
    ("extreme", "bearish"):  ["long_put", "protective_put"],
}

# Catalogo strategie con dettagli
STRATEGY_CATALOG: dict[str, dict[str, str]] = {
    "covered_call": {
        "description": "Detieni il sottostante, vendi una call OTM per incassare premio.",
        "max_profit": "Premium incassato + apprezzamento fino allo strike",
        "max_loss": "Costo del sottostante meno il premio incassato",
        "breakeven": "Prezzo acquisto sottostante − premio incassato",
        "ideal_regime": "calm",
        "ideal_outlook": "neutral/bullish",
        "risk_level": "low",
    },
    "bull_call_spread": {
        "description": "Acquista call ATM, vendi call OTM. Capped upside, ridotto costo.",
        "max_profit": "Differenza strike − premio netto pagato",
        "max_loss": "Premio netto pagato",
        "breakeven": "Strike basso + premio netto",
        "ideal_regime": "calm/normal",
        "ideal_outlook": "bullish",
        "risk_level": "low",
    },
    "naked_call": {
        "description": "Vendi call scoperta. Massimo profitto = premio. Rischio illimitato.",
        "max_profit": "Premio incassato",
        "max_loss": "Illimitato",
        "breakeven": "Strike + premio incassato",
        "ideal_regime": "calm",
        "ideal_outlook": "bearish/neutral",
        "risk_level": "high",
    },
    "iron_condor": {
        "description": "Vendi strangle OTM, acquista strangle più OTM. Profitto in range.",
        "max_profit": "Premio netto incassato",
        "max_loss": "Differenza strike − premio netto",
        "breakeven": "Due punti: strike call venduta + premio e strike put venduta − premio",
        "ideal_regime": "calm/normal",
        "ideal_outlook": "neutral",
        "risk_level": "medium",
    },
    "short_strangle": {
        "description": "Vendi call e put OTM. Profitto se spot rimane in range.",
        "max_profit": "Premi incassati",
        "max_loss": "Illimitato (call) / strike put − premi (put)",
        "breakeven": "Due punti simmetrici intorno ad ATM",
        "ideal_regime": "calm",
        "ideal_outlook": "neutral",
        "risk_level": "high",
    },
    "protective_put": {
        "description": "Detieni sottostante + acquista put ATM. Assicurazione contro ribasso.",
        "max_profit": "Illimitato (meno il premio pagato)",
        "max_loss": "Strike put − spot attuale + premio pagato",
        "breakeven": "Prezzo acquisto sottostante + premio pagato",
        "ideal_regime": "calm/normal",
        "ideal_outlook": "bearish",
        "risk_level": "low",
    },
    "bear_put_spread": {
        "description": "Acquista put ATM, vendi put OTM. Capped downside profit.",
        "max_profit": "Differenza strike − premio netto pagato",
        "max_loss": "Premio netto pagato",
        "breakeven": "Strike alto − premio netto",
        "ideal_regime": "normal",
        "ideal_outlook": "bearish",
        "risk_level": "low",
    },
    "collar": {
        "description": "Protettivo: long stock + long put + short call (finanzia la put).",
        "max_profit": "Strike call − prezzo acquisto + premio netto",
        "max_loss": "Prezzo acquisto − strike put + premio netto",
        "breakeven": "Prezzo acquisto ± premi",
        "ideal_regime": "calm",
        "ideal_outlook": "neutral/bearish",
        "risk_level": "low",
    },
    "cash_secured_put": {
        "description": "Vendi put OTM con cash a garanzia. Acquisti a sconto se assegnato.",
        "max_profit": "Premio incassato",
        "max_loss": "Strike − premio incassato",
        "breakeven": "Strike − premio",
        "ideal_regime": "normal/extreme",
        "ideal_outlook": "bullish",
        "risk_level": "medium",
    },
    "long_put": {
        "description": "Acquista put per speculazione o protezione ribassista.",
        "max_profit": "Strike − premio (se spot → 0)",
        "max_loss": "Premio pagato",
        "breakeven": "Strike − premio",
        "ideal_regime": "high/extreme",
        "ideal_outlook": "bearish",
        "risk_level": "medium",
    },
    "butterfly": {
        "description": "Vendi 2 call ATM, acquista 1 call ITM + 1 call OTM. Low cost neutral.",
        "max_profit": "Differenza strike wing − premio netto (se spot = ATM a scadenza)",
        "max_loss": "Premio netto pagato",
        "breakeven": "Due punti: ITM strike + premio e OTM strike − premio",
        "ideal_regime": "normal",
        "ideal_outlook": "neutral",
        "risk_level": "low",
    },
    "bull_put_spread": {
        "description": "Vendi put ATM, acquista put OTM. Profitto se spot sale o resta stabile.",
        "max_profit": "Premio netto incassato",
        "max_loss": "Differenza strike − premio netto",
        "breakeven": "Strike alto − premio netto",
        "ideal_regime": "high",
        "ideal_outlook": "bullish",
        "risk_level": "medium",
    },
    "long_straddle": {
        "description": "Acquista call e put ATM. Profitto con forte movimento in qualsiasi direzione.",
        "max_profit": "Illimitato",
        "max_loss": "Premi pagati (se spot = strike a scadenza)",
        "breakeven": "Due punti: ATM ± premi totali",
        "ideal_regime": "high/extreme",
        "ideal_outlook": "neutral (alta volatilità attesa)",
        "risk_level": "medium",
    },
    "iron_butterfly": {
        "description": "Vendi straddle ATM, acquista strangle OTM. Massimo profitto ATM.",
        "max_profit": "Premio netto incassato",
        "max_loss": "Differenza strike wing − premio netto",
        "breakeven": "Due punti: ATM ± premio netto",
        "ideal_regime": "high",
        "ideal_outlook": "neutral",
        "risk_level": "medium",
    },
    "bear_call_spread": {
        "description": "Vendi call ATM, acquista call OTM. Profitto se spot scende o resta sotto strike.",
        "max_profit": "Premio netto incassato",
        "max_loss": "Differenza strike − premio netto",
        "breakeven": "Strike basso + premio netto",
        "ideal_regime": "high",
        "ideal_outlook": "bearish",
        "risk_level": "medium",
    },
    "long_strangle": {
        "description": "Acquista call e put OTM. Meno costoso di straddle, richiede maggior movimento.",
        "max_profit": "Illimitato",
        "max_loss": "Premi pagati totali",
        "breakeven": "Due punti: call strike + premi e put strike − premi",
        "ideal_regime": "extreme",
        "ideal_outlook": "neutral (grande movimento atteso)",
        "risk_level": "medium",
    },
}

RISK_LEVEL_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


class OptionsStrategyScanner:
    """Suggerisce strategie opzioni basate su regime vol e outlook.

    Usa la STRATEGY_MATRIX per identificare le strategie appropriate
    e le filtra per max_risk_level prima di restituirle.
    """

    def recommend(
        self,
        vol_regime: str,
        market_outlook: str,
        max_risk_level: str = "medium",
    ) -> list[StrategyRecommendation]:
        """Raccomanda strategie opzioni per il regime e outlook corrente.

        Parameters
        ----------
        vol_regime:
            Regime di volatilità: calm|normal|high|extreme.
        market_outlook:
            Outlook direzionale: bearish|neutral|bullish.
        max_risk_level:
            Livello massimo di rischio accettato: low|medium|high.
        """
        key = (vol_regime.lower(), market_outlook.lower())
        strategy_names = STRATEGY_MATRIX.get(key, [])

        if not strategy_names:
            # Fallback: usa "normal" come regime se non trovato
            log.warning(
                "options_scanner.no_strategies_for_key",
                regime=vol_regime,
                outlook=market_outlook,
            )
            key_fallback = ("normal", market_outlook.lower())
            strategy_names = STRATEGY_MATRIX.get(key_fallback, [])

        max_risk_order = RISK_LEVEL_ORDER.get(max_risk_level.lower(), 2)

        recommendations: list[StrategyRecommendation] = []
        for name in strategy_names:
            rec = self._build_recommendation(name)
            if rec is None:
                continue
            risk_order = RISK_LEVEL_ORDER.get(rec.risk_level, 2)
            if risk_order <= max_risk_order:
                recommendations.append(rec)

        log.info(
            "options_scanner.recommend",
            regime=vol_regime,
            outlook=market_outlook,
            n_strategies=len(recommendations),
        )
        return recommendations

    def _build_recommendation(self, strategy_name: str) -> StrategyRecommendation | None:
        """Costruisce StrategyRecommendation dal catalogo."""
        info = STRATEGY_CATALOG.get(strategy_name)
        if info is None:
            log.warning("options_scanner.unknown_strategy", strategy=strategy_name)
            return None

        return StrategyRecommendation(
            strategy_name=strategy_name,
            description=info["description"],
            max_profit=info["max_profit"],
            max_loss=info["max_loss"],
            breakeven=info["breakeven"],
            ideal_regime=info["ideal_regime"],
            ideal_outlook=info["ideal_outlook"],
            risk_level=info["risk_level"],
        )
