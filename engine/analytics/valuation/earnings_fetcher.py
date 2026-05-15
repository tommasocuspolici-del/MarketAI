"""EarningsFetcher — fetch e persist dei dati EPS per il Valuation Engine.

Fonti (in ordine di priorità):
  1. FRED SP500EPS → EPS aggregato S&P 500 trimestrale (per ^GSPC / SPY)
  2. DuckDB fundamentals_edgar → EPS da EDGAR XBRL già presenti (singoli ticker)
  3. yfinance → EPS fallback per singoli ticker

Pipeline: fetch → clean → validate → persist in fundamentals_edgar.

Regola 12: pipeline invariabile — nessun fetch inline in lettura.
Regola 8: numpy per calcoli.
Regola 29: gated da feature flag 'valuation_pe_engine'.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from shared.feature_flags import is_enabled
from shared.exceptions import FeatureDisabledError
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["EarningsFetcher", "EarningsSnapshot"]

log = get_logger(__name__)

# Ticker indice S&P 500 supportati dalla fonte FRED SP500EPS
_SP500_TICKERS = {"^GSPC", "SPY", "^SP500"}

# FRED series per EPS aggregato S&P 500 (dati trimestrali BEA)
_FRED_SP500EPS = "SP500EPS"

_TABLE = "fundamentals_edgar"


@dataclass(frozen=True)
class EarningsSnapshot:
    """Risultato aggregato EPS trailing 4Q per un ticker.

    Attributes:
        ticker:           Ticker di riferimento.
        as_of:            Data del calcolo.
        eps_trailing_4q:  Somma EPS ultimi 4 trimestri (trailing twelve months).
        eps_yoy_pct:      Crescita YoY in percentuale (None se non calcolabile).
        quarters_used:    Numero di trimestri usati per il calcolo (max 4).
        source:           Fonte del dato ('fred' | 'edgar' | 'yfinance' | 'none').
    """
    ticker:          str
    as_of:           date
    eps_trailing_4q: float | None
    eps_yoy_pct:     float | None
    quarters_used:   int
    source:          str


class EarningsFetcher:
    """Fetch e persist dei dati EPS per il Valuation Engine.

    Per ^GSPC/SPY usa FRED SP500EPS (EPS aggregato indice).
    Per singoli ticker legge da fundamentals_edgar (già popolato da EDGAR scheduler).
    Fallback: yfinance Ticker.info se tutto il resto manca.

    Usage::

        fetcher = EarningsFetcher(client=get_duckdb_client())
        snapshot = fetcher.get_trailing_eps("^GSPC")
        print(snapshot.eps_trailing_4q)
    """

    def __init__(
        self,
        client: DuckDBClient,
        fred_client: object = None,
    ) -> None:
        if not is_enabled("valuation_pe_engine"):
            raise FeatureDisabledError(
                "Feature 'valuation_pe_engine' is disabled. "
                "Abilita in config/feature_flags.yaml."
            )
        self._client = client
        self._fred = fred_client

    # ─── Public API ──────────────────────────────────────────────────────────

    def get_trailing_eps(self, ticker: str, as_of: date | None = None) -> EarningsSnapshot:
        """Restituisce EPS trailing 4Q per il ticker.

        Legge da DuckDB (già popolato) — non fa fetch in-band.
        Se non disponibile in DB, tenta yfinance come ultimo fallback.

        Args:
            ticker: Ticker (es. '^GSPC', 'AAPL').
            as_of:  Data di riferimento (default: oggi).

        Returns:
            EarningsSnapshot con eps_trailing_4q (None se non disponibile).
        """
        as_of = as_of or date.today()

        # 1. Leggi da fundamentals_edgar
        snapshot = self._read_from_edgar(ticker, as_of)
        if snapshot.eps_trailing_4q is not None:
            return snapshot

        # 2. Fallback yfinance (singola chiamata, risultato non persistito)
        return self._fetch_from_yfinance(ticker, as_of)

    def fetch_and_persist_sp500(self, lookback_years: int = 20) -> int:
        """Scarica EPS S&P 500 da FRED SP500EPS e persiste in fundamentals_edgar.

        Usato dal job scheduler (settimanale) per tenere aggiornati
        i dati EPS dell'indice. Solo per ticker ^GSPC/SPY.

        Args:
            lookback_years: Anni di storia da scaricare (default 20).

        Returns:
            Numero di righe inserite/aggiornate.
        """
        if self._fred is None:
            log.warning("earnings_fetcher.no_fred_client")
            return 0

        try:
            start = date.today() - timedelta(days=lookback_years * 365)
            df = self._fred.fetch_series(  # type: ignore[attr-defined]
                _FRED_SP500EPS,
                start=start,
                sort_order="asc",
                limit=lookback_years * 4 + 4,
            )
        except Exception as exc:
            log.warning("earnings_fetcher.fred_fetch_failed", error=str(exc)[:120])
            return 0

        if df.empty:
            log.info("earnings_fetcher.fred_empty", series=_FRED_SP500EPS)
            return 0

        rows = self._transform_fred_sp500eps(df)
        if not rows:
            return 0

        return self._persist_rows(rows)

    # ─── Internal helpers ────────────────────────────────────────────────────

    def _read_from_edgar(self, ticker: str, as_of: date) -> EarningsSnapshot:
        """Legge EPS quarterly da fundamentals_edgar e calcola trailing 4Q."""
        try:
            cutoff = as_of - timedelta(days=400)
            rows = self._client.query(
                "SELECT report_date, eps_diluted FROM fundamentals_edgar "
                "WHERE ticker = ? AND report_date::DATE BETWEEN ? AND ? "
                "AND period IN ('Q1','Q2','Q3','Q4') AND eps_diluted IS NOT NULL "
                "ORDER BY report_date DESC LIMIT 4",
                [ticker, cutoff, as_of],
            )
        except Exception as exc:
            log.debug("earnings_fetcher.edgar_read_failed ticker=%s: %s", ticker, str(exc)[:80])
            return EarningsSnapshot(ticker=ticker, as_of=as_of,
                                    eps_trailing_4q=None, eps_yoy_pct=None,
                                    quarters_used=0, source="none")

        if not rows:
            return EarningsSnapshot(ticker=ticker, as_of=as_of,
                                    eps_trailing_4q=None, eps_yoy_pct=None,
                                    quarters_used=0, source="none")

        eps_vals = np.array([float(r[1]) for r in rows], dtype=np.float64)
        trailing = float(np.sum(eps_vals))
        yoy = self._compute_yoy(ticker, as_of, trailing)

        return EarningsSnapshot(
            ticker=ticker,
            as_of=as_of,
            eps_trailing_4q=trailing,
            eps_yoy_pct=yoy,
            quarters_used=len(eps_vals),
            source="edgar",
        )

    def _fetch_from_yfinance(self, ticker: str, as_of: date) -> EarningsSnapshot:
        """Fallback: legge EPS da yfinance Ticker.info (non persiste)."""
        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
            ttm_eps = info.get("trailingEps")
            if ttm_eps is not None:
                return EarningsSnapshot(
                    ticker=ticker,
                    as_of=as_of,
                    eps_trailing_4q=float(ttm_eps),
                    eps_yoy_pct=None,
                    quarters_used=4,
                    source="yfinance",
                )
        except Exception as exc:
            log.debug("earnings_fetcher.yfinance_failed ticker=%s: %s", ticker, str(exc)[:80])

        return EarningsSnapshot(ticker=ticker, as_of=as_of,
                                eps_trailing_4q=None, eps_yoy_pct=None,
                                quarters_used=0, source="none")

    def _compute_yoy(self, ticker: str, as_of: date, eps_ttm: float) -> float | None:
        """Calcola YoY growth rispetto ai 4 trimestri dell'anno precedente."""
        try:
            prev_start = as_of - timedelta(days=765)
            prev_end   = as_of - timedelta(days=365)
            rows = self._client.query(
                "SELECT eps_diluted FROM fundamentals_edgar "
                "WHERE ticker = ? AND report_date::DATE BETWEEN ? AND ? "
                "AND period IN ('Q1','Q2','Q3','Q4') AND eps_diluted IS NOT NULL "
                "ORDER BY report_date DESC LIMIT 4",
                [ticker, prev_start, prev_end],
            )
            if len(rows) >= 2:
                prev_ttm = float(np.sum(np.array([float(r[0]) for r in rows],
                                                  dtype=np.float64)))
                if prev_ttm != 0:
                    return float((eps_ttm / prev_ttm - 1.0) * 100.0)
        except Exception:
            pass
        return None

    def _transform_fred_sp500eps(self, df: pd.DataFrame) -> list[dict]:
        """Converte DataFrame FRED SP500EPS in righe per fundamentals_edgar."""
        rows: list[dict] = []
        # FRED SP500EPS: EPS quarterly per S&P 500 come somma 4-quarter annualizzata
        # Ogni osservazione è una stima trimestrale del periodo
        col_ts = "ts" if "ts" in df.columns else "date"
        col_val = "value" if "value" in df.columns else df.columns[-1]

        for _, row in df.iterrows():
            try:
                ts_val = row[col_ts]
                val    = row[col_val]
                if pd.isna(val):
                    continue
                eps = float(val)
                report_dt = pd.Timestamp(ts_val).date()
                # Determina il quarter in base al mese
                month = report_dt.month
                if month <= 3:
                    period = "Q1"
                elif month <= 6:
                    period = "Q2"
                elif month <= 9:
                    period = "Q3"
                else:
                    period = "Q4"

                for tkr in ("^GSPC", "SPY"):
                    rows.append({
                        "ticker":      tkr,
                        "report_date": report_dt.isoformat(),
                        "period":      period,
                        "eps_diluted": eps,
                        "source":      "fred",
                    })
            except Exception as exc:
                log.debug("earnings_fetcher.transform_row_skip: %s", str(exc)[:60])
                continue

        return rows

    def _persist_rows(self, rows: list[dict]) -> int:
        """Persiste le righe in fundamentals_edgar con upsert."""
        if not rows:
            return 0
        df = pd.DataFrame(rows)
        inserted = 0
        try:
            with self._client.transaction() as conn:
                conn.register("_earnings_batch", df)
                conn.execute(
                    """
                    INSERT INTO fundamentals_edgar
                        (ticker, report_date, period, eps_diluted, source)
                    SELECT
                        ticker,
                        report_date::TIMESTAMPTZ,
                        period,
                        eps_diluted,
                        source
                    FROM _earnings_batch
                    ON CONFLICT (ticker, report_date, period) DO UPDATE SET
                        eps_diluted = excluded.eps_diluted,
                        source      = excluded.source
                    """
                )
                conn.unregister("_earnings_batch")
            inserted = len(df)
            log.info("earnings_fetcher.persisted", rows=inserted)
        except Exception as exc:
            log.warning("earnings_fetcher.persist_failed: %s", str(exc)[:120])
        return inserted
