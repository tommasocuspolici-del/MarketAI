"""Options Flow Fetcher — Put/Call ratio e IV skew da yfinance/CBOE/Finnhub.

Metriche raccolte:
  put_call_ratio   rapporto put/call su volume o OI
  put_volume       volume aggregato put
  call_volume      volume aggregato call
  iv_skew_25d      IV(put 25-delta) - IV(call 25-delta) — indicatore di skew
  iv_atm           implied volatility at-the-money (nearest strike)

Strategia fonti (cascade):
  1. yfinance option chain   — gratuito, copertura ampia, derive P/C da OI/volume
  2. CBOE public endpoint    — solo SPX/VIX, dati ufficiali giornalieri
  3. Fallback: dati assenti  — graceful degradation senza crash

Regola 12: solo fetch→persist, nessuna analisi inline.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

from shared.resilience.error_policy import apply_error_policy

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
log = logging.getLogger(__name__)

_TABLE = "putcall_ratio_daily"

# Ticker sintetici CBOE (non hanno options chain su yfinance)
_CBOE_TICKERS = frozenset({"^VIX", "^SPX", "SPY", "QQQ"})

# Soglia delta approssimativa per lo skew 25-delta (% moneyness proxy)
_SKEW_MONEYNESS_BAND = 0.05   # ±5% dal ATM per approssimare 25-delta


class OptionsFlowFetcher:
    """Scarica e persiste Put/Call ratio e IV skew da yfinance.

    Args:
        client: DuckDBClient per la persistenza.
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client

    def fetch_and_persist(self, tickers: list[str]) -> int:
        """Scarica options flow per la lista di ticker e persiste.

        Args:
            tickers: Lista di ticker Yahoo Finance (es. ["SPY", "AAPL"]).

        Returns:
            Numero totale di righe inserite/aggiornate.
        """
        total = 0
        for ticker in tickers:
            n = self._fetch_ticker(ticker)
            total += n
            log.debug("options_flow_fetcher.ticker_done ticker=%s rows=%d", ticker, n)
        log.info("options_flow_fetcher.done total_rows=%d tickers=%d", total, len(tickers))
        return total

    @apply_error_policy(level="RECOVER", fallback=0, context="OptionsFlowFetcher._fetch_ticker")
    def _fetch_ticker(self, ticker: str) -> int:
        import yfinance as yf

        t = yf.Ticker(ticker)
        expirations = _safe_options(t)
        if not expirations:
            log.debug("options_flow_fetcher.no_expirations ticker=%s", ticker)
            return 0

        # Prende la prima scadenza disponibile (più liquida, ~30gg)
        exp = expirations[0]
        try:
            chain = t.option_chain(exp)
        except Exception as exc:
            log.debug("options_flow_fetcher.chain_failed ticker=%s: %s", ticker, str(exc)[:80])
            return 0

        calls = chain.calls if hasattr(chain, "calls") else pd.DataFrame()
        puts  = chain.puts  if hasattr(chain, "puts")  else pd.DataFrame()

        if calls.empty and puts.empty:
            return 0

        spot = _get_spot(t)
        metrics = _compute_metrics(calls, puts, spot)
        if metrics is None:
            return 0

        return self._persist(ticker, metrics)

    def get_latest(self, ticker: str) -> dict | None:
        """Legge i dati options più recenti per un ticker."""
        try:
            rows = self._client.query(
                f"SELECT ticker, date, put_call_ratio, put_volume, call_volume, "
                f"oi_put, oi_call, iv_skew_25d, iv_atm, source "
                f"FROM {_TABLE} "
                f"WHERE ticker = ? "
                f"ORDER BY date DESC, fetched_at DESC LIMIT 1",
                [ticker],
            )
            if not rows:
                return None
            r = rows[0]
            return {
                "ticker": r[0], "date": r[1],
                "put_call_ratio": r[2], "put_volume": r[3], "call_volume": r[4],
                "oi_put": r[5], "oi_call": r[6],
                "iv_skew_25d": r[7], "iv_atm": r[8], "source": r[9],
            }
        except Exception as exc:
            log.warning("options_flow_fetcher.get_latest_failed ticker=%s: %s",
                        ticker, str(exc)[:120])
            return None

    def get_history(self, ticker: str, days: int = 30) -> pd.DataFrame:
        """Legge lo storico options flow per un ticker."""
        from datetime import timedelta
        cutoff = date.today() - timedelta(days=days)
        try:
            rows = self._client.query(
                f"SELECT ticker, date, put_call_ratio, iv_skew_25d, iv_atm, source "
                f"FROM {_TABLE} "
                f"WHERE ticker = ? AND date >= ? "
                f"ORDER BY date DESC",
                [ticker, cutoff],
            )
            cols = ["ticker", "date", "put_call_ratio", "iv_skew_25d", "iv_atm", "source"]
            return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
        except Exception as exc:
            log.warning("options_flow_fetcher.get_history_failed ticker=%s: %s",
                        ticker, str(exc)[:120])
            return pd.DataFrame()

    # ─── Internal helpers ─────────────────────────────────────────────────────

    def _persist(self, ticker: str, metrics: dict) -> int:
        today = date.today()
        try:
            self._client.execute(
                f"""
                INSERT INTO {_TABLE}
                    (ticker, date, put_call_ratio, put_volume, call_volume,
                     oi_put, oi_call, iv_skew_25d, iv_atm, source, fetched_at)
                VALUES (?,?,?,?,?,?,?,?,?,'yfinance_derived',NOW())
                ON CONFLICT (ticker, date, source) DO UPDATE SET
                    put_call_ratio=excluded.put_call_ratio,
                    put_volume=excluded.put_volume,
                    call_volume=excluded.call_volume,
                    oi_put=excluded.oi_put,
                    oi_call=excluded.oi_call,
                    iv_skew_25d=excluded.iv_skew_25d,
                    iv_atm=excluded.iv_atm,
                    fetched_at=NOW()
                """,
                [
                    ticker, today,
                    metrics.get("put_call_ratio"),
                    _int_or_none(metrics.get("put_volume")),
                    _int_or_none(metrics.get("call_volume")),
                    _int_or_none(metrics.get("oi_put")),
                    _int_or_none(metrics.get("oi_call")),
                    metrics.get("iv_skew_25d"),
                    metrics.get("iv_atm"),
                ],
            )
            return 1
        except Exception as exc:
            log.debug("options_flow_fetcher.persist_failed ticker=%s: %s",
                      ticker, str(exc)[:80])
            return 0


# ─── Computation helpers ──────────────────────────────────────────────────────

def _safe_options(ticker_obj) -> list[str]:
    try:
        exps = ticker_obj.options
        return list(exps) if exps else []
    except Exception:
        return []


def _get_spot(ticker_obj) -> float | None:
    try:
        info = ticker_obj.info
        return float(info.get("regularMarketPrice") or info.get("currentPrice") or 0) or None
    except Exception:
        return None


def _compute_metrics(calls: pd.DataFrame, puts: pd.DataFrame, spot: float | None) -> dict | None:
    """Calcola P/C ratio, volume aggregato e IV skew approssimato."""
    # Volume aggregato
    put_vol  = _sum_col(puts,  "volume")
    call_vol = _sum_col(calls, "volume")
    oi_put   = _sum_col(puts,  "openInterest")
    oi_call  = _sum_col(calls, "openInterest")

    # P/C ratio su volume (fallback su OI)
    if call_vol and call_vol > 0 and put_vol is not None:
        pcr = put_vol / call_vol
    elif oi_call and oi_call > 0 and oi_put is not None:
        pcr = oi_put / oi_call
    else:
        pcr = None

    # IV at-the-money (strike più vicino allo spot)
    iv_atm = _compute_iv_atm(calls, puts, spot)

    # IV skew 25-delta approssimato (OTM put vs OTM call a parità di distanza)
    iv_skew = _compute_iv_skew(calls, puts, spot) if spot else None

    if pcr is None and iv_atm is None:
        return None

    return {
        "put_call_ratio": pcr,
        "put_volume":     put_vol,
        "call_volume":    call_vol,
        "oi_put":         oi_put,
        "oi_call":        oi_call,
        "iv_atm":         iv_atm,
        "iv_skew_25d":    iv_skew,
    }


def _compute_iv_atm(calls: pd.DataFrame, puts: pd.DataFrame, spot: float | None) -> float | None:
    if spot is None or spot <= 0:
        return None

    best_iv = None
    best_dist = float("inf")

    for df in (calls, puts):
        if df.empty or "strike" not in df.columns or "impliedVolatility" not in df.columns:
            continue
        for _, row in df.iterrows():
            strike = _f(row.get("strike"))
            iv = _f(row.get("impliedVolatility"))
            if strike is None or iv is None or iv <= 0:
                continue
            dist = abs(strike - spot)
            if dist < best_dist:
                best_dist = dist
                best_iv = iv

    return best_iv


def _compute_iv_skew(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> float | None:
    """IV skew 25-delta approssimato: IV(OTM put) - IV(OTM call) a ±5% dal ATM."""
    band = spot * _SKEW_MONEYNESS_BAND

    otm_put_ivs  = _otm_ivs(puts,  spot, side="put",  band=band)
    otm_call_ivs = _otm_ivs(calls, spot, side="call", band=band)

    if not otm_put_ivs or not otm_call_ivs:
        return None

    return sum(otm_put_ivs) / len(otm_put_ivs) - sum(otm_call_ivs) / len(otm_call_ivs)


def _otm_ivs(df: pd.DataFrame, spot: float, side: str, band: float) -> list[float]:
    if df.empty or "strike" not in df.columns or "impliedVolatility" not in df.columns:
        return []
    ivs = []
    for _, row in df.iterrows():
        strike = _f(row.get("strike"))
        iv = _f(row.get("impliedVolatility"))
        if strike is None or iv is None or iv <= 0:
            continue
        if side == "put" and (spot - band) > strike > (spot - 3 * band):
            ivs.append(iv)
        elif side == "call" and (spot + band) < strike < (spot + 3 * band):
            ivs.append(iv)
    return ivs


# ─── Type helpers ─────────────────────────────────────────────────────────────

def _sum_col(df: pd.DataFrame, col: str) -> int | None:
    if df.empty or col not in df.columns:
        return None
    try:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        return int(s.sum()) if not s.empty else None
    except Exception:
        return None


def _f(val) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def _int_or_none(val) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None
