# engine/fixed_income/real_yield_analyzer.py
"""
RealYieldAnalyzer: calcola il real yield e le sue implicazioni su oro ed equity.

Real Yield = Nominal Yield - Breakeven Inflation
  · Nominal: DGS10 (Federal Reserve, serie FRED)
  · Breakeven: T10YIE (differenza tra Treasury nominale e TIPS, serie FRED)

Relazioni fondamentali (ben documentate empiricamente):
  1. Real yield ↑ → Oro ↓ (l'oro non paga cedola, costo opportunità sale)
     Correlazione storica: ~-0.75 su dati 2000-2024
  2. Real yield ↑ → P/E equity ↓ (discount rate più alto comprimi multipli)
     Relazione teorica: P/E_fair = 1 / real_yield (semplificazione)
  3. Real yield molto negativo → oro outperform, growth stocks outperform
     (periodo 2020-2021: real yield = -1.1%, QQQ +48%)

Z-Score del real yield:
  Contestualizza il livello corrente rispetto alla storia recente.
  Real yield a -1.0% sembra molto negativo, ma se la media è -0.5%
  e la deviazione standard è 0.3%, lo Z-Score è -1.67 (non estremo).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import structlog

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient
    from shared.db.macro_repo import MacroRepository

__version__ = "1.0.0"
log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RealYieldSignal:
    computed_at:        datetime
    nominal_10y:        float
    breakeven_10y:      float
    real_yield_10y:     float
    real_yield_trend:   str           # 'rising'|'falling'|'stable'
    real_yield_zscore:  float
    gold_implied_signal: str          # 'bearish_gold'|'neutral'|'bullish_gold'
    equity_pe_pressure: str           # 'compressing'|'stable'|'expanding'
    fair_pe_estimate:   float | None
    narrative_summary:  str


class RealYieldAnalyzer:
    """Analizza il real yield e produce segnali per oro ed equity."""

    def __init__(
        self,
        macro_repo: MacroRepository,
        duckdb:     DuckDBClient,
        lookback_days: int = 252,
    ) -> None:
        self._macro    = macro_repo
        self._duckdb   = duckdb
        self._lookback = lookback_days

    def compute(self) -> RealYieldSignal:
        """Calcola il segnale real yield corrente."""

        # Carica serie FRED
        nominal_df   = self._macro.read_macro("DGS10",  limit=self._lookback)
        breakeven_df = self._macro.read_macro("T10YIE", limit=self._lookback)

        if nominal_df is None or nominal_df.empty:
            raise ValueError("DGS10 non disponibile nel DB")
        if breakeven_df is None or breakeven_df.empty:
            raise ValueError("T10YIE non disponibile nel DB")

        nominal   = nominal_df["value"].dropna().to_numpy(dtype=np.float64)
        breakeven = breakeven_df["value"].dropna().to_numpy(dtype=np.float64)

        # Allinea le serie (lunghezze diverse per frequenza diversa)
        min_len = min(len(nominal), len(breakeven))
        nominal   = nominal[-min_len:]
        breakeven = breakeven[-min_len:]

        real_yield_series = nominal - breakeven
        current_real = float(real_yield_series[-1])
        current_nom  = float(nominal[-1])
        current_be   = float(breakeven[-1])

        # Trend: confronto con 20gg precedenti
        prev_real = float(np.mean(real_yield_series[-25:-5]))
        if current_real > prev_real + 0.10:
            trend = "rising"
        elif current_real < prev_real - 0.10:
            trend = "falling"
        else:
            trend = "stable"

        # Z-Score su 252gg
        mu  = float(np.mean(real_yield_series))
        std = float(np.std(real_yield_series, ddof=1))
        zscore = float((current_real - mu) / std) if std > 0 else 0.0

        # Segnale per l'oro
        gold_signal = self._gold_signal(current_real, trend, zscore)

        # Pressione sui multipli equity
        pe_pressure = self._pe_pressure(current_real, trend)

        # Fair P/E estimato (semplificato: 1 / max(real_yield, 0.01))
        fair_pe = (
            round(1.0 / current_real, 1) if current_real > 0.005 else None
        )

        narrative = self._build_narrative(
            current_nom, current_be, current_real, trend, zscore,
            gold_signal, pe_pressure, fair_pe
        )

        signal = RealYieldSignal(
            computed_at=datetime.now(UTC),
            nominal_10y=current_nom,
            breakeven_10y=current_be,
            real_yield_10y=current_real,
            real_yield_trend=trend,
            real_yield_zscore=zscore,
            gold_implied_signal=gold_signal,
            equity_pe_pressure=pe_pressure,
            fair_pe_estimate=fair_pe,
            narrative_summary=narrative,
        )

        self._persist(signal)
        log.info(
            "real_yield.computed",
            nominal=round(current_nom, 2),
            breakeven=round(current_be, 2),
            real=round(current_real, 2),
            trend=trend, gold=gold_signal, pe=pe_pressure,
        )
        return signal

    @staticmethod
    def _gold_signal(real: float, trend: str, zscore: float) -> str:
        """
        Real yield negativo e in calo → favorevole per l'oro.
        Real yield positivo e in salita → negativo per l'oro.
        """
        if real < -0.50 or (real < 0 and trend == "falling"):
            return "bullish_gold"
        if real > 1.50 or (real > 0.5 and trend == "rising" and zscore > 1.0):
            return "bearish_gold"
        return "neutral"

    @staticmethod
    def _pe_pressure(real: float, trend: str) -> str:
        """
        Real yield in salita → discount rate sale → multipli si comprimono.
        Real yield in calo → multipli si espandono.
        """
        if trend == "rising" and real > 0.5:
            return "compressing"
        if trend == "falling" and real < 1.0:
            return "expanding"
        return "stable"

    @staticmethod
    def _build_narrative(
        nom: float, be: float, real: float,
        trend: str, zscore: float,
        gold: str, pe: str, fair_pe: float | None,
    ) -> str:
        trend_it = {"rising": "in salita", "falling": "in calo", "stable": "stabile"}
        gold_it  = {"bullish_gold": "favorevole per l'oro",
                    "bearish_gold": "sfavorevole per l'oro", "neutral": "neutro per l'oro"}
        pe_it    = {"compressing": "si stanno comprimendo",
                    "expanding": "si stanno espandendo", "stable": "sono stabili"}

        return (
            f"Real yield 10Y: {real:+.2f}% "
            f"(nominale {nom:.2f}% - breakeven {be:.2f}%). "
            f"Trend {trend_it[trend]} (Z-Score: {zscore:+.1f}). "
            f"Outlook oro: {gold_it[gold]}. "
            f"Multipli P/E equity {pe_it[pe]}."
            + (f" P/E fair stimato: {fair_pe:.0f}x." if fair_pe else "")
        )

    def _persist(self, s: RealYieldSignal) -> None:
        self._duckdb.execute(
            """INSERT OR REPLACE INTO real_yield_signals
               (computed_at, nominal_10y, breakeven_10y, real_yield_10y,
                real_yield_trend, real_yield_zscore,
                gold_implied_signal, equity_pe_pressure)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [s.computed_at, s.nominal_10y, s.breakeven_10y, s.real_yield_10y,
             s.real_yield_trend, s.real_yield_zscore,
             s.gold_implied_signal, s.equity_pe_pressure],
        )
