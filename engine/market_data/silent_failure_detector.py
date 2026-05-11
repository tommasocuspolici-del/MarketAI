"""SilentFailureDetector — Settimana 9 Hardening.

Rileva failure silenziosi nei feed dati (^VIX, futures, FRED).
Un "silent failure" è quando il dato viene ricevuto ma è stale
(stesso valore per N giorni) o anomalo senza produrre un'eccezione.

Tipici casi:
  · yfinance restituisce dati cached/stale per ^VIX (stesso prezzo x gg)
  · FRED non aggiorna la serie per festività USA
  · Futures con volume = 0 (mercato chiuso, ma dato presente)

Integrazione con DataQualityReport (Rule 26):
  Ogni serie con silent failure viene marcata con quality_score < 0.5.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared.logger import get_logger

__version__ = "1.0.0"
__all__ = ["SilentFailureDetector", "SilentFailureResult"]

log = get_logger(__name__)

_DEFAULT_STALE_WINDOW = 3    # N giorni identici → stale
_DEFAULT_ZERO_VOLUME_WINDOW = 2  # N giorni volume=0 → silent failure


@dataclass(frozen=True)
class SilentFailureResult:
    """Risultato del check silent failure su una serie."""
    series_id:        str
    failure_detected: bool
    failure_type:     str | None   # 'stale' | 'zero_volume' | 'missing' | None
    stale_days:       int
    latest_value:     float | None
    quality_score:    float           # [0, 1] — 0 = dato inutilizzabile
    message:          str


class SilentFailureDetector:
    """Rileva failure silenziosi nei feed dati.

    Usage::

        detector = SilentFailureDetector()
        result = detector.check_ohlcv(df=vix_df, series_id="^VIX")
        if result.failure_detected:
            log.warning("silent_failure", series=result.series_id)
    """

    def __init__(
        self,
        stale_window: int = _DEFAULT_STALE_WINDOW,
        zero_vol_window: int = _DEFAULT_ZERO_VOLUME_WINDOW,
    ) -> None:
        self._stale_window   = stale_window
        self._zero_vol_window = zero_vol_window

    def check_ohlcv(
        self,
        df:        pd.DataFrame,
        series_id: str,
    ) -> SilentFailureResult:
        """Controlla un DataFrame OHLCV per silent failures.

        Args:
            df:        DataFrame con colonne close, volume (opzionale), ts.
            series_id: Identificatore della serie per logging.

        Returns:
            SilentFailureResult con failure_type e quality_score.
        """
        if df is None or df.empty:
            return SilentFailureResult(
                series_id=series_id, failure_detected=True,
                failure_type="missing", stale_days=0,
                latest_value=None, quality_score=0.0,
                message=f"{series_id}: DataFrame vuoto o None.",
            )

        closes = df["close"].dropna().to_numpy(dtype=np.float64)
        if len(closes) == 0:
            return SilentFailureResult(
                series_id=series_id, failure_detected=True,
                failure_type="missing", stale_days=0,
                latest_value=None, quality_score=0.0,
                message=f"{series_id}: nessun valore close valido.",
            )

        latest = float(closes[-1])

        # ── Check stale: stesso valore per N giorni ───────────────────────
        window = min(self._stale_window, len(closes))
        recent = closes[-window:]
        stale_days = int(np.sum(np.isclose(recent, latest, rtol=1e-6)))

        if stale_days >= self._stale_window:
            quality = max(0.1, 1.0 - (stale_days / (self._stale_window * 2)))
            log.warning(
                "silent_failure.stale", series_id=series_id,
                stale_days=stale_days, value=round(latest, 4),
            )
            return SilentFailureResult(
                series_id=series_id, failure_detected=True,
                failure_type="stale", stale_days=stale_days,
                latest_value=latest, quality_score=quality,
                message=(
                    f"{series_id}: valore {latest:.4f} invariato "
                    f"per {stale_days} giorni. Possibile feed stale."
                ),
            )

        # ── Check volume zero ─────────────────────────────────────────────
        if "volume" in df.columns:
            vols = df["volume"].dropna().to_numpy()
            if len(vols) >= self._zero_vol_window:
                recent_vols = vols[-self._zero_vol_window:]
                if np.all(recent_vols == 0):
                    log.warning(
                        "silent_failure.zero_volume", series_id=series_id,
                        days=self._zero_vol_window,
                    )
                    return SilentFailureResult(
                        series_id=series_id, failure_detected=True,
                        failure_type="zero_volume",
                        stale_days=int(self._zero_vol_window),
                        latest_value=latest, quality_score=0.4,
                        message=(
                            f"{series_id}: volume = 0 per "
                            f"{self._zero_vol_window} giorni. Mercato chiuso?"
                        ),
                    )

        return SilentFailureResult(
            series_id=series_id, failure_detected=False,
            failure_type=None, stale_days=stale_days,
            latest_value=latest, quality_score=1.0,
            message=f"{series_id}: OK — nessun silent failure rilevato.",
        )

    def check_macro_series(
        self,
        df:        pd.DataFrame,
        series_id: str,
        max_stale_days: int = 35,   # FRED mensile: OK fino a 35 gg
    ) -> SilentFailureResult:
        """Controlla una serie macro FRED per staleness.

        Args:
            df:             DataFrame con colonne ts, value.
            series_id:      ID serie FRED.
            max_stale_days: Massimo giorni senza aggiornamento prima del warning.

        Returns:
            SilentFailureResult.
        """
        if df is None or df.empty:
            return SilentFailureResult(
                series_id=series_id, failure_detected=True,
                failure_type="missing", stale_days=0,
                latest_value=None, quality_score=0.0,
                message=f"{series_id}: serie FRED vuota.",
            )

        col_ts = "ts" if "ts" in df.columns else df.columns[0]
        col_val = "value" if "value" in df.columns else df.columns[-1]

        vals = df[col_val].dropna()
        if vals.empty:
            return SilentFailureResult(
                series_id=series_id, failure_detected=True,
                failure_type="missing", stale_days=0,
                latest_value=None, quality_score=0.0,
                message=f"{series_id}: nessun valore valido.",
            )

        latest_val = float(vals.iloc[-1])

        # Stima giorni dall'ultimo aggiornamento
        if col_ts in df.columns:
            try:
                latest_ts = pd.to_datetime(df[col_ts].iloc[-1])
                now_ts    = pd.Timestamp.now(tz="UTC")
                if latest_ts.tzinfo is None:
                    latest_ts = latest_ts.tz_localize("UTC")
                days_since = (now_ts - latest_ts).days
            except Exception:
                days_since = 0
        else:
            days_since = 0

        if days_since > max_stale_days:
            log.warning(
                "silent_failure.macro_stale", series_id=series_id,
                days_since=days_since, max=max_stale_days,
            )
            return SilentFailureResult(
                series_id=series_id, failure_detected=True,
                failure_type="stale", stale_days=days_since,
                latest_value=latest_val, quality_score=0.5,
                message=(
                    f"{series_id}: ultimo aggiornamento {days_since}gg fa "
                    f"(max: {max_stale_days}gg). Serie potenzialmente stale."
                ),
            )

        return SilentFailureResult(
            series_id=series_id, failure_detected=False,
            failure_type=None, stale_days=days_since,
            latest_value=latest_val, quality_score=1.0,
            message=f"{series_id}: OK — aggiornato {days_since}gg fa.",
        )
