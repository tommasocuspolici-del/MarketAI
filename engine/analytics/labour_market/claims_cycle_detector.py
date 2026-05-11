"""
ClaimsCycleDetector: rileva il ciclo del mercato del lavoro dai Claims settimanali.

Initial Jobless Claims (ICSA) è uno dei leading indicators più tempestivi:
  · Salgono mediamente 6-9 mesi PRIMA delle recessioni conclamate
  · La media mobile 4 settimane (4wk MA) smootha la volatilità settimanale
  · Variazione YoY > +15% segnala deterioramento significativo

Ciclo rilevato (4 stati):
  expansion   - claims in calo o stazionari, mercato in espansione
  peak        - claims iniziano a salire, mercato al picco
  contraction - claims in aumento sostenuto, deterioramento in corso
  trough      - claims stabilizzano dopo recessione, prossimo a rimbalzo

Fonte FRED:
  ICSA  = Initial Claims SA (settimanale)
  CCSA  = Continuing Claims SA

Regola 8: numpy per tutti i calcoli.
Regola 13: persiste in claims_cycle (DuckDB, migration 009).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, UTC, datetime
from typing import Literal

import numpy as np
import pandas as pd
import structlog

from engine.market_data.fred_simple_client import (
    FredKeyMissingError,
    FredSimpleClient,
    FredSimpleError,
)

__version__ = "1.0.0"
log = structlog.get_logger(__name__)

ClaimsCycleRegime = Literal["expansion", "peak", "contraction", "trough"]

# Costanti regime (Regola 7)
_MA_WINDOW           = 4      # 4-week moving average
_PEAK_MOM_THRESHOLD  = 0.05   # Claims in salita > 5% MoM → peak
_CONTRACTION_YOY     = 0.15   # Claims > 15% YoY → contraction confermata
_TROUGH_MA_DECLINING = -0.03  # 4wk MA scende > 3% → trough/recovery

# Stima pesi per signal_strength [-1, 1]
_WEIGHT_YOY  = 0.50
_WEIGHT_MOM  = 0.30
_WEIGHT_LEVEL= 0.20

_FETCH_WEEKS = 104  # 2 anni di dati settimanali


@dataclass(frozen=True)
class ClaimsCycleSignal:
    """Segnale ciclo mercato lavoro da Initial Claims."""

    week_ending:      date
    initial_claims:   float
    claims_4wk_ma:    float
    claims_yoy_pct:   float | None
    claims_mom_pct:   float | None
    cycle_regime:     ClaimsCycleRegime
    signal_strength:  float    # [-1, 1]: +1 = mercato forte (pochi claims)


class ClaimsCycleDetector:
    """Rileva il ciclo del mercato del lavoro dai Claims settimanali ICSA."""

    def __init__(self, duckdb=None) -> None:
        self._duckdb = duckdb
        self._client = FredSimpleClient()

    def detect(self) -> ClaimsCycleSignal:
        """Fetcha ICSA da FRED e rileva il regime di ciclo.

        Returns:
            ClaimsCycleSignal con regime e signal_strength.
        """
        try:
            df_initial = self._client.fetch_series(
                "ICSA", limit=_FETCH_WEEKS, sort_order="asc"
            )
        except FredKeyMissingError:
            raise
        except FredSimpleError as exc:
            log.error("claims.fetch_failed", series="ICSA", error=str(exc))
            raise

        if df_initial.empty or len(df_initial) < _MA_WINDOW + 1:
            raise ValueError("Claims: dati insufficienti per rilevazione ciclo")

        signal = self._compute_signal(df_initial)

        if self._duckdb is not None:
            self._persist(df_initial, signal)

        log.info(
            "claims.detected",
            regime=signal.cycle_regime,
            claims=signal.initial_claims,
            ma_4wk=round(signal.claims_4wk_ma, 0),
            yoy_pct=round(signal.claims_yoy_pct, 2) if signal.claims_yoy_pct else None,
            strength=round(signal.signal_strength, 3),
        )
        return signal

    def _compute_signal(self, df: pd.DataFrame) -> ClaimsCycleSignal:
        """Calcola regime e signal_strength dai claims.

        Usa numpy per tutti i calcoli su array (Regola 8).
        """
        values = df["value"].to_numpy(dtype=np.float64)
        n      = len(values)

        # 4-week moving average (kernel di convoluzione — vettorizzato)
        kernel      = np.ones(_MA_WINDOW, dtype=np.float64) / _MA_WINDOW
        ma_full     = np.convolve(values, kernel, mode="full")[:n]
        ma_full[:_MA_WINDOW - 1] = np.nan
        latest_ma   = float(ma_full[-1])
        latest      = float(values[-1])

        # YoY e MoM
        yoy_pct: float | None = None
        mom_pct: float | None = None
        if n >= 52:
            prev_year = float(values[-52])
            if prev_year > 0:
                yoy_pct = float((latest - prev_year) / prev_year * 100)
        if n >= 5:
            prev_month = float(ma_full[-5]) if not np.isnan(ma_full[-5]) else float(values[-5])
            if prev_month > 0:
                mom_pct = float((latest_ma - prev_month) / prev_month * 100)

        # Regime
        regime = self._classify_regime(latest_ma, ma_full, yoy_pct, mom_pct)

        # Signal strength [-1, 1]
        # Claims bassi/in calo = positivo per mercato; claims alti/in rialzo = negativo
        yoy_score   = float(np.clip(-(yoy_pct or 0) / 30.0, -1.0, 1.0))
        mom_score   = float(np.clip(-(mom_pct or 0) / 10.0, -1.0, 1.0))
        # Livello assoluto: normalizzato su range storico tipico 180k-450k
        level_score = float(np.clip((300_000 - latest) / 120_000, -1.0, 1.0))
        signal_strength = float(
            yoy_score * _WEIGHT_YOY +
            mom_score * _WEIGHT_MOM +
            level_score * _WEIGHT_LEVEL
        )

        # Data ultima osservazione
        try:
            week_ending = pd.to_datetime(df["ts"].iloc[-1]).date()
        except Exception:  # noqa: BLE001
            week_ending = date.today()

        return ClaimsCycleSignal(
            week_ending=week_ending,
            initial_claims=latest,
            claims_4wk_ma=latest_ma,
            claims_yoy_pct=yoy_pct,
            claims_mom_pct=mom_pct,
            cycle_regime=regime,
            signal_strength=signal_strength,
        )

    @staticmethod
    def _classify_regime(
        current_ma: float,
        ma_history: np.ndarray,
        yoy_pct: float | None,
        mom_pct: float | None,
    ) -> ClaimsCycleRegime:
        """Classifica il regime dal pattern della 4wk MA.

        Logica:
          contraction: yoy > 15% O mom > 5%
          trough:      ma in calo dopo periodo di contrazione
          peak:        ma in rialzo moderato (mom 0-5%)
          expansion:   tutto il resto (ma stazionario o in calo)
        """
        # Contraction: deterioramento confermato
        if yoy_pct is not None and yoy_pct > _CONTRACTION_YOY * 100:
            return "contraction"
        if mom_pct is not None and mom_pct > _PEAK_MOM_THRESHOLD * 100:
            # Piccolo rialzo → peak; rialzo forte → contraction
            if mom_pct > 8.0:
                return "contraction"
            return "peak"

        # Trough: ma in discesa dopo un periodo elevato
        if len(ma_history) >= 8:
            valid = ma_history[~np.isnan(ma_history)]
            if len(valid) >= 8:
                # Se la MA attuale è sotto la media delle ultime 8 settimane
                recent_mean = float(np.mean(valid[-8:]))
                if current_ma < recent_mean * 0.97:  # scende > 3%
                    return "trough"

        return "expansion"

    def _persist(self, df: pd.DataFrame, signal: ClaimsCycleSignal) -> None:
        """Persiste l'ultimo record in claims_cycle DuckDB."""
        if self._duckdb is None:
            return
        now = datetime.now(UTC)
        try:
            self._duckdb.execute(
                """INSERT OR REPLACE INTO claims_cycle
                   (week_ending, initial_claims, claims_4wk_ma,
                    claims_yoy_pct, claims_mom_pct, cycle_regime, signal_strength, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    signal.week_ending,
                    int(signal.initial_claims),
                    signal.claims_4wk_ma,
                    signal.claims_yoy_pct,
                    signal.claims_mom_pct,
                    signal.cycle_regime,
                    signal.signal_strength,
                    now,
                ],
            )
        except Exception as exc:  # noqa: BLE001
            log.error("claims.persist_failed", error=str(exc))
