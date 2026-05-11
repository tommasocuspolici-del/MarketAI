# engine/volatility/vol_surface.py
"""
VolSurfaceAnalyzer: analizza la struttura a termine della volatilità implicita.

Ticker Yahoo Finance (tutti gratuiti):
  ^VIX   → volatilità implicita 30 giorni (standard)
  ^VIX9D → volatilità implicita 9 giorni (brevissimo termine)
  ^VXV   → volatilità implicita 93 giorni
  ^VXMT  → volatilità implicita 6 mesi
  ^SKEW  → indice skew delle opzioni S&P 500 (asimmetria distribuzione)

Interpretazione della curva:
  · Steep contango (VIX3M >> VIX): mercato si aspetta ritorno alla calma
    → normale in mercati non stressati
  · Flat: incertezza su direzione della volatilità
  · Backwardation (VIX > VIX3M): panico immediato prevale su lungo termine
    → spesso coincide con bottom di mercato (opportunità)
  · Inverted (VIX9D >> VIX >> VIX3M): stress di brevissimo termine estremo
    → coincide con eventi specifici (FOMC, earnings, crisi geopolitica)

Connessione con VIX-Based Analysis:
  Il regime della curva modifica il segnale VIX del StrategyComposer:
  · Backwardation → conferma segnale bullish del VIX (panico immediato)
  · Steep contango → segnale VIX meno affidabile (mercato non crede allo stress)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import structlog

from shared.types import TimeFrame

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient
    from shared.db.prices_repo import PricesRepository

__version__ = "1.0.0"
log = structlog.get_logger(__name__)

_VIX_TICKERS = {
    "vix_9d": ("^VIX9D", "NYSE"),
    "vix_1m": ("^VIX",   "NYSE"),
    "vix_3m": ("^VXV",   "NYSE"),
    "vix_6m": ("^VXMT",  "NYSE"),
    "skew":   ("^SKEW",  "NYSE"),
}


@dataclass(frozen=True)
class VolSurfaceSnapshot:
    snapshot_at:     datetime
    vix_9d:          float | None
    vix_1m:          float
    vix_3m:          float | None
    vix_6m:          float | None
    skew_index:      float | None
    term_slope_1m_3m: float | None   # vix_3m - vix_1m
    term_slope_3m_6m: float | None   # vix_6m - vix_3m
    contango_pct:    float | None    # (vix_3m / vix_1m - 1) * 100
    surface_regime:  str
    vix_signal_modifier: float          # [-0.3, +0.3]: modifica al segnale VIX

    @property
    def is_backwardation(self) -> bool:
        return self.surface_regime in ("backwardation", "inverted")

    @property
    def is_contango(self) -> bool:
        return self.surface_regime in ("steep_contango", "flat")


class VolSurfaceAnalyzer:
    """Costruisce e analizza la superficie di volatilità VIX."""

    def __init__(
        self,
        prices_repo: PricesRepository,
        duckdb:      DuckDBClient,
    ) -> None:
        self._repo   = prices_repo
        self._duckdb = duckdb

    def compute(self) -> VolSurfaceSnapshot:
        """Calcola lo snapshot corrente della vol surface."""
        levels: dict[str, float | None] = {}

        for key, (ticker, exchange) in _VIX_TICKERS.items():
            try:
                df = self._repo.read_ohlcv(
                    ticker=ticker, exchange=exchange,
                    timeframe=TimeFrame.D1, limit=1,
                )
                levels[key] = float(df["close"].iloc[-1]) if (
                    df is not None and not df.empty
                ) else None
            except Exception:
                levels[key] = None

        vix_1m = levels["vix_1m"]
        if vix_1m is None:
            raise ValueError("VIX 1M non disponibile — dato critico")

        vix_3m = levels["vix_3m"]
        vix_9d = levels["vix_9d"]
        vix_6m = levels["vix_6m"]

        # Slope 1M→3M
        slope_1m_3m = (
            float(vix_3m - vix_1m) if vix_3m is not None else None
        )
        slope_3m_6m = (
            float(vix_6m - vix_3m)
            if vix_6m is not None and vix_3m is not None else None
        )
        contango = (
            float((vix_3m / vix_1m - 1) * 100)
            if vix_3m is not None else None
        )

        surface_regime = self._classify_regime(vix_1m, vix_3m, vix_9d)
        modifier       = self._compute_signal_modifier(surface_regime, contango)

        snap = VolSurfaceSnapshot(
            snapshot_at=datetime.now(UTC),
            vix_9d=vix_9d,
            vix_1m=vix_1m,
            vix_3m=vix_3m,
            vix_6m=vix_6m,
            skew_index=levels["skew"],
            term_slope_1m_3m=slope_1m_3m,
            term_slope_3m_6m=slope_3m_6m,
            contango_pct=contango,
            surface_regime=surface_regime,
            vix_signal_modifier=modifier,
        )

        self._persist(snap)
        log.info(
            "vol_surface.computed",
            vix_1m=round(vix_1m, 2),
            vix_3m=round(vix_3m, 2) if vix_3m else None,
            regime=surface_regime,
            modifier=round(modifier, 3),
        )
        return snap

    @staticmethod
    def _classify_regime(
        vix_1m: float,
        vix_3m: float | None,
        vix_9d: float | None,
    ) -> str:
        if vix_3m is None:
            return "unknown"
        slope = vix_3m - vix_1m

        if vix_9d is not None and vix_9d > vix_1m * 1.05 and vix_1m > vix_3m:
            return "inverted"          # 9d > 1m > 3m: stress brevissimo termine
        if slope < -1.5:
            return "backwardation"     # 1m >> 3m: panico immediato
        if slope < 0.5:
            return "flat"
        if slope > 3.0:
            return "steep_contango"    # 3m >> 1m: mercato calmo, nessuna paura
        return "contango"

    @staticmethod
    def _compute_signal_modifier(regime: str, contango_pct: float | None) -> float:
        """
        Modifica il segnale VIX del StrategyComposer in base alla curva.

        Backwardation → conferma (+0.2): il panico è immediato e reale
        Steep contango → attenua (-0.2): lo stress può essere temporaneo
        Inverted       → conferma forte (+0.3): evento shock brevissimo termine
        """
        base_modifier = {
            "inverted":      0.30,
            "backwardation": 0.20,
            "flat":          0.05,
            "contango":     -0.10,
            "steep_contango":-0.20,
            "unknown":       0.00,
        }.get(regime, 0.0)

        # Se contango molto profondo (>5%), attenua ulteriormente
        if contango_pct is not None and contango_pct > 5.0:
            base_modifier -= 0.10

        return float(np.clip(base_modifier, -0.30, 0.30))

    def _persist(self, s: VolSurfaceSnapshot) -> None:
        self._duckdb.execute(
            """INSERT OR REPLACE INTO vol_surface_snapshots
               (snapshot_at, vix_9d, vix_1m, vix_3m, vix_6m, skew_index,
                term_slope_1m_3m, term_slope_3m_6m, contango_pct, surface_regime)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [s.snapshot_at, s.vix_9d, s.vix_1m, s.vix_3m, s.vix_6m,
             s.skew_index, s.term_slope_1m_3m, s.term_slope_3m_6m,
             s.contango_pct, s.surface_regime],
        )
