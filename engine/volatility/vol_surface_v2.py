# engine/volatility/vol_surface.py
"""
VolSurfaceAnalyzer v2.0: struttura a termine della volatilità implicita.

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

OTTIMIZZAZIONI v2.0 (Blocco A roadmap):
  · Regime volatility da percentile storico: calm / elevated / stressed / crisis
    Basato su percentile rank del VIX rispetto agli ultimi 252 giorni.
  · VIX Futures Basis annualizzato: misura contango/backwardation in %/anno.
  · Alert SKEW > 145: tail-risk elevato → segnale distribuzioni pesanti.
  · Persistenza snapshot in vix_signals (tabella già presente da Migration 007).
  · Modifica al segnale VIX del StrategyComposer mantenuta e migliorata.
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

__version__ = "2.0.0"
log = structlog.get_logger(__name__)

_VIX_TICKERS = {
    "vix_9d": ("^VIX9D", "NYSE"),
    "vix_1m": ("^VIX",   "NYSE"),
    "vix_3m": ("^VXV",   "NYSE"),
    "vix_6m": ("^VXMT",  "NYSE"),
    "skew":   ("^SKEW",  "NYSE"),
}

# Soglie percentile per vol regime (calibrate su VIX 1990-2025)
_CALM_PCT_MAX      = 25.0   # percentile < 25 → calm
_ELEVATED_PCT_MAX  = 60.0   # 25-60 → elevated
_STRESSED_PCT_MAX  = 85.0   # 60-85 → stressed
                             # > 85   → crisis

# Alert SKEW (Regola Blocco A: SKEW > 145 → tail risk elevato)
_SKEW_TAIL_RISK_THRESHOLD = 145.0

# Lookback per calcolo percentile storico
_PERCENTILE_LOOKBACK_DAYS = 252


@dataclass(frozen=True)
class VolSurfaceSnapshot:
    """Snapshot completo della volatility surface VIX."""

    snapshot_at:          datetime
    vix_9d:               float | None
    vix_1m:               float
    vix_3m:               float | None
    vix_6m:               float | None
    skew_index:           float | None
    term_slope_1m_3m:     float | None   # vix_3m - vix_1m
    term_slope_3m_6m:     float | None   # vix_6m - vix_3m
    contango_pct:         float | None   # (vix_3m / vix_1m - 1) * 100
    # v2.0: regime dalla struttura a termine
    surface_regime:       str            # backwardation|flat|contango|steep_contango|inverted|unknown
    # v2.0: regime dalla volatilità assoluta (percentile storico)
    vol_regime:           str            # calm|elevated|stressed|crisis
    vix_pct_rank:         float | None   # percentile rank VIX su lookback
    # v2.0: Futures Basis annualizzato
    futures_basis_annual: float | None   # % annuo; positivo = contango, negativo = backwardation
    # v2.0: SKEW alert
    skew_tail_risk_alert: bool           # True se SKEW > 145
    # Modificatore per CompositeSignal
    vix_signal_modifier:  float          # [-0.3, +0.3]

    @property
    def is_backwardation(self) -> bool:
        return self.surface_regime in ("backwardation", "inverted")

    @property
    def is_contango(self) -> bool:
        return self.surface_regime in ("steep_contango", "flat")

    @property
    def is_stressed(self) -> bool:
        """True se la volatilità assoluta è in regime stressed o crisis."""
        return self.vol_regime in ("stressed", "crisis")


class VolSurfaceAnalyzer:
    """Costruisce e analizza la superficie di volatilità VIX.

    v2.0: aggiunto vol_regime (percentile), futures_basis, SKEW alert,
    e persistenza in vix_signals.
    """

    def __init__(
        self,
        prices_repo: PricesRepository,
        duckdb:      DuckDBClient,
    ) -> None:
        self._repo   = prices_repo
        self._duckdb = duckdb

    def compute(self) -> VolSurfaceSnapshot:
        """Calcola lo snapshot corrente della vol surface.

        Returns:
            VolSurfaceSnapshot con regime struttura a termine + vol regime.
        """
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
            except Exception:  # noqa: BLE001
                levels[key] = None

        vix_1m = levels["vix_1m"]
        if vix_1m is None:
            raise ValueError("VIX 1M non disponibile — dato critico")

        vix_3m = levels["vix_3m"]
        vix_9d = levels["vix_9d"]
        vix_6m = levels["vix_6m"]
        skew   = levels["skew"]

        # Slope 1M→3M e 3M→6M
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

        # Regime struttura a termine (basato su slope)
        surface_regime = self._classify_term_structure(vix_1m, vix_3m, vix_9d)
        modifier = self._compute_signal_modifier(surface_regime, contango)

        # v2.0: vol regime da percentile storico
        vix_history = self._load_vix_history()
        vix_pct_rank = self._compute_percentile_rank(vix_1m, vix_history)
        vol_regime = self._classify_vol_regime(vix_pct_rank)

        # v2.0: Futures Basis annualizzato
        # Approssimazione: basis = (VIX3M / VIX1M - 1) * (12/2) → annualizzato su 2 mesi
        futures_basis_annual: float | None = None
        if vix_3m is not None and vix_1m > 0:
            monthly_basis = (vix_3m / vix_1m - 1)
            futures_basis_annual = float(monthly_basis * 6)  # * 12/2 = * 6

        # v2.0: SKEW alert (Regola Blocco A: SKEW > 145 → tail risk elevato)
        skew_alert = bool(skew is not None and skew > _SKEW_TAIL_RISK_THRESHOLD)
        if skew_alert:
            log.warning(
                "vol_surface.skew_tail_risk_alert",
                skew=skew,
                threshold=_SKEW_TAIL_RISK_THRESHOLD,
                message="SKEW sopra soglia — distribuzione con code pesanti (tail risk elevato)",
            )

        snap = VolSurfaceSnapshot(
            snapshot_at=datetime.now(UTC),
            vix_9d=vix_9d,
            vix_1m=vix_1m,
            vix_3m=vix_3m,
            vix_6m=vix_6m,
            skew_index=skew,
            term_slope_1m_3m=slope_1m_3m,
            term_slope_3m_6m=slope_3m_6m,
            contango_pct=contango,
            surface_regime=surface_regime,
            vol_regime=vol_regime,
            vix_pct_rank=vix_pct_rank,
            futures_basis_annual=futures_basis_annual,
            skew_tail_risk_alert=skew_alert,
            vix_signal_modifier=modifier,
        )

        self._persist_vol_surface(snap)
        self._persist_vix_signals(snap)
        log.info(
            "vol_surface.computed",
            vix_1m=round(vix_1m, 2),
            vix_3m=round(vix_3m, 2) if vix_3m else None,
            surface_regime=surface_regime,
            vol_regime=vol_regime,
            vix_pct_rank=round(vix_pct_rank, 1) if vix_pct_rank else None,
            skew_alert=skew_alert,
            modifier=round(modifier, 3),
        )
        return snap

    # ─── Classificazione regime struttura a termine ───────────────────────────

    @staticmethod
    def _classify_term_structure(
        vix_1m: float,
        vix_3m: float | None,
        vix_9d: float | None,
    ) -> str:
        """Classifica il regime della struttura a termine della vol."""
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

    # ─── Vol regime da percentile storico (v2.0) ──────────────────────────────

    def _load_vix_history(self) -> np.ndarray:
        """Carica la storia VIX per calcolo percentile.

        Usa _PERCENTILE_LOOKBACK_DAYS barre dal PricesRepository.
        Ritorna array vuoto se non disponibile (graceful degradation).
        """
        try:
            df = self._repo.read_ohlcv(
                ticker="^VIX", exchange="NYSE",
                timeframe=TimeFrame.D1,
                limit=_PERCENTILE_LOOKBACK_DAYS,
            )
            if df is None or df.empty:
                return np.array([], dtype=np.float64)
            return df["close"].to_numpy(dtype=np.float64)
        except Exception:  # noqa: BLE001
            return np.array([], dtype=np.float64)

    @staticmethod
    def _compute_percentile_rank(vix_current: float, history: np.ndarray) -> float | None:
        """Percentile rank del VIX corrente rispetto alla storia.

        100 = massimo storico nel periodo; 0 = minimo storico.
        Utile per calibrare quanto il VIX corrente sia 'alto' storicamente.
        """
        if len(history) < 20:
            return None
        pct = float(np.mean(history <= vix_current) * 100)
        return round(pct, 1)

    @staticmethod
    def _classify_vol_regime(pct_rank: float | None) -> str:
        """Classifica il regime di volatilità assoluta da percentile rank.

        Calibrazione su VIX 1990-2025:
          calm:     pct < 25  (VIX < ~15) — mercato tranquillo
          elevated: 25-60     (VIX 15-22) — preoccupazione moderata
          stressed: 60-85     (VIX 22-30) — stress elevato
          crisis:   > 85      (VIX > 30)  — panico/crisi
        """
        if pct_rank is None:
            return "unknown"
        if pct_rank < _CALM_PCT_MAX:
            return "calm"
        if pct_rank < _ELEVATED_PCT_MAX:
            return "elevated"
        if pct_rank < _STRESSED_PCT_MAX:
            return "stressed"
        return "crisis"

    # ─── Modificatore segnale VIX ─────────────────────────────────────────────

    @staticmethod
    def _compute_signal_modifier(regime: str, contango_pct: float | None) -> float:
        """Modifica il segnale VIX del StrategyComposer in base alla curva.

        Backwardation → conferma (+0.2): il panico è immediato e reale
        Steep contango → attenua (-0.2): lo stress può essere temporaneo
        Inverted       → conferma forte (+0.3): evento shock brevissimo termine
        """
        base_modifier = {
            "inverted":       0.30,
            "backwardation":  0.20,
            "flat":           0.05,
            "contango":      -0.10,
            "steep_contango":-0.20,
            "unknown":        0.00,
        }.get(regime, 0.0)

        # Se contango molto profondo (>5%), attenua ulteriormente
        if contango_pct is not None and contango_pct > 5.0:
            base_modifier -= 0.10

        return float(np.clip(base_modifier, -0.30, 0.30))

    # ─── Persistenza ──────────────────────────────────────────────────────────

    def _persist_vol_surface(self, s: VolSurfaceSnapshot) -> None:
        """Persiste in vol_surface_snapshots (tabella da migration 008)."""
        try:
            self._duckdb.execute(
                """INSERT OR REPLACE INTO vol_surface_snapshots
                   (snapshot_at, vix_9d, vix_1m, vix_3m, vix_6m, skew_index,
                    term_slope_1m_3m, term_slope_3m_6m, contango_pct, surface_regime)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [s.snapshot_at, s.vix_9d, s.vix_1m, s.vix_3m, s.vix_6m,
                 s.skew_index, s.term_slope_1m_3m, s.term_slope_3m_6m,
                 s.contango_pct, s.surface_regime],
            )
        except Exception as exc:  # noqa: BLE001
            log.error("vol_surface.persist_vol_surface_failed", error=str(exc))

    def _persist_vix_signals(self, s: VolSurfaceSnapshot) -> None:
        """Persiste in vix_signals (tabella da migration 007).

        v2.0 (Blocco A): popola vix_pct_rank, regime e zscore calcolati.
        Lo z-score viene approssimato dal percentile rank per compatibilità.
        """
        try:
            # Z-score approssimato da percentile (mapping non-lineare inverso normale)
            from scipy import stats as sp_stats
            vix_zscore = 0.0
            if s.vix_pct_rank is not None:
                # Percentile → z-score: 50% → 0, 95% → 1.65, 99% → 2.33
                vix_zscore = float(sp_stats.norm.ppf(
                    max(0.01, min(0.99, s.vix_pct_rank / 100))
                ))

            # Regime per vix_signals: mappa vol_regime al formato atteso
            signal_regime = {
                "calm":     "calm",
                "elevated": "elevated",
                "stressed": "high_stress",
                "crisis":   "panic",
                "unknown":  "calm",
            }.get(s.vol_regime, "calm")

            zscore_signal = (
                "buy"  if vix_zscore > 1.5  else
                "sell" if vix_zscore < -0.5 else
                "hold"
            )
            spike = bool(s.vol_regime == "crisis")

            self._duckdb.execute(
                """INSERT OR REPLACE INTO vix_signals
                   (computed_at, vix_level, vix_zscore, vix_vxv_ratio,
                    vix_pct_rank, spike_detected, zscore_signal, regime, lookback_days)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    s.snapshot_at,
                    s.vix_1m,
                    vix_zscore,
                    float(s.vix_3m / s.vix_1m) if s.vix_3m else None,
                    s.vix_pct_rank,
                    spike,
                    zscore_signal,
                    signal_regime,
                    _PERCENTILE_LOOKBACK_DAYS,
                ],
            )
        except Exception as exc:  # noqa: BLE001
            log.error("vol_surface.persist_vix_signals_failed", error=str(exc))
