"""SanityCheckerV2 — Settimana 9 Hardening.

Estende il SanityChecker esistente con regole critiche per i nuovi dati
introdotti dalla Roadmap Unificata (VIX, futures, roll_yield).

Regole critiche (bloccano il calcolo):
  VIX ≤ 0 o > 100       → CRITICAL: dato impossibile
  roll_yield > 100%      → CRITICAL: dato impossibile
  spread_10y_2y > 15%    → CRITICAL: dato impossibile

Regole warning (producono avviso ma non bloccano):
  CL=F vs USO Δ > 5%    → WARN: discrepanza futures/spot ETF
  VIX spike > 50         → WARN: valore estremo ma possibile

Regola 5: eccezioni custom da shared/exceptions.py.
Regola 26: ogni serie ha DataQualityReport allegato.
"""
from __future__ import annotations

from dataclasses import dataclass

from shared.logger import get_logger

__version__ = "1.0.0"
__all__ = ["SanityCheckerV2", "SanityResult"]

log = get_logger(__name__)


@dataclass(frozen=True)
class SanityResult:
    """Risultato di un controllo sanity."""
    passed:   bool
    level:    str           # 'OK' | 'WARN' | 'CRITICAL'
    rule:     str           # nome della regola
    message:  str
    value:    float | None = None


class SanityCheckerV2:
    """Controlli sanity per i nuovi dati introdotti dalla Roadmap Unificata.

    Usage::

        checker = SanityCheckerV2()
        result = checker.check_vix(vix_level=45.0)
        if result.level == 'CRITICAL':
            raise DataQualityError(result.message)
    """

    # ── VIX ──────────────────────────────────────────────────────────────

    def check_vix(self, vix_level: float) -> SanityResult:
        """Verifica che il livello VIX sia in range plausibile.

        Args:
            vix_level: Valore VIX corrente.

        Returns:
            SanityResult con level CRITICAL se VIX ≤ 0 o > 100.
        """
        if vix_level <= 0:
            return SanityResult(
                passed=False, level="CRITICAL", rule="vix_positive",
                message=f"VIX ≤ 0 impossibile: {vix_level:.2f}. Probabile errore feed.",
                value=vix_level,
            )
        if vix_level > 100:
            return SanityResult(
                passed=False, level="CRITICAL", rule="vix_max",
                message=f"VIX > 100 impossibile: {vix_level:.2f}. Probabile spike dato.",
                value=vix_level,
            )
        if vix_level > 50:
            return SanityResult(
                passed=True, level="WARN", rule="vix_extreme",
                message=f"VIX > 50 estremo ma plausibile: {vix_level:.2f}. Verificare.",
                value=vix_level,
            )
        return SanityResult(
            passed=True, level="OK", rule="vix_range",
            message=f"VIX in range normale: {vix_level:.2f}",
            value=vix_level,
        )

    # ── Futures ───────────────────────────────────────────────────────────

    def check_roll_yield(self, roll_yield: float, ticker: str = "") -> SanityResult:
        """Verifica che il roll yield sia in range plausibile.

        Args:
            roll_yield: Roll yield in decimale (es. -0.018 = -1.8%).
            ticker:     Simbolo futures per logging.

        Returns:
            SanityResult con level CRITICAL se |roll_yield| > 1.0 (100%).
        """
        abs_roll = abs(roll_yield)
        if abs_roll > 1.0:
            return SanityResult(
                passed=False, level="CRITICAL", rule="roll_yield_max",
                message=(
                    f"{ticker}: roll_yield {roll_yield*100:.1f}% > 100% impossibile. "
                    "Probabile errore nel prezzo proxy."
                ),
                value=roll_yield,
            )
        if abs_roll > 0.15:
            return SanityResult(
                passed=True, level="WARN", rule="roll_yield_high",
                message=f"{ticker}: roll_yield {roll_yield*100:.1f}% molto alto. Verificare.",
                value=roll_yield,
            )
        return SanityResult(
            passed=True, level="OK", rule="roll_yield_range",
            message=f"{ticker}: roll_yield {roll_yield*100:.3f}% in range.",
            value=roll_yield,
        )

    def check_futures_spot_discrepancy(
        self, futures_close: float, spot_close: float,
        ticker: str = "", spot_ticker: str = "",
        threshold_pct: float = 5.0,
    ) -> SanityResult:
        """Verifica la discrepanza futures vs spot ETF.

        Args:
            futures_close:  Prezzo close futures.
            spot_close:     Prezzo close ETF spot proxy.
            ticker:         Simbolo futures.
            spot_ticker:    Simbolo ETF proxy.
            threshold_pct:  Soglia discrepanza % (default: 5%).

        Returns:
            SanityResult WARN se discrepanza > threshold_pct.
        """
        if spot_close <= 0:
            return SanityResult(
                passed=False, level="WARN", rule="spot_zero",
                message=f"{spot_ticker}: prezzo spot ≤ 0.",
                value=spot_close,
            )
        discrepancy_pct = abs(futures_close - spot_close) / spot_close * 100
        if discrepancy_pct > threshold_pct:
            return SanityResult(
                passed=True, level="WARN", rule="futures_spot_discrepancy",
                message=(
                    f"{ticker} vs {spot_ticker}: discrepanza {discrepancy_pct:.1f}% "
                    f"> {threshold_pct:.0f}%. Basis inusuale, verificare."
                ),
                value=discrepancy_pct,
            )
        return SanityResult(
            passed=True, level="OK", rule="futures_spot_ok",
            message=f"{ticker} vs {spot_ticker}: discrepanza {discrepancy_pct:.1f}% OK.",
            value=discrepancy_pct,
        )

    # ── Yield Curve ───────────────────────────────────────────────────────

    def check_yield_spread(
        self, spread_10y_2y: float, label: str = "10Y-2Y"
    ) -> SanityResult:
        """Verifica che lo spread yield sia in range plausibile.

        Args:
            spread_10y_2y: Spread in punti percentuali.
            label:         Etichetta per logging.

        Returns:
            SanityResult CRITICAL se |spread| > 15%.
        """
        if abs(spread_10y_2y) > 15.0:
            return SanityResult(
                passed=False, level="CRITICAL", rule="yield_spread_max",
                message=(
                    f"Spread {label} = {spread_10y_2y:+.2f}% impossibile. "
                    "Probabile errore nel dato FRED."
                ),
                value=spread_10y_2y,
            )
        return SanityResult(
            passed=True, level="OK", rule="yield_spread_range",
            message=f"Spread {label} = {spread_10y_2y:+.2f}% plausibile.",
            value=spread_10y_2y,
        )

    # ── Batch check ───────────────────────────────────────────────────────

    def run_all(self, data: dict[str, float]) -> list[SanityResult]:
        """Esegue tutti i controlli sui dati forniti.

        Args:
            data: Dict con chiavi 'vix', 'roll_yield_clf', 'roll_yield_gcf',
                  'spread_10y_2y' e valori float.

        Returns:
            Lista di SanityResult con tutti i controlli eseguiti.
        """
        results: list[SanityResult] = []

        if "vix" in data:
            results.append(self.check_vix(data["vix"]))

        for key in ("roll_yield_clf", "roll_yield_gcf", "roll_yield_esf"):
            if key in data:
                ticker = key.replace("roll_yield_", "").upper().replace("LF", "L=F").replace("CF", "C=F").replace("SF", "S=F")
                results.append(self.check_roll_yield(data[key], ticker=ticker))

        if "spread_10y_2y" in data:
            results.append(self.check_yield_spread(data["spread_10y_2y"]))

        # Log CRITICAL e WARN
        for r in results:
            if r.level == "CRITICAL":
                log.error("sanity_checker.critical", rule=r.rule, message=r.message)
            elif r.level == "WARN":
                log.warning("sanity_checker.warn", rule=r.rule, message=r.message)

        return results

    def has_critical(self, results: list[SanityResult]) -> bool:
        """True se almeno un risultato è CRITICAL."""
        return any(r.level == "CRITICAL" for r in results)
