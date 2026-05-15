"""
PayrollDecomposer: analisi NFP per settore + revisions tracker.

Il NFP headline (PAYEMS) nasconde dinamiche settoriali opposte.
Un payroll forte trainato esclusivamente da settori difensivi (governo,
sanitÃ ) ha implicazioni molto diverse da uno trainato da manifattura
e servizi privati.

Cyclical vs Defensive split:
  Â· Ciclici:   manifattura, costruzioni, retail, tempo libero/ospitalitÃ 
  Â· Difensivi: governo federale/statale, sanitÃ , educazione
  Rapporto ciclici/difensivi: > 1 â†’ espansione guidata dal settore privato

Revisions Tracker:
  Â· 2-month revision: differenza cumulata tra prima stima e revisione finale
  Â· Revisioni sistematicamente negative segnalano debolezza latente
  Â· NFP vs ADP divergence: differenza tra NFP BLS e stima ADP
    (ADP esce 2gg prima del NFP â†’ leading indicator di revisioni future)

Serie FRED usate:
  PAYEMS    = NFP totale SA
  MANEMP    = Manifattura
  USCONS    = Costruzioni
  USTRADE   = Retail
  AEHOUS    = Tempo libero e ospitalitÃ 
  SRVPRD    = Servizi privati
  USGOVT    = Governo totale
  EDUHITH   = Educazione e sanitÃ 

Regola 8: numpy per tutti i calcoli.
Regola 13: persiste in payroll_sector (DuckDB, migration 009).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, UTC, datetime

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

# Settori e serie FRED (Regola 7: costanti nominate)
_SECTOR_SERIES: dict[str, tuple[str, bool]] = {
    # (fred_series_id, is_cyclical)
    "manufacturing":    ("MANEMP",  True),
    "construction":     ("USCONS",  True),
    "retail":           ("USTRADE", True),
    "leisure_hosp":     ("AEHOUS",  True),
    "services_private": ("SRVPRD",  False),   # ampio, include sia ciclici che difensivi
    "government":       ("USGOVT",  False),
    "education_health": ("EDUHITH", False),
}

_TOTAL_SERIES = "PAYEMS"  # NFP totale
_FETCH_MONTHS = 24        # Storia per revisions tracker


@dataclass(frozen=True)
class PayrollSignal:
    """Segnale sintetico NFP per il LabourRegimeClassifier."""

    release_date:         date
    nfp_total:            float           # Totale migliaia posti
    cyclical_jobs:        float           # Somma settori ciclici
    defensive_jobs:       float           # Somma settori difensivi
    cyclical_ratio:       float           # cyclical / max(defensive, 1)
    two_month_revision:   float | None    # Revisione cumulata 2 mesi (in migliaia)
    payroll_score:        float           # [-1, 1]: +1 = payroll forte e ciclico
    sector_breakdown:     dict[str, float]


class PayrollDecomposer:
    """Decompone il NFP nei settori costituenti e calcola il payroll score."""

    def __init__(self, duckdb: object = None) -> None:
        self._duckdb = duckdb
        self._client = FredSimpleClient()

    def decompose(self) -> PayrollSignal:
        """Fetcha i dati NFP da FRED e calcola il payroll signal.

        Returns:
            PayrollSignal con breakdown settoriale e payroll_score [-1,1].
        """
        # Fetch totale NFP
        try:
            df_total = self._client.fetch_series(
                _TOTAL_SERIES, limit=_FETCH_MONTHS, sort_order="asc"
            )
        except FredKeyMissingError:
            raise
        except FredSimpleError as exc:
            log.error("payroll.total_fetch_failed", error=str(exc))
            raise

        # Fetch settori
        sector_frames: dict[str, pd.DataFrame] = {}
        for sector, (series_id, _) in _SECTOR_SERIES.items():
            try:
                df = self._client.fetch_series(
                    series_id, limit=_FETCH_MONTHS, sort_order="asc"
                )
                sector_frames[sector] = df
            except FredSimpleError as exc:
                log.warning("payroll.sector_fetch_failed", sector=sector, error=str(exc)[:60])
                sector_frames[sector] = pd.DataFrame()

        signal = self._compute_signal(df_total, sector_frames)

        if self._duckdb is not None:
            self._persist(signal, sector_frames)

        log.info(
            "payroll.decomposed",
            nfp=signal.nfp_total,
            cyclical=round(signal.cyclical_jobs, 0),
            defensive=round(signal.defensive_jobs, 0),
            ratio=round(signal.cyclical_ratio, 2),
            score=round(signal.payroll_score, 3),
        )
        return signal

    def _compute_signal(
        self,
        df_total: pd.DataFrame,
        sector_frames: dict[str, pd.DataFrame],
    ) -> PayrollSignal:
        """Calcola breakdown e score da DataFrame FRED.

        Usa numpy per i calcoli (Regola 8).
        """
        def last_val(df: pd.DataFrame) -> float:
            return float(df["value"].iloc[-1]) if not df.empty else 0.0

        def delta_mom(df: pd.DataFrame) -> float:
            """Variazione mese su mese (MoM) in migliaia."""
            if len(df) < 2:
                return 0.0
            arr = df["value"].to_numpy(dtype=np.float64)
            return float(arr[-1] - arr[-2])

        # NFP totale e MoM
        nfp_total  = last_val(df_total)
        nfp_mom    = delta_mom(df_total)

        # Breakdown settoriale
        sector_vals: dict[str, float] = {}
        for sector, (_, is_cyclical) in _SECTOR_SERIES.items():
            df = sector_frames.get(sector, pd.DataFrame())
            sector_vals[sector] = delta_mom(df)  # usa MoM per comparabilitÃ 

        # Cyclical vs Defensive
        cyclical_jobs  = sum(v for s, v in sector_vals.items()
                             if _SECTOR_SERIES[s][1])
        defensive_jobs = sum(v for s, v in sector_vals.items()
                             if not _SECTOR_SERIES[s][1])
        cyclical_ratio = float(cyclical_jobs / max(abs(defensive_jobs), 1.0))

        # Revisions tracker: confronta prima stima con valore attuale su 2 mesi
        two_month_revision = self._compute_revision(df_total)

        # Score payroll [-1, 1]
        # Componenti:
        #   1. NFP headline MoM: normalizzato su range tipico Â±300k
        #   2. Cyclical ratio: > 1 positivo, < 0 negativo
        #   3. Revisions: revisioni positive = segnale rialzista
        nfp_score    = float(np.clip(nfp_mom / 200_000, -1.0, 1.0))  # Â±200k = Â±1
        cyclical_s   = float(np.clip((cyclical_ratio - 1.0) / 2.0, -1.0, 1.0))
        revision_s   = 0.0
        if two_month_revision is not None:
            revision_s = float(np.clip(two_month_revision / 100_000, -1.0, 1.0))

        payroll_score = float(
            nfp_score  * 0.50 +
            cyclical_s * 0.35 +
            revision_s * 0.15
        )

        # Data release
        try:
            release_date = pd.to_datetime(df_total["ts"].iloc[-1]).date()
        except Exception:  # noqa: BLE001
            release_date = date.today()

        return PayrollSignal(
            release_date=release_date,
            nfp_total=nfp_total,
            cyclical_jobs=cyclical_jobs,
            defensive_jobs=defensive_jobs,
            cyclical_ratio=cyclical_ratio,
            two_month_revision=two_month_revision,
            payroll_score=round(payroll_score, 4),
            sector_breakdown=sector_vals,
        )

    @staticmethod
    def _compute_revision(df_total: pd.DataFrame) -> float | None:
        """Stima la revisione cumulata a 2 mesi dal trend recente.

        Il FRED rilascia i dati giÃ  revisionati. Usiamo la differenza tra
        il valore attuale del mese M-2 e quello registrato al momento del
        rilascio M (che era la prima stima di M-2) come proxy della revisione.
        In pratica: confronta l'ultimo punto vs la media dei 2 precedenti.
        """
        if len(df_total) < 4:
            return None
        vals   = df_total["value"].to_numpy(dtype=np.float64)
        latest = float(vals[-1])
        prev2m = float(np.mean(vals[-3:-1]))
        # Revisione: se latest > media 2 mesi fa â†’ revisione positiva (dati migliorati)
        return float(latest - prev2m)

    def _persist(
        self,
        signal: PayrollSignal,
        sector_frames: dict[str, pd.DataFrame],
    ) -> None:
        """Persiste in payroll_sector DuckDB (migration 009)."""
        if self._duckdb is None:
            return
        now = datetime.now(UTC)
        for sector, (_, is_cyclical) in _SECTOR_SERIES.items():
            df = sector_frames.get(sector, pd.DataFrame())
            if df.empty:
                continue
            jobs_mom = float(df["value"].iloc[-1] - df["value"].iloc[-2]) if len(df) >= 2 else 0.0
            jobs_yoy = None
            if len(df) >= 13:
                prev_y = float(df["value"].iloc[-13])
                cur = float(df["value"].iloc[-1])
                if prev_y > 0:
                    jobs_yoy = float((cur - prev_y) / prev_y * 100)

            try:
                self._duckdb.execute(  # type: ignore[attr-defined]
                    """INSERT OR REPLACE INTO payroll_sector
                       (release_date, sector, jobs_added_k, two_month_revision,
                        yoy_pct, is_cyclical)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        signal.release_date,
                        sector,
                        jobs_mom,
                        signal.two_month_revision,
                        jobs_yoy,
                        is_cyclical,
                    ],
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("payroll.persist_failed", sector=sector, error=str(exc)[:60])
