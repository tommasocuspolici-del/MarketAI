"""SanityCheckerV2 — Sanity checks avanzati per dati di mercato (Settimana 9).

Estende SanityChecker v1 con check specifici per:
  · VIX: range valido [0, 100], warn > 50, critical ≤ 0 o > 100
  · Roll yield futures: critical > 100% o < -100%, warn > 15%
  · Discrepanza futures/spot: warn > 5% (default)
  · Yield spread: critical se |spread| > 15%

Regola 5: nessun except generico — errori specifici.
Regola 7: soglie nominate come costanti, mai magic numbers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__version__ = "1.0.0"
__all__ = ["SanityCheckerV2", "SanityResult"]

# ── Soglie VIX (Regola 7) ────────────────────────────────────────
_VIX_MIN_OK        = 0.0    # VIX deve essere > 0
_VIX_WARN_UPPER    = 50.0   # VIX > 50 → estremo ma possibile
_VIX_CRITICAL_UPPER= 100.0  # VIX > 100 → impossibile

# ── Soglie roll yield ────────────────────────────────────────────
_ROLL_WARN_ABS     = 0.15   # |roll| > 15% → warn
_ROLL_CRITICAL_ABS = 1.00   # |roll| > 100% → critical

# ── Soglie discrepanza futures/spot ─────────────────────────────
_DISCREPANCY_DEFAULT_PCT = 5.0   # > 5% → warn

# ── Soglie yield spread ─────────────────────────────────────────
_SPREAD_CRITICAL_ABS = 15.0   # |spread| > 15% → critical


@dataclass(frozen=True)
class SanityResult:
    """Risultato di un singolo sanity check.

    Attributes:
        passed:  True se il dato è accettabile (anche con WARN).
        level:   'OK' | 'WARN' | 'CRITICAL'.
        rule:    Nome della regola applicata.
        message: Descrizione human-readable del risultato.
        value:   Valore controllato (opzionale).
    """
    passed:  bool
    level:   str          # 'OK' | 'WARN' | 'CRITICAL'
    rule:    str
    message: str
    value:   float | None = field(default=None)


class SanityCheckerV2:
    """Check di sanità avanzati per prezzi, VIX, roll yield, yield curve.

    Tutti i metodi sono puri (nessun side effect) e testabili in isolation.
    """

    # ── VIX ──────────────────────────────────────────────────────

    def check_vix(self, vix: float) -> SanityResult:
        """Controlla che il VIX sia in un range plausibile.

        Regole:
          · VIX ≤ 0        → CRITICAL (fisicamente impossibile)
          · VIX > 100      → CRITICAL (mai avvenuto nella storia)
          · VIX > 50       → WARN (estremo ma possibile: Mar 2020 ≈ 82)
          · 0 < VIX ≤ 50   → OK
        """
        rule = "vix_range_check"
        if vix <= _VIX_MIN_OK:
            return SanityResult(
                passed=False, level="CRITICAL", rule=rule,
                message=f"VIX={vix:.2f} ≤ 0: dato impossibile",
                value=vix,
            )
        if vix > _VIX_CRITICAL_UPPER:
            return SanityResult(
                passed=False, level="CRITICAL", rule=rule,
                message=f"VIX={vix:.2f} > {_VIX_CRITICAL_UPPER}: mai osservato nella storia",
                value=vix,
            )
        if vix > _VIX_WARN_UPPER:
            return SanityResult(
                passed=True, level="WARN", rule=rule,
                message=f"VIX={vix:.2f} > {_VIX_WARN_UPPER}: livello estremo, verificare",
                value=vix,
            )
        return SanityResult(
            passed=True, level="OK", rule=rule,
            message=f"VIX={vix:.2f} in range normale",
            value=vix,
        )

    # ── Roll Yield ────────────────────────────────────────────────

    def check_roll_yield(self, roll: float, ticker: str) -> SanityResult:
        """Controlla che il roll yield di un futures sia plausibile.

        Regole:
          · |roll| > 100% → CRITICAL (dato impossibile)
          · |roll| > 15%  → WARN (anomalo ma possibile in gas naturale)
          · altrimenti     → OK
        """
        rule = "roll_yield_range_check"
        abs_roll = abs(roll)
        if abs_roll > _ROLL_CRITICAL_ABS:
            return SanityResult(
                passed=False, level="CRITICAL", rule=rule,
                message=f"{ticker}: roll yield={roll*100:.1f}% > ±100%: dato impossibile",
                value=roll,
            )
        if abs_roll > _ROLL_WARN_ABS:
            return SanityResult(
                passed=True, level="WARN", rule=rule,
                message=f"{ticker}: roll yield={roll*100:.1f}% > ±{_ROLL_WARN_ABS*100:.0f}%: anomalo",
                value=roll,
            )
        return SanityResult(
            passed=True, level="OK", rule=rule,
            message=f"{ticker}: roll yield={roll*100:.2f}% in range normale",
            value=roll,
        )

    # ── Discrepanza Futures/Spot ──────────────────────────────────

    def check_futures_spot_discrepancy(
        self,
        futures_price: float,
        spot_price: float,
        futures_ticker: str,
        spot_ticker: str,
        threshold_pct: float = _DISCREPANCY_DEFAULT_PCT,
    ) -> SanityResult:
        """Controlla discrepanza tra futures e spot proxy.

        Regole:
          · spot = 0      → WARN (dato mancante, non blocca ma segnala)
          · discrepanza > threshold_pct% → WARN
          · altrimenti     → OK
        """
        rule = "futures_spot_discrepancy_check"
        if spot_price == 0:
            return SanityResult(
                passed=False, level="WARN", rule=rule,
                message=f"{futures_ticker}/{spot_ticker}: spot price = 0, dato mancante",
                value=0.0,
            )
        discrepancy = abs((futures_price - spot_price) / spot_price * 100)
        if discrepancy > threshold_pct:
            return SanityResult(
                passed=True, level="WARN", rule=rule,
                message=(
                    f"{futures_ticker}/{spot_ticker}: discrepanza {discrepancy:.1f}% "
                    f"> {threshold_pct:.1f}%"
                ),
                value=discrepancy,
            )
        return SanityResult(
            passed=True, level="OK", rule=rule,
            message=f"{futures_ticker}/{spot_ticker}: discrepanza {discrepancy:.1f}% OK",
            value=discrepancy,
        )

    # ── Yield Spread ──────────────────────────────────────────────

    def check_yield_spread(self, spread: float) -> SanityResult:
        """Controlla che lo yield spread sia in range plausibile.

        Regola: |spread| > 15% → CRITICAL (mai osservato storicamente).
        """
        rule = "yield_spread_range_check"
        if abs(spread) > _SPREAD_CRITICAL_ABS:
            return SanityResult(
                passed=False, level="CRITICAL", rule=rule,
                message=f"Yield spread={spread:.2f}% fuori range storico (|spread| > {_SPREAD_CRITICAL_ABS}%)",
                value=spread,
            )
        return SanityResult(
            passed=True, level="OK", rule=rule,
            message=f"Yield spread={spread:.2f}% in range normale",
            value=spread,
        )

    # ── Run all ───────────────────────────────────────────────────

    def run_all(self, data: dict[str, Any]) -> list[SanityResult]:
        """Esegue tutti i check disponibili sui dati forniti.

        Args:
            data: Dict con chiavi opzionali:
                  · 'vix': float
                  · 'roll_yield_clf': float (CL=F)
                  · 'spread_10y_2y': float

        Returns:
            Lista di SanityResult (vuota se data è vuoto).
        """
        results: list[SanityResult] = []
        if "vix" in data:
            results.append(self.check_vix(float(data["vix"])))
        if "roll_yield_clf" in data:
            results.append(self.check_roll_yield(float(data["roll_yield_clf"]), "CL=F"))
        if "spread_10y_2y" in data:
            results.append(self.check_yield_spread(float(data["spread_10y_2y"])))
        return results

    @staticmethod
    def has_critical(results: list[SanityResult]) -> bool:
        """True se almeno un risultato è CRITICAL."""
        return any(r.level == "CRITICAL" for r in results)
