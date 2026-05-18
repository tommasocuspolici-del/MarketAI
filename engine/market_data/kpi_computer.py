"""KPI computation utilities per LiveMarketService.

Estratto da live_market_service.py (ROADMAP_CODE_QUALITY_v1.0, Settimana 7, P6).
Contiene: dataclass, costanti, download yfinance, KpiComputer class.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

import pandas as pd

from engine.market_data.hardening.silent_failure_detector import SilentFailureError
from shared.logger import get_logger

log = get_logger(__name__)

# ─── Costanti KPI ───────────────────────────────────────────────────────────
_KPI_DEFINITIONS: list[tuple[str, str, str, str]] = [
    # (term_glossario, yf_ticker, valuta_attesa, format_spec)
    ("S&P 500",   "^GSPC",     "USD", ",.2f"),
    ("NASDAQ",    "^IXIC",     "USD", ",.2f"),
    ("DJIA",      "^DJI",      "USD", ",.2f"),
    ("FTSE MIB",  "FTSEMIB.MI","EUR", ",.2f"),
    ("VIX",       "^VIX",      "USD", ".2f"),
    ("DXY",       "DX-Y.NYB",  "USD", ".2f"),
    ("EUR/USD",   "EURUSD=X",  "USD", ".4f"),
    ("Gold",      "GC=F",      "USD", ",.2f"),
    ("WTI",       "CL=F",      "USD", ".2f"),
    ("Brent",     "BZ=F",      "USD", ".2f"),
    ("Silver",    "SI=F",      "USD", ".3f"),
    ("Nat Gas",   "NG=F",      "USD", ".3f"),
    ("Copper",    "HG=F",      "USD", ".3f"),
]

_TRADING_DAYS_1W: int = 5
_TRADING_DAYS_1M: int = 21


# ─── Dataclass ──────────────────────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class MarketKpi:
    """Singolo KPI di mercato fetchato live."""
    term: str
    yf_ticker: str
    value: float | None
    delta_pct: float | None
    currency: str
    format_spec: str
    is_override: bool = False
    is_stale: bool = False
    error: str = ""


@dataclass(frozen=True, slots=True)
class DeltaWindow:
    """Variazioni % su più finestre temporali per un asset."""
    term: str
    ticker: str
    delta_1w: float | None
    delta_1m: float | None
    delta_ytd: float | None
    last_price: float | None = None
    error: str = ""


@dataclass(slots=True)
class MarketSnapshot:
    """Snapshot completo dei KPI di mercato a un dato istante."""
    kpis: list[MarketKpi] = field(default_factory=list)
    fetched_at: float = 0.0
    is_stale: bool = False
    n_errors: int = 0
    is_unavailable: bool = False

    @classmethod
    def empty(cls, reason: str = "unavailable") -> MarketSnapshot:
        """Snapshot sentinel quando nessun dato è disponibile."""
        return cls(kpis=[], fetched_at=time.time(), is_unavailable=True, n_errors=0)

    @property
    def fetched_at_human(self) -> str:
        if self.fetched_at == 0:
            return "mai"
        delta = time.time() - self.fetched_at
        if delta < 60:
            return f"{int(delta)}s fa"
        if delta < 3600:
            return f"{int(delta / 60)}m fa"
        return f"{int(delta / 3600)}h fa"


# ─── Utilities ──────────────────────────────────────────────────────────────
def _safe_float(val: Any) -> float:
    """Converte in float in modo robusto (gestisce Series, DataFrame, scalari).

    Risolve un bug in yfinance con rate-limit o MultiIndex: ``iloc[-1]`` può
    restituire una ``pandas.Series`` invece di uno scalare, causando
    ``TypeError: cannot convert the series to <class 'float'>``.

    Args:
        val: Valore da convertire (scalare, numpy scalar, pandas Series/DataFrame).

    Returns:
        float. Se il valore è una Series/DataFrame vuota, restituisce ``float("nan")``.
    """
    import numpy as np  # noqa: PLC0415 — lazy import to avoid startup cost
    if hasattr(val, "dropna"):
        clean = val.dropna()
        if hasattr(clean, "iloc") and len(clean) > 0:
            v = clean.iloc[-1]
            return float(v) if not hasattr(v, "__len__") else float(v.iloc[-1])
        return float("nan")
    if hasattr(val, "item"):
        return float(val.item())
    return float(val)


def build_unavailable_kpis(reason: str) -> list[MarketKpi]:
    """Placeholder KPIs per quando il fetch è impossibile."""
    return [
        MarketKpi(
            term=term, yf_ticker=yf_ticker, value=None, delta_pct=None,
            currency=currency, format_spec=fmt, error=reason,
        )
        for term, yf_ticker, currency, fmt in _KPI_DEFINITIONS
    ]


# ─── yfinance download ──────────────────────────────────────────────────────

_CACHE_DIR = None  # lazy-initialized in _get_yf_session

_YF_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

_RETRY_DELAYS: tuple[float, ...] = (0.0, 3.0, 8.0)


def _get_yf_session() -> object:
    """Ritorna una CachedSession requests_cache con TTL uguale al live_market_ttl.

    Trasparente per yfinance: intercetta le chiamate HTTP e serve dalla cache
    locale (SQLite in DATA_DIR/cache/) per evitare rate-limit di Yahoo Finance.
    """
    import requests_cache
    from shared.constants import DATA_DIR
    from shared.config.operational_config import OP_CONFIG

    cache_path = DATA_DIR / "cache" / "yf_http_cache"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    session = requests_cache.CachedSession(
        str(cache_path),
        expire_after=OP_CONFIG.cache.live_market_ttl_s,
        allowable_methods=("GET",),
        stale_if_error=True,
    )
    session.headers.update(_YF_HEADERS)
    return session


def download_market_data(tickers_list: list[str]) -> pd.DataFrame | None:
    """Scarica dati yfinance per i ticker dati, con HTTP cache e retry su rate-limit.

    Strategia:
      1. Usa CachedSession (requests_cache) per evitare richieste duplicate → YFRateLimitError.
      2. Fino a 3 tentativi con backoff (0s / 3s / 8s) se la risposta è vuota o rate-limited.
      3. Retry su incompatibilità API (TypeError → fallback senza multi_level_index).
    """
    try:
        import yfinance as yf
        from yfinance.exceptions import YFRateLimitError
    except ImportError:
        return None

    try:
        session = _get_yf_session()
    except Exception as exc:  # noqa: BLE001 — requests_cache non installato
        log.warning("yfinance.cached_session_unavailable", error=str(exc)[:120])
        session = None

    import time as _time

    def _attempt(use_multi_level: bool) -> pd.DataFrame | None:
        kwargs: dict = dict(
            period="5d", interval="1d",
            progress=False, auto_adjust=True,
        )
        if use_multi_level:
            kwargs["multi_level_index"] = True
        if session is not None:
            kwargs["session"] = session
        try:
            data = yf.download(tickers=tickers_list, **kwargs)
            return data if data is not None and not data.empty else None
        except YFRateLimitError:
            return None  # segnale per il retry loop
        except TypeError:
            return False  # segnale per passare a use_multi_level=False
        except (OSError, ValueError, KeyError) as exc:
            log.warning("yfinance.download_failed", error=str(exc)[:120])
            return None

    use_multi = True
    for i, delay in enumerate(_RETRY_DELAYS):
        if delay:
            _time.sleep(delay)
        result = _attempt(use_multi)
        if result is False:
            # TypeError: API incompatibile, riprova senza multi_level_index
            use_multi = False
            result = _attempt(use_multi)
        if result is not None and result is not False:
            return result
        if i < len(_RETRY_DELAYS) - 1:
            log.warning("yfinance.download_empty_retrying", attempt=i + 1, delay=_RETRY_DELAYS[i + 1])

    log.warning("yfinance.download_failed_all_retries", tickers=len(tickers_list))
    return None


# ─── KpiComputer ────────────────────────────────────────────────────────────
class KpiComputer:
    """Estrae KPI da un DataFrame yfinance con fallback e override."""

    def __init__(
        self,
        *,
        override_store: Any,
        sanity: Any,
        get_ws_price_fn: Callable[[str], float | None],
        lookup_cached_fn: Callable[[str], MarketKpi | None],
    ) -> None:
        self._override_store = override_store
        self._sanity = sanity
        self._get_ws_price = get_ws_price_fn
        self._lookup_cached = lookup_cached_fn

    def extract_kpi(
        self, *, data: Any, term: str, yf_ticker: str, currency: str, fmt: str,
    ) -> MarketKpi:
        """Estrae il KPI per un singolo ticker dal DataFrame multi-ticker yf.

        Percorso prioritario:
          1. Prezzo WebSocket live (se WS attivo e recente).
          2. Prezzo dal DataFrame yfinance (bulk download).
          3. Fallback fast_info singolo ticker.
          4. Cache locale stale.
          5. MarketKpi con error=... (mai None, mai eccezione propagata).

        Args:
            data: DataFrame yfinance (MultiIndex o piano) da ``yf.download``.
            term: Chiave glossario (es. ``"S&P 500"``).
            yf_ticker: Ticker Yahoo Finance (es. ``"^GSPC"``).
            currency: Valuta display (es. ``"USD"``, ``"EUR"``).
            fmt: Format spec Python (es. ``",.2f"``).

        Returns:
            MarketKpi con valore, delta_pct, eventuali flag is_stale/is_override.
            Non solleva mai eccezioni: errori sono catturati e messi in kpi.error.
        """
        ws_price = self._get_ws_price(yf_ticker)
        if ws_price is not None:
            final_value, is_override = self._override_store.resolve("price", term, ws_price)
            return MarketKpi(
                term=term, yf_ticker=yf_ticker, value=final_value,
                delta_pct=None, currency=currency, format_spec=fmt, is_override=is_override,
            )
        try:
            ticker_data = self.get_ticker_frame(data, yf_ticker)
            if ticker_data is None:
                raise SilentFailureError("yfinance", f"no frame for {yf_ticker}")
            if ticker_data.empty:
                raise SilentFailureError("yfinance", f"empty data for {yf_ticker}")
            ticker_data = ticker_data.dropna(how="all")
            if ticker_data.empty:
                raise SilentFailureError("yfinance", f"no rows for {yf_ticker}")
            close_col = "Close" if "Close" in ticker_data.columns else "close"
            if close_col not in ticker_data.columns:
                raise SilentFailureError("yfinance", f"no Close column for {yf_ticker}")
            last_close = _safe_float(ticker_data[close_col].iloc[-1])
            prev_close = (
                _safe_float(ticker_data[close_col].iloc[-2])
                if len(ticker_data) >= 2 else last_close
            )
            violations = self._sanity.check_price_data(yf_ticker, last_close, prev_close=prev_close)
            if not self._sanity.is_safe_to_store(violations):
                cached = self._lookup_cached(term)
                if cached is not None:
                    return MarketKpi(
                        term=term, yf_ticker=yf_ticker, value=cached.value,
                        delta_pct=cached.delta_pct, currency=cached.currency,
                        format_spec=fmt, is_stale=True, error="sanity violation, using last good value",
                    )
            api_delta_pct: float | None = None
            if prev_close > 0:
                api_delta_pct = (last_close - prev_close) / prev_close
            final_value, is_override = self._override_store.resolve("price", term, last_close)
            return MarketKpi(
                term=term, yf_ticker=yf_ticker, value=final_value,
                delta_pct=api_delta_pct, currency=currency, format_spec=fmt, is_override=is_override,
            )
        except SilentFailureError as exc:
            price_fb, delta_fb = self.fetch_fast_info_fallback(yf_ticker)
            if price_fb is not None:
                log.info("yfinance.fast_info_fallback_used", ticker=yf_ticker)
                return MarketKpi(
                    term=term, yf_ticker=yf_ticker, value=price_fb,
                    delta_pct=delta_fb, currency=currency, format_spec=fmt,
                )
            cached = self._lookup_cached(term)
            if cached is not None:
                return MarketKpi(
                    term=term, yf_ticker=yf_ticker, value=cached.value,
                    delta_pct=cached.delta_pct, currency=cached.currency,
                    format_spec=fmt, is_stale=True, error=f"silent_failure: {exc.reason[:80]}",
                )
            return MarketKpi(
                term=term, yf_ticker=yf_ticker, value=None, delta_pct=None,
                currency=currency, format_spec=fmt, error=f"silent_failure: {exc.reason[:80]}",
            )
        except (KeyError, ValueError, IndexError, AttributeError) as exc:
            cached = self._lookup_cached(term)
            if cached is not None:
                return MarketKpi(
                    term=term, yf_ticker=yf_ticker, value=cached.value,
                    delta_pct=cached.delta_pct, currency=cached.currency,
                    format_spec=fmt, is_stale=True, error=f"parse_error: {str(exc)[:80]}",
                )
            return MarketKpi(
                term=term, yf_ticker=yf_ticker, value=None, delta_pct=None,
                currency=currency, format_spec=fmt, error=f"parse_error: {str(exc)[:80]}",
            )

    @staticmethod
    def get_ticker_frame(data: Any, yf_ticker: str) -> Any:
        """Estrae il sotto-frame per un singolo ticker (gestisce MultiIndex yfinance).

        Risolve il BUG-004: yfinance >= 0.2.x restituisce un DataFrame MultiIndex
        ``(field, ticker)``. Il vecchio accesso diretto ``data[ticker]`` tornava
        sempre il primo ticker del MultiIndex, non quello richiesto.

        Args:
            data: DataFrame yfinance (MultiIndex a due livelli o a colonne piane).
            yf_ticker: Ticker da estrarre (es. ``"^GSPC"``, ``"^VIX"``).

        Returns:
            DataFrame con colonne piane (es. ``"Close"``) relativo al ticker,
            oppure ``None`` se il ticker non è presente o il dato è vuoto.
        """
        if data is None or data.empty:
            return None
        if isinstance(data.columns, pd.MultiIndex):
            lvl1 = data.columns.get_level_values(1).tolist()
            lvl0 = data.columns.get_level_values(0).tolist()
            if yf_ticker in lvl1:
                try:
                    return data.xs(yf_ticker, axis=1, level=1)
                except (KeyError, TypeError):
                    pass
            if yf_ticker in lvl0:
                try:
                    return data[yf_ticker]
                except (KeyError, TypeError):
                    pass
            return None
        if "Close" in data.columns or "close" in data.columns:
            return data
        return None

    @staticmethod
    def fetch_fast_info_fallback(yf_ticker: str) -> tuple[float | None, float | None]:
        """Fallback singolo ticker via yf.Ticker.fast_info."""
        try:
            import yfinance as yf  # noqa: PLC0415
            t = yf.Ticker(yf_ticker)
            fi = t.fast_info
            price = getattr(fi, "last_price", None)
            prev = getattr(fi, "previous_close", None)
            if price is None or price != price:
                return None, None
            price_f = float(price)
            delta: float | None = None
            if prev is not None and float(prev) > 0:
                delta = (price_f - float(prev)) / float(prev)
            return price_f, delta
        except Exception as exc:  # noqa: BLE001
            log.warning("[RECOVER] kpi_computer.fetch_fast_info_fallback: %s: %s", yf_ticker, type(exc).__name__)
            return None, None
