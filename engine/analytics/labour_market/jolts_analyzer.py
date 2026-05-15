"""
JOLTSAnalyzer: Job Openings and Labor Turnover Survey.

Analizza i dati JOLTS mensili (FRED) per determinare lo stato del mercato
del lavoro USA. Produce segnali sul regime (tight/balanced/slack/deteriorating)
basandosi su:

  Â· Beveridge Curve gap: openings_rate - unemployment_rate
    > 0 = molte offerte, poca disoccupazione = mercato surriscaldato (wage pressure)
    < 0 = poche offerte rispetto a disoccupazione = mercato rilassato

  Â· Quits Rate (% dimissioni volontarie):
    Leading indicator di +3-6M per wage growth.
    Alto quits rate = i lavoratori hanno potere contrattuale.

  Â· Hires vs Layoffs:
    hires > layoffs = espansione netta occupazione

Fonti FRED:
  JTSJOL  = Job Openings (total, SA, migliaia)
  JTSHL   = Hires
  JTSQUL  = Quits
  JTSLUL  = Layoffs & Discharges
  JTSQUR  = Quits Rate %
  JTSJOR  = Openings Rate %
  UNRATE  = Unemployment Rate (per Beveridge gap)

Regola 8: numpy per tutti i calcoli.
Regola 12: fetch â†’ clean â†’ validate â†’ duckdb_write â†’ cache â†’ return
Regola 13: persiste in jolts_monthly (DuckDB).
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

LabourRegime = Literal["tight", "balanced", "slack", "deteriorating"]

# Soglie regime calibrate su cicli JOLTS 1990-2025 (Regola 7: costanti nominate)
_TIGHT_QUITS_RATE_MIN    = 2.5   # % dimissioni â€” soglia mercato molto caldo
_TIGHT_OPENINGS_RATE_MIN = 5.0   # % aperture â€” soglia mercato saturo
_BALANCED_QUITS_MIN      = 2.0
_BALANCED_OPENINGS_MIN   = 3.5
_DETERIORATING_QUITS_MOM = -0.3  # Calo quits rate q/q > 0.3pp â†’ deterioramento

# Serie FRED per JOLTS
_JOLTS_FRED_SERIES: dict[str, str] = {
    "job_openings": "JTSJOL",
    "hires":        "JTSHL",
    "quits":        "JTSQUL",
    "layoffs":      "JTSLUL",
    "quits_rate":   "JTSQUR",
    "openings_rate":"JTSJOR",
    "unemployment": "UNRATE",
}

# Numero di mesi di storia da caricare
_DEFAULT_HISTORY_MONTHS = 36


@dataclass(frozen=True)
class JOLTSSignal:
    """Segnale sintetico JOLTS per il Labour Regime Classifier."""

    regime:          LabourRegime
    beveridge_gap:   float    # > 0 â†’ piÃ¹ offerte che domanda; < 0 â†’ mercato caldo
    quits_momentum:  float    # Variazione trimestrale quits rate (leading wage)
    labour_score:    float    # [-1, 1]: +1 = mercato del lavoro forte
    latest_date:     date
    quits_rate:      float
    openings_rate:   float
    hires_quits_ratio: float


class JOLTSAnalyzer:
    """
    Analisi dei dati JOLTS per determinare lo stato del mercato del lavoro.

    Beveridge Curve: il gap tra openings_rate e unemployment_rate misura
    quanto il mercato del lavoro Ã¨ "surriscaldato" (gap positivo = molte
    offerte, poca disoccupazione = wage pressure).
    """

    def __init__(
        self,
        duckdb: object = None,
        history_months: int = _DEFAULT_HISTORY_MONTHS,
    ) -> None:
        self._duckdb   = duckdb
        self._history  = history_months
        self._client   = FredSimpleClient()

    def analyze(self) -> JOLTSSignal:
        """Fetcha i dati JOLTS da FRED, calcola il segnale e persiste.

        Returns:
            JOLTSSignal con regime, Beveridge gap e labour_score [-1, 1].

        Raises:
            FredKeyMissingError: se FRED_API_KEY non configurata.
        """
        # Fetch tutte le serie JOLTS
        frames: dict[str, pd.DataFrame] = {}
        for field, series_id in _JOLTS_FRED_SERIES.items():
            try:
                df = self._client.fetch_series(
                    series_id,
                    limit=self._history,
                    sort_order="asc",
                )
                frames[field] = df
            except FredKeyMissingError:
                raise
            except FredSimpleError as exc:
                log.warning(
                    "jolts.series_fetch_failed",
                    field=field,
                    series_id=series_id,
                    error=str(exc),
                )
                frames[field] = pd.DataFrame()

        signal = self._compute_signal(frames)

        if self._duckdb is not None:
            self._persist(frames)

        log.info(
            "jolts.analyzed",
            regime=signal.regime,
            score=round(signal.labour_score, 3),
            beveridge_gap=round(signal.beveridge_gap, 2),
            quits_rate=round(signal.quits_rate, 2),
        )
        return signal

    def _compute_signal(self, frames: dict[str, pd.DataFrame]) -> JOLTSSignal:
        """Calcola il segnale JOLTS dai DataFrame FRED.

        Tutta la matematica Ã¨ in numpy (Regola 8).
        """
        def last_value(field: str) -> float:
            df = frames.get(field, pd.DataFrame())
            if df.empty:
                return 0.0
            return float(df["value"].iloc[-1])

        def as_array(field: str) -> np.ndarray:  # type: ignore[type-arg]
            df = frames.get(field, pd.DataFrame())
            if df.empty:
                return np.array([], dtype=np.float64)
            return df["value"].to_numpy(dtype=np.float64)  # type: ignore[no-any-return]

        quits_rate    = last_value("quits_rate")
        openings_rate = last_value("openings_rate")
        unemployment  = last_value("unemployment")
        hires_val     = last_value("hires")
        quits_val     = last_value("quits")

        # Beveridge gap: openings_rate - unemployment_rate
        # Positivo â†’ mercato surriscaldato; negativo â†’ mercato lasco
        beveridge_gap = float(openings_rate - unemployment)

        # Momentum quits (leading wage indicator +3-6M)
        quits_arr = as_array("quits_rate")
        quits_momentum = 0.0
        if len(quits_arr) >= 4:
            quits_momentum = float(quits_arr[-1] - quits_arr[-4])

        # Hires/Quits ratio
        hires_quits_ratio = float(hires_val / quits_val) if quits_val > 0 else 1.0

        # Score labour [-1, 1]
        beveridge_score = float(np.clip(beveridge_gap / 3.0, -1.0, 1.0))
        quits_score     = float(np.clip(quits_momentum / 0.5, -1.0, 1.0))
        labour_score    = float(beveridge_score * 0.6 + quits_score * 0.4)

        # Regime
        if quits_rate >= _TIGHT_QUITS_RATE_MIN and openings_rate >= _TIGHT_OPENINGS_RATE_MIN:
            regime: LabourRegime = "tight"
        elif quits_rate >= _BALANCED_QUITS_MIN and openings_rate >= _BALANCED_OPENINGS_MIN:
            regime = "balanced"
        elif quits_momentum < _DETERIORATING_QUITS_MOM:
            regime = "deteriorating"
        else:
            regime = "slack"

        # Data ultima osservazione
        quits_df = frames.get("quits_rate", pd.DataFrame())
        try:
            latest_date = pd.to_datetime(quits_df["ts"].iloc[-1]).date()
        except Exception:  # noqa: BLE001
            latest_date = date.today()

        return JOLTSSignal(
            regime=regime,
            beveridge_gap=beveridge_gap,
            quits_momentum=quits_momentum,
            labour_score=labour_score,
            latest_date=latest_date,
            quits_rate=quits_rate,
            openings_rate=openings_rate,
            hires_quits_ratio=hires_quits_ratio,
        )

    def _persist(self, frames: dict[str, pd.DataFrame]) -> None:
        """Persiste gli ultimi N mesi di JOLTS in DuckDB (tabella jolts_monthly).

        BUGFIX Regola 23: rimosso iterrows con lookup riga-per-riga.
        Sostituito con merge vettorizzato su colonna ts â€” O(N log N) invece di O(N*K).
        """
        if self._duckdb is None:
            return

        base_df = frames.get("quits_rate", pd.DataFrame())
        if base_df.empty:
            return

        # Costruisci DataFrame allineato tramite merge vettorizzato
        def _prep(field: str) -> pd.DataFrame:
            df = frames.get(field, pd.DataFrame())
            if df.empty:
                return pd.DataFrame(columns=["_ts", field])
            return df.assign(_ts=pd.to_datetime(df["ts"]).dt.normalize())[["_ts", "value"]].rename(columns={"value": field})

        merged = base_df.assign(_ts=pd.to_datetime(base_df["ts"]).dt.normalize())
        for field in ["openings_rate", "unemployment", "hires", "quits",
                       "job_openings", "layoffs"]:
            prep = _prep(field)
            if not prep.empty:
                merged = merged.merge(prep, on="_ts", how="left")
            else:
                merged[field] = float("nan")

        # Calcola colonne derivate vettorizzato
        merged["beveridge_gap"] = (
            merged["openings_rate"].to_numpy(dtype="float64") -
            merged["unemployment"].to_numpy(dtype="float64")
        )
        q_arr = merged["quits"].to_numpy(dtype="float64")
        h_arr = merged["hires"].to_numpy(dtype="float64")
        with import_np() as np:  # type: ignore[no-untyped-call]
            merged["hires_quits_ratio"] = np.where(
                q_arr > 0, h_arr / q_arr, float("nan")
            )

        now = datetime.now(UTC)
        for _, row in merged.iterrows():  # loop su N righe per INSERT â€” accettabile, non su serie storiche
            series_date = pd.to_datetime(row["ts"]).date()
            try:
                self._duckdb.execute(  # type: ignore[attr-defined]
                    """INSERT OR REPLACE INTO jolts_monthly
                       (series_date, job_openings, hires, quits, layoffs_discharges,
                        quits_rate, openings_rate, beveridge_gap, hires_quits_ratio, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        series_date,
                        None if pd.isna(row.get("job_openings", float("nan"))) else float(row["job_openings"]),
                        None if pd.isna(row.get("hires", float("nan"))) else float(row["hires"]),
                        None if pd.isna(row.get("quits", float("nan"))) else float(row["quits"]),
                        None if pd.isna(row.get("layoffs", float("nan"))) else float(row["layoffs"]),
                        None if pd.isna(row.get("quits_rate", float("nan"))) else float(row["quits_rate"]),
                        None if pd.isna(row.get("openings_rate", float("nan"))) else float(row["openings_rate"]),
                        None if pd.isna(row["beveridge_gap"]) else float(row["beveridge_gap"]),
                        None if pd.isna(row["hires_quits_ratio"]) else float(row["hires_quits_ratio"]),
                        now,
                    ],
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("jolts.persist_row_failed", date=str(series_date), error=str(exc))


def import_np():  # type: ignore[no-untyped-def]
    """Lazy numpy import context manager per evitare circular import."""
    import contextlib
    import numpy as _np
    @contextlib.contextmanager
    def _ctx():  # type: ignore[no-untyped-def]
        yield _np
    return _ctx()
