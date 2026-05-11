"""FREDSimpleClient: client HTTP sync minimale per uso UI (v7.1.2).

Il ``FREDFetcher`` ufficiale e' async + pipeline completo (DataCleaner,
DualWriter, QualityReportRepository) — perfetto per lo scheduler ma
sovradimensionato per le UI Streamlit che servono solo "ultimo valore
di una serie".

Questo client:
  - Fa una GET a ``api.stlouisfed.org/fred/series/observations``.
  - Ritorna direttamente un DataFrame ``ts``, ``value``.
  - Niente cache su disco, niente persistenza DB. La cache TTL la fa
    Streamlit con ``@st.cache_data``.
  - Niente async — usato in path sincroni (UI body Streamlit).

Convenzioni v6.0 rispettate: type hints completi, structlog, no print,
API key da env (Regola 15), no magic number.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import date
from urllib.error import HTTPError, URLError

import pandas as pd

from shared.logger import get_logger

__version__ = "7.1.2"

__all__ = [
    "FredSimpleClient",
    "FredSimpleError",
    "FredKeyMissingError",
]

log = get_logger(__name__)

_FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
_DEFAULT_TIMEOUT_S = 10.0
_DEFAULT_LIMIT = 365


class FredSimpleError(Exception):
    """Errore generico del client FRED HTTP."""


class FredKeyMissingError(FredSimpleError):
    """API key FRED non configurata in environment."""


class FredSimpleClient:
    """Client HTTP minimale per FRED, ad uso delle pagine UI."""

    def __init__(
        self,
        api_key: str | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        # API key da env (Regola 15)
        self._api_key: str = (api_key or os.environ.get("FRED_API_KEY", "")).strip()
        self._timeout_s = float(timeout_s)

    @property
    def has_api_key(self) -> bool:
        """True se l'API key e' presente in environment."""
        return bool(self._api_key)

    def fetch_series(
        self,
        series_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int = _DEFAULT_LIMIT,
        sort_order: str = "desc",
    ) -> pd.DataFrame:
        """Fetch di una serie FRED.

        Args:
            series_id: ID FRED (es. 'DGS10', 'UNRATE').
            start: Data inizio (inclusive). None = dall'inizio della serie.
            end: Data fine (inclusive). None = ultimo disponibile.
            limit: Numero massimo di osservazioni (default 365).
            sort_order: 'desc' (piu' recenti prima) o 'asc'.

        Returns:
            DataFrame con colonne ``ts`` (datetime) e ``value`` (float).
            DataFrame vuoto se la serie non esiste o non ha osservazioni.

        Raises:
            FredKeyMissingError: Se ``FRED_API_KEY`` non e' in environment.
            FredSimpleError: Per errori HTTP o di parsing.
        """
        if not self._api_key:
            raise FredKeyMissingError(
                "FRED_API_KEY non configurata. "
                "Aggiungila al file .env e ricarica l'app."
            )

        params: dict[str, str] = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "limit": str(int(limit)),
            "sort_order": sort_order,
        }
        if start is not None:
            params["observation_start"] = start.isoformat()
        if end is not None:
            params["observation_end"] = end.isoformat()

        url = f"{_FRED_BASE_URL}?{urllib.parse.urlencode(params)}"

        try:
            with urllib.request.urlopen(url, timeout=self._timeout_s) as resp:
                if resp.status != 200:
                    raise FredSimpleError(
                        f"FRED HTTP {resp.status} per {series_id}"
                    )
                payload = json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            log.warning(
                "fred_simple.http_error",
                series_id=series_id,
                status=exc.code,
            )
            raise FredSimpleError(
                f"HTTP {exc.code} per {series_id}: {exc.reason}"
            ) from exc
        except URLError as exc:
            log.warning(
                "fred_simple.url_error",
                series_id=series_id,
                reason=str(exc.reason),
            )
            raise FredSimpleError(
                f"Errore rete per {series_id}: {exc.reason}"
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise FredSimpleError(
                f"Timeout/rete per {series_id}: {exc}"
            ) from exc

        observations = payload.get("observations") or []
        if not observations:
            return pd.DataFrame(columns=["ts", "value"])

        rows: list[dict[str, object]] = []
        for obs in observations:
            value_str = obs.get("value", ".")
            # FRED usa "." per dati mancanti
            if value_str == "." or value_str is None:
                continue
            try:
                value = float(value_str)
            except (TypeError, ValueError):
                continue
            rows.append({"ts": obs.get("date"), "value": value})

        if not rows:
            return pd.DataFrame(columns=["ts", "value"])

        df = pd.DataFrame(rows)
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
        df = df.dropna(subset=["ts"]).reset_index(drop=True)
        return df

    def fetch_latest(self, series_id: str) -> tuple[date, float] | None:
        """Ritorna (data, valore) dell'ultima osservazione disponibile.

        Returns None se la serie e' vuota o non disponibile.
        """
        try:
            df = self.fetch_series(series_id, limit=1, sort_order="desc")
        except FredSimpleError as exc:
            log.warning(
                "fred_simple.fetch_latest_failed",
                series_id=series_id,
                error=str(exc),
            )
            return None
        if df.empty:
            return None
        row = df.iloc[0]
        return row["ts"].date(), float(row["value"])

    def fetch_yield_curve(self) -> pd.DataFrame:
        """Snapshot della yield curve US Treasury — ultimo valore disponibile.

        Tenor mappati ai series_id FRED ufficiali:
          1M -> DGS1MO, 3M -> DGS3MO, 6M -> DGS6MO,
          1Y -> DGS1, 2Y -> DGS2, 5Y -> DGS5, 10Y -> DGS10, 30Y -> DGS30.

        Returns:
            DataFrame con colonne 'tenor', 'series_id', 'yield_pct',
            'observation_date'. Le righe per le quali FRED non ha dato
            disponibile sono escluse (non ritorna NaN).
        """
        tenors: list[tuple[str, str]] = [
            ("1M", "DGS1MO"),
            ("3M", "DGS3MO"),
            ("6M", "DGS6MO"),
            ("1Y", "DGS1"),
            ("2Y", "DGS2"),
            ("5Y", "DGS5"),
            ("10Y", "DGS10"),
            ("30Y", "DGS30"),
        ]
        rows: list[dict[str, object]] = []
        for tenor, series_id in tenors:
            latest = self.fetch_latest(series_id)
            if latest is None:
                continue
            obs_date, val = latest
            rows.append(
                {
                    "tenor": tenor,
                    "series_id": series_id,
                    "yield_pct": val,
                    "observation_date": obs_date,
                }
            )
        return pd.DataFrame(rows)
