"""OpenInterestAnalyzer — Settimana 5 Roadmap Unificata.

Classifica il sentiment istituzionale tramite le 4 combinazioni
Open Interest / Prezzo (Schwager, 1984 — "Technical Analysis of the Futures Markets").

Le 4 combinazioni OI/Prezzo:
  ┌───────────┬───────────┬──────────────────────────────────────────────────┐
  │ OI        │ Prezzo    │ Interpretazione                                  │
  ├───────────┼───────────┼──────────────────────────────────────────────────┤
  │ Aumenta ↑ │ Aumenta ↑ │ TREND_CONFIRMED_BULLISH                         │
  │           │           │ Nuovi longs entrano: trend forte, confermato     │
  ├───────────┼───────────┼──────────────────────────────────────────────────┤
  │ Aumenta ↑ │ Diminuisce│ DISTRIBUTION_BEARISH                            │
  │           │ ↓         │ Nuovi shorts entrano: distribuzione bearish      │
  ├───────────┼───────────┼──────────────────────────────────────────────────┤
  │ Diminuisce│ Aumenta ↑ │ SHORT_COVERING_WEAK_BULLISH                     │
  │ ↓         │           │ Shorts si coprono: rialzo debole, non confermato │
  ├───────────┼───────────┼──────────────────────────────────────────────────┤
  │ Diminuisce│ Diminuisce│ LIQUIDATION_POSSIBLE_BOTTOM                     │
  │ ↓         │ ↓         │ Longs liquidano: selling exhaustion vicino       │
  └───────────┴───────────┴──────────────────────────────────────────────────┘

Regola 2 (SRP): solo analisi OI/prezzo — non fa roll yield o basis.
Regola 8: numpy per tutti i calcoli.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from engine.futures_analysis.schemas import OISignal, OpenInterestResult
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["OpenInterestAnalyzer"]

log = get_logger(__name__)

# Finestra di confronto per classificare il cambiamento OI/prezzo
_CHANGE_WINDOW = 5    # barre (giorni lavorativi)
_MIN_BARS      = 10   # minimo per un'analisi significativa

# Soglia percentuale minima per classificare come "salita" o "discesa"
# Sotto questa soglia → consideriamo invariato (evita falsi segnali su rumore)
_CHANGE_THRESHOLD_PCT = 0.5   # 0.5%


class OpenInterestAnalyzer:
    """Classifica il segnale OI/prezzo per un ticker futures.

    Legge da `futures_ohlcv` (migration 007) le colonne `close` e `open_interest`.

    Usage::

        analyzer = OpenInterestAnalyzer(duckdb=get_duckdb_client())
        result = analyzer.analyze("CL=F")
    """

    def __init__(self, duckdb: DuckDBClient) -> None:
        self._db = duckdb

    def analyze(self, ticker: str, window: int = _CHANGE_WINDOW) -> OpenInterestResult:
        """Classifica il segnale OI/prezzo per un ticker futures.

        Args:
            ticker: Simbolo futures (es. 'CL=F').
            window: Finestra di confronto in barre (default: 5).

        Returns:
            OpenInterestResult con oi_signal e institutional_bias.
        """
        df = self._load_data(ticker)
        if df is None or len(df) < _MIN_BARS:
            log.warning("oi_analyzer.insufficient_data", ticker=ticker,
                        rows=len(df) if df is not None else 0)
            return _insufficient_result(ticker)

        return self._classify_from_df(ticker, df, window)

    def analyze_from_df(
        self, ticker: str, df: pd.DataFrame, window: int = _CHANGE_WINDOW
    ) -> OpenInterestResult:
        """Classifica il segnale OI/prezzo da DataFrame (per test senza DB).

        Args:
            ticker: Simbolo futures.
            df:     DataFrame con colonne 'close' e 'open_interest'.
            window: Finestra di confronto.

        Returns:
            OpenInterestResult.
        """
        if df is None or len(df) < _MIN_BARS:
            return _insufficient_result(ticker)
        return self._classify_from_df(ticker, df, window)

    # ─── Core classification ─────────────────────────────────────────────

    def _classify_from_df(
        self, ticker: str, df: pd.DataFrame, window: int
    ) -> OpenInterestResult:
        """Classificazione interna OI/prezzo."""
        closes = df["close"].to_numpy(dtype=np.float64)
        oi_col = "open_interest" if "open_interest" in df.columns else "oi"
        oi_raw = df[oi_col].to_numpy() if oi_col in df.columns else np.zeros(len(closes))

        # Rimuovi NaN da OI
        has_oi = not np.all(oi_raw == 0) and not np.all(np.isnan(oi_raw.astype(float)))

        current_close = float(closes[-1])
        prev_close    = float(closes[-min(window + 1, len(closes))])
        price_chg_pct = float((current_close - prev_close) / prev_close * 100.0) \
                        if prev_close > 0 else 0.0

        current_oi: int | None = None
        oi_chg_pct:  float | None = None
        oi_pct_rank: float | None = None

        if has_oi:
            oi_vals = oi_raw.astype(float)
            valid_oi = oi_vals[~np.isnan(oi_vals)]
            if len(valid_oi) >= 2:
                current_oi = int(valid_oi[-1])
                prev_oi    = float(valid_oi[-min(window + 1, len(valid_oi))])
                if prev_oi > 0:
                    oi_chg_pct = float((valid_oi[-1] - prev_oi) / prev_oi * 100.0)
                if len(valid_oi) > 5:
                    oi_pct_rank = float(np.mean(valid_oi <= valid_oi[-1]))

        # Classificazione delle 4 combinazioni
        oi_signal = _classify_signal(
            price_change_pct=price_chg_pct,
            oi_change_pct=oi_chg_pct,
            has_oi=has_oi,
        )

        # Bias istituzionale
        institutional_bias = _compute_institutional_bias(oi_signal, oi_pct_rank)

        log.info(
            "oi_analyzer.done",
            ticker=ticker,
            oi_signal=oi_signal.value,
            price_chg_pct=round(price_chg_pct, 2),
            oi_chg_pct=round(oi_chg_pct, 2) if oi_chg_pct else None,
            institutional_bias=institutional_bias,
        )

        return OpenInterestResult(
            ticker=ticker,
            computed_at=datetime.now(UTC),
            oi_signal=oi_signal,
            oi_current=current_oi,
            oi_change_pct=oi_chg_pct,
            price_change_pct=price_chg_pct,
            oi_pct_rank=oi_pct_rank,
            institutional_bias=institutional_bias,
        )

    def _load_data(self, ticker: str) -> pd.DataFrame | None:
        """Legge close e open_interest da futures_ohlcv."""
        try:
            rows = self._db.query(
                "SELECT ts, close, open_interest FROM futures_ohlcv "
                "WHERE ticker = ? AND contract_month = 'front' "
                "ORDER BY ts ASC",
                [ticker],
            )
            if not rows:
                return None
            df = pd.DataFrame(rows, columns=["ts", "close", "open_interest"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            return df.dropna(subset=["close"])
        except Exception as exc:
            log.warning("oi_analyzer.load_failed", ticker=ticker, error=str(exc)[:80])
            return None


# ─── Funzioni pure ───────────────────────────────────────────────────────────

def _classify_signal(
    price_change_pct: float,
    oi_change_pct:    float | None,
    has_oi:           bool,
) -> OISignal:
    """Classifica il segnale OI/prezzo secondo Schwager (1984).

    Se OI non disponibile → usa solo il trend prezzo come proxy.
    """
    if not has_oi or oi_change_pct is None:
        return OISignal.INSUFFICIENT_DATA

    thr = _CHANGE_THRESHOLD_PCT

    price_up = price_change_pct >  thr
    price_dn = price_change_pct < -thr
    oi_up    = oi_change_pct    >  thr
    oi_dn    = oi_change_pct    < -thr

    if oi_up and price_up:
        return OISignal.TREND_CONFIRMED_BULLISH
    if oi_up and price_dn:
        return OISignal.DISTRIBUTION_BEARISH
    if oi_dn and price_up:
        return OISignal.SHORT_COVERING_WEAK_BUY
    if oi_dn and price_dn:
        return OISignal.LIQUIDATION_POSSIBLE_BTM

    # Segnale ambiguo: una sola direzione non supera la soglia
    return OISignal.INSUFFICIENT_DATA


def _compute_institutional_bias(
    signal:      OISignal,
    oi_pct_rank: float | None,
) -> str:
    """Deduce il bias istituzionale dal segnale OI e dal rank storico.

    I large traders (istituzionali) tendono ad aggiungere posizioni
    (OI↑) nel senso del trend. OI↑ + prezzo↑ = longs istituzionali.
    """
    if signal == OISignal.TREND_CONFIRMED_BULLISH:
        # OI alto storicamente → maggiore probabilità di istituzionali long
        if oi_pct_rank is not None and oi_pct_rank > 0.7:
            return "long_bias"
        return "long_bias"
    if signal == OISignal.DISTRIBUTION_BEARISH:
        return "short_bias"
    if signal == OISignal.SHORT_COVERING_WEAK_BUY:
        return "neutral"   # shorts si coprono, non nuovi longs
    if signal == OISignal.LIQUIDATION_POSSIBLE_BTM:
        return "neutral"   # longs escono, non necessariamente shorts entrano
    return "neutral"


def _insufficient_result(ticker: str) -> OpenInterestResult:
    return OpenInterestResult(
        ticker=ticker,
        computed_at=datetime.now(UTC),
        oi_signal=OISignal.INSUFFICIENT_DATA,
        oi_current=None,
        oi_change_pct=None,
        price_change_pct=None,
        oi_pct_rank=None,
        institutional_bias="neutral",
    )
