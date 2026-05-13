"""LiveMarketService: dati di mercato real-time con cache TTL e force refresh.

Risolve due problemi v6:
  1. KPI Mercato hardcoded -> ora vengono fetchati live da yfinance.
  2. Nessun modo di forzare refresh -> ``refresh_now()`` invalida la cache
     e rifa fetch immediato.

Gestisce silent failures e applica override manuali (Rule 43, 47).

Pattern d'uso::

    svc = get_live_market_service()
    snap = svc.get_kpi_snapshot()  # cached up to TTL_SECONDS
    snap = svc.refresh_now()       # forza re-fetch immediato

Funziona offline: se yfinance fallisce o non e' installato, ritorna
l'ultima cache disponibile (con flag is_stale=True). Se la cache e'
vuota, ritorna placeholder con flag is_unavailable=True che le UI
sanno gestire.

Bugfix v7.1.1:
  · Race condition #1: get_live_market_service() ora usa lru_cache(maxsize=1)
    -> singleton thread-safe garantito da CPython.
  · Race condition #2: get_kpi_snapshot() ora rilascia il lock SOLO dopo
    aver verificato che nessun altro thread sta gia' rifacendo il fetch.
    Pattern double-checked locking + refresh_in_progress flag.
  · Bug delta: con override attivo il delta_pct ora rispecchia il movimento
    REALE del prezzo API, non il delta artificiale dell'override.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from threading import Condition, Lock
from typing import Any

import pandas as pd

from engine.market_data.hardening.sanity_checker import SanityChecker
from engine.market_data.hardening.silent_failure_detector import (
    SilentFailureError,
)
from personal.data_entry.override_store import ManualOverrideStore
from shared.logger import get_logger

__version__ = "9.0.0"

__all__ = [
    "DeltaWindow",
    "LiveMarketService",
    "MarketKpi",
    "MarketSnapshot",
    "fetch_delta_windows",
    "get_live_market_service",
]

log = get_logger(__name__)

# TTL della cache in secondi. Sotto questo, get_kpi_snapshot ritorna cache.
_TTL_SECONDS = 60.0

# Mappa term-glossario -> ticker yfinance.
# I ticker sono quelli ufficiali di Yahoo Finance.
_KPI_DEFINITIONS: list[tuple[str, str, str, str]] = [
    # (term_glossario, yf_ticker,    valuta_attesa, format_spec)
    ("S&P 500",   "^GSPC",  "USD", ",.2f"),
    ("NASDAQ",    "^IXIC",  "USD", ",.2f"),
    ("DJIA",      "^DJI",   "USD", ",.2f"),
    ("FTSE MIB",  "FTSEMIB.MI", "EUR", ",.2f"),
    ("VIX",       "^VIX",   "USD", ".2f"),
    ("DXY",       "DX-Y.NYB", "USD", ".2f"),
    ("EUR/USD",   "EURUSD=X", "USD", ".4f"),
    ("Gold",      "GC=F",   "USD", ",.2f"),
    ("WTI",       "CL=F",   "USD", ".2f"),
    ("Brent",     "BZ=F",   "USD", ".2f"),
    ("Silver",    "SI=F",   "USD", ".3f"),
    ("Nat Gas",   "NG=F",   "USD", ".3f"),
    ("Copper",    "HG=F",   "USD", ".3f"),
]


@dataclass(frozen=True, slots=True)
class MarketKpi:
    """Singolo KPI di mercato fetchato live."""

    term: str               # chiave glossario
    yf_ticker: str
    value: float | None
    delta_pct: float | None  # variazione % vs previous close (sempre del prezzo API)
    currency: str
    format_spec: str
    is_override: bool = False
    is_stale: bool = False   # True se valore proviene da cache scaduta
    error: str = ""


@dataclass(frozen=True, slots=True)
class DeltaWindow:
    """v7.2 (B10): variazioni % su piu' finestre temporali per un asset.

    Tutte le percentuali sono in formato decimale (0.012 = 1.2%). None
    indica dato non disponibile (ticker errato, storico insufficiente,
    yfinance non installato).

    Attributes:
        term: Label leggibile (es. "S&P 500").
        ticker: Yahoo ticker (es. "SPY", "BTC-USD").
        delta_1w: Variazione vs prezzo di 5 trading day fa.
        delta_1m: Variazione vs prezzo di ~21 trading day fa.
        delta_ytd: Variazione vs primo trading day dell'anno corrente.
        last_price: Ultimo prezzo close (per visualizzazione).
        error: Messaggio errore se fetch fallito (vuoto se ok).
    """

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
    fetched_at: float = 0.0       # timestamp epoch
    is_stale: bool = False         # True se dato cache > TTL
    n_errors: int = 0

    @property
    def fetched_at_human(self) -> str:
        """Stringa human-readable 'X secondi fa'."""
        if self.fetched_at == 0:
            return "mai"
        delta = time.time() - self.fetched_at
        if delta < 60:
            return f"{int(delta)}s fa"
        if delta < 3600:
            return f"{int(delta / 60)}m fa"
        return f"{int(delta / 3600)}h fa"


class LiveMarketService:
    """Servizio singleton per fetch KPI real-time con cache e force refresh.

    Thread-safety:
      - ``self._lock``: protegge la cache (lettura/scrittura snapshot).
      - ``self._refresh_cv``: Condition usata per evitare che N thread
        scavalchino la cache scaduta facendo N download HTTP paralleli.
        Solo il primo thread fa il fetch, gli altri attendono e leggono
        la cache appena scritta.
    """

    def __init__(
        self,
        *,
        override_store: ManualOverrideStore | None = None,
        sanity: SanityChecker | None = None,
        ttl_seconds: float = _TTL_SECONDS,
    ) -> None:
        self._override_store = override_store or ManualOverrideStore()
        self._sanity = sanity or SanityChecker()
        self._ttl = ttl_seconds
        self._cache: MarketSnapshot = MarketSnapshot()
        self._lock = Lock()
        # Condition variable per coordinare i refresh concorrenti
        self._refresh_cv = Condition(self._lock)
        self._refresh_in_progress = False
        # v9.0 (Sett.2): WebSocket manager opzionale per prezzi live Finnhub.
        # Iniettato da start_websocket_stream() se realtime_websocket=true.
        # None quando il WebSocket non è attivo (default safe).
        self._ws_manager: object | None = None  # tipo opaco per evitare import circolare

    # ─────────────────────────────────────────────────────── public api
    def get_kpi_snapshot(self, *, force: bool = False) -> MarketSnapshot:
        """Ritorna snapshot dei KPI. Usa cache se valida e non force=True.

        Pattern di sincronizzazione (fix race condition #2):
          1. Acquisisci lock.
          2. Se cache valida e !force -> ritorna cache.
          3. Se un altro thread sta gia' rifacendo il fetch (refresh_in_progress)
             -> attendi che finisca, poi ritorna la cache aggiornata.
          4. Altrimenti, marca refresh_in_progress=True e rilascia il lock.
          5. Esegui il fetch (operazione lenta, fuori dal lock).
          6. Riacquisisci il lock, scrivi cache, marca refresh_in_progress=False,
             notifica gli altri thread.
        """
        with self._refresh_cv:
            cache_age = time.time() - self._cache.fetched_at
            cache_valid = (
                self._cache.kpis and cache_age < self._ttl and not force
            )
            if cache_valid:
                return self._cache

            # Cache scaduta o force=True: serve un refresh.
            if self._refresh_in_progress:
                # Un altro thread sta gia' refreshando. Aspetta che finisca,
                # poi ritorna la cache che lui ha appena scritto.
                self._refresh_cv.wait_for(
                    lambda: not self._refresh_in_progress, timeout=30.0
                )
                return self._cache

            # Siamo il primo thread a fare il refresh.
            self._refresh_in_progress = True

        # Fuori dal lock: il fetch e' lento (HTTP), non bloccare gli altri.
        new_snapshot = None
        try:
            new_snapshot = self._fetch_snapshot()
        except Exception as e:
            log.error("Failed to fetch snapshot", error=str(e))
            # Fallback: usa la cache precedente se disponibile, altrimenti costruisci snapshot di errore
            with self._lock:
                if self._cache.kpis:
                    new_snapshot = self._cache
                    new_snapshot.is_stale = True
                else:
                    new_snapshot = MarketSnapshot(
                        kpis=self._build_unavailable_kpis(f"Fetch error: {e}")
                    )
        finally:
            with self._refresh_cv:
                self._cache = new_snapshot
                self._refresh_in_progress = False
                self._refresh_cv.notify_all()

        return new_snapshot

    def refresh_now(self) -> MarketSnapshot:
        """Forza un re-fetch immediato ignorando la cache."""
        return self.get_kpi_snapshot(force=True)

    def start_websocket_stream(self, tickers: list[str] | None = None) -> bool:
        """Avvia lo stream WebSocket Finnhub se il feature flag è abilitato.

        v9.0 (Sett.2): integra WebSocketStreamManager per prezzi live.
        I prezzi WebSocket vengono usati da _extract_kpi() se non stale
        (< 90s), riducendo il numero di REST call a yfinance.

        Args:
            tickers: Lista di ticker da streamare. None = usa _KPI_DEFINITIONS.

        Returns:
            True se il WebSocket è stato avviato, False altrimenti.
        """
        try:
            from shared.feature_flags import is_enabled
            if not is_enabled("realtime_websocket"):
                return False

            from engine.market_data.websocket_manager import get_ws_manager
            ws = get_ws_manager()
            if ws is None:
                return False

            stream_tickers = tickers or [d[1] for d in _KPI_DEFINITIONS]
            ws.start(stream_tickers)
            self._ws_manager = ws
            log.info("live_market_service.ws_stream_started", tickers=len(stream_tickers))
            return True

        except Exception as exc:
            # Fallback silenzioso: REST continua a funzionare
            log.warning(
                "live_market_service.ws_start_failed",
                error=str(exc)[:120],
            )
            return False

    def _get_ws_price(self, yf_ticker: str) -> float | None:
        """Ritorna il prezzo live dal WebSocket se disponibile e non stale.

        Usato da _extract_kpi() come source prioritaria quando il WS è attivo.
        Ritorna None se WS non attivo, ticker non subscribato, o prezzo stale.
        """
        if self._ws_manager is None:
            return None
        try:
            lp = self._ws_manager.get_price(yf_ticker)  # type: ignore[attr-defined]
            if lp is not None:
                return lp.price
        except Exception:  # noqa: BLE001
            pass
        return None

    def cache_age_seconds(self) -> float:
        """Eta' della cache in secondi (0 se mai fetchata)."""
        with self._lock:
            if self._cache.fetched_at == 0:
                return 0.0
            return time.time() - self._cache.fetched_at

    # ─────────────────────────────────────────────────────── internal
    def _fetch_snapshot(self) -> MarketSnapshot:
        """Esegue fetch live di tutti i KPI. Pure: nessuna mutazione cache.

        Il chiamante e' responsabile di scrivere il risultato sulla cache
        sotto lock (vedi get_kpi_snapshot).
        """
        snapshot = MarketSnapshot()
        snapshot.fetched_at = time.time()

        try:
            import yfinance as yf
        except ImportError:
            # yfinance non installato: ritorniamo cache se esiste, altrimenti placeholder
            cached = self._read_cache_safe()
            if cached.kpis:
                cached.is_stale = True
                return cached
            snapshot.kpis = self._build_unavailable_kpis(
                "yfinance non installato"
            )
            snapshot.n_errors = len(snapshot.kpis)
            return snapshot

        # Bulk download dei tickers per minimizzare chiamate HTTP.
        # BUGFIX v7.2.2 (yfinance compat): yfinance 0.2.x+ usa MultiIndex (field, ticker)
        # by default — rimosso group_by="ticker" (vecchia API) e auto_adjust=False.
        # Aggiunti auto_adjust=True (nuovo default) e fallback per strutture diverse.
        tickers_list = [d[1] for d in _KPI_DEFINITIONS]
        data = None
        try:
            data = yf.download(
                tickers=tickers_list,
                period="5d",
                interval="1d",
                progress=False,
                auto_adjust=True,
                multi_level_index=True,  # esplicito per yfinance >= 0.2.50
            )
        except TypeError:
            # Versioni precedenti non hanno multi_level_index param
            try:
                data = yf.download(
                    tickers=" ".join(tickers_list),
                    period="5d",
                    interval="1d",
                    progress=False,
                    auto_adjust=True,
                )
            except (OSError, ValueError, KeyError) as exc:
                data = None
                log.warning("yfinance.download_failed", error=str(exc)[:120])
        except (OSError, ValueError, KeyError) as exc:
            data = None
            log.warning("yfinance.download_failed", error=str(exc)[:120])

        if data is None or data.empty:
            # Fallback globale: usa cache o segna tutto come non disponibile
            cached = self._read_cache_safe()
            if cached.kpis:
                cached.is_stale = True
                return cached
            snapshot.kpis = self._build_unavailable_kpis("yfinance download failed")
            snapshot.n_errors = len(snapshot.kpis)
            return snapshot

        for term, yf_ticker, currency, fmt in _KPI_DEFINITIONS:
            kpi = self._extract_kpi(
                data=data,
                term=term,
                yf_ticker=yf_ticker,
                currency=currency,
                fmt=fmt,
            )
            snapshot.kpis.append(kpi)
            if kpi.error:
                snapshot.n_errors += 1

        return snapshot

    def _get_ticker_frame(self, data: Any, yf_ticker: str) -> Any:
        """Estrae il sotto-frame per un singolo ticker.

        BUGFIX v7.2.2: gestisce tutte le varianti di struttura MultiIndex di yfinance:
          · Nuova (>= 0.2.x): colonne (field, ticker) — usa xs(ticker, level=1)
          · Vecchia (<= 0.1.x): colonne (ticker, field) — usa data[ticker]
          · Singolo ticker: colonne piane — ritorna data com'è
        """
        import pandas as pd

        if data is None or data.empty:
            return None

        if isinstance(data.columns, pd.MultiIndex):
            lvl0 = data.columns.get_level_values(0).tolist()
            lvl1 = data.columns.get_level_values(1).tolist()

            # Nuovo formato: (field, ticker) → ticker in level 1
            if yf_ticker in lvl1:
                try:
                    return data.xs(yf_ticker, axis=1, level=1)
                except (KeyError, TypeError):
                    pass

            # Vecchio formato: (ticker, field) → ticker in level 0
            if yf_ticker in lvl0:
                try:
                    return data[yf_ticker]
                except (KeyError, TypeError):
                    pass

            return None

        # DataFrame a colonne piane: caso singolo ticker o fallback
        if "Close" in data.columns or "close" in data.columns:
            return data

        return None

    def _fetch_fast_info_fallback(self, yf_ticker: str) -> tuple[float | None, float | None]:
        """Fallback singolo ticker via yf.Ticker.fast_info.

        BUGFIX v7.2.2: usato quando il bulk download fallisce o restituisce dati vuoti.
        Più lento ma più affidabile per ticker individuali.

        Returns:
            (last_price, delta_pct) — entrambi None se il ticker non è disponibile.
        """
        try:
            import yfinance as yf
            t = yf.Ticker(yf_ticker)
            fi = t.fast_info
            price = getattr(fi, "last_price", None)
            prev = getattr(fi, "previous_close", None)
            if price is None or price != price:   # NaN check
                return None, None
            price_f = float(price)
            delta: float | None = None
            if prev is not None and float(prev) > 0:
                delta = (price_f - float(prev)) / float(prev)
            return price_f, delta
        except Exception:  # noqa: BLE001
            return None, None

    def _read_cache_safe(self) -> MarketSnapshot:
        """Snapshot copy della cache corrente per uso fuori dal lock."""
        with self._lock:
            return MarketSnapshot(
                kpis=list(self._cache.kpis),
                fetched_at=self._cache.fetched_at,
                is_stale=self._cache.is_stale,
                n_errors=self._cache.n_errors,
            )

    def _extract_kpi(
        self,
        *,
        data: Any,
        term: str,
        yf_ticker: str,
        currency: str,
        fmt: str,
    ) -> MarketKpi:
        """Estrae il KPI per un singolo ticker dal DataFrame multi-ticker yf.

        v9.0 (Sett.2): controlla prima il WebSocket se attivo e non stale.
        Questo riduce la latenza per i ticker subscribati a Finnhub WS.
        Fallback trasparente a yfinance REST se WS non disponibile.
        """
        # ─── v9.0: WebSocket price (source prioritaria, bassa latenza) ───────
        # Se il WS è attivo e ha un prezzo recente (< 90s), lo usiamo
        # direttamente senza parsare il DataFrame yfinance.
        # delta_pct non è disponibile dal WS → rimane None fino al prossimo REST.
        ws_price = self._get_ws_price(yf_ticker)
        if ws_price is not None:
            final_value, is_override = self._override_store.resolve(
                "price", term, ws_price
            )
            return MarketKpi(
                term=term,
                yf_ticker=yf_ticker,
                value=final_value,
                delta_pct=None,  # delta non disponibile da WS
                currency=currency,
                format_spec=fmt,
                is_override=is_override,
            )
        # ─── Fallback: yfinance REST (percorso originale) ─────────────────────
        try:
            # Quando si chiama yf.download con piu' tickers e group_by="ticker",
            # il risultato e' un DataFrame multi-index. Selezioniamo il sotto-frame.
            try:
                ticker_data = data[yf_ticker]
            except (KeyError, TypeError):
                # Singolo ticker: il DataFrame non ha multi-index.
                ticker_data = data

            if ticker_data is None or ticker_data.empty:
                raise SilentFailureError("yfinance", f"empty data for {yf_ticker}")

            # Drop righe interamente NaN (giorni di chiusura mercati FX/futures).
            ticker_data = ticker_data.dropna(how="all")
            if ticker_data.empty or len(ticker_data) < 1:
                raise SilentFailureError("yfinance", f"no rows for {yf_ticker}")

            close_col = "Close" if "Close" in ticker_data.columns else "close"
            if close_col not in ticker_data.columns:
                raise SilentFailureError(
                    "yfinance", f"no Close column for {yf_ticker}"
                )

            last_close = float(ticker_data[close_col].iloc[-1])
            prev_close = (
                float(ticker_data[close_col].iloc[-2])
                if len(ticker_data) >= 2
                else last_close
            )

            # Sanity check
            violations = self._sanity.check_price_data(
                yf_ticker, last_close, prev_close=prev_close
            )
            if not self._sanity.is_safe_to_store(violations):
                # Violazione critica: usa cache se c'e', altrimenti errore.
                cached = self._lookup_cached(term)
                if cached is not None:
                    return MarketKpi(
                        term=term,
                        yf_ticker=yf_ticker,
                        value=cached.value,
                        delta_pct=cached.delta_pct,
                        currency=cached.currency,
                        format_spec=fmt,
                        is_stale=True,
                        error="sanity violation, using last good value",
                    )

            # ─── BUGFIX v7.1.1: delta_pct calcolato SEMPRE sul prezzo API, ───
            # non sull'override. Il delta deve riflettere il vero movimento
            # del mercato (last_close vs prev_close), indipendentemente dal
            # fatto che l'utente abbia inserito un override sul valore corrente.
            api_delta_pct: float | None = None
            if prev_close > 0:
                api_delta_pct = (last_close - prev_close) / prev_close

            # Override manuale (Rule 43): l'utente puo' aver corretto il prezzo.
            final_value, is_override = self._override_store.resolve(
                "price", term, last_close
            )

            return MarketKpi(
                term=term,
                yf_ticker=yf_ticker,
                value=final_value,
                delta_pct=api_delta_pct,  # delta del PREZZO API, non dell'override
                currency=currency,
                format_spec=fmt,
                is_override=is_override,
            )

        except SilentFailureError as exc:
            # BUGFIX v7.2.2: fast_info fallback prima di usare cache scaduta
            price_fb, delta_fb = self._fetch_fast_info_fallback(yf_ticker)
            if price_fb is not None:
                log.info("yfinance.fast_info_fallback_used", ticker=yf_ticker)
                return MarketKpi(
                    term=term,
                    yf_ticker=yf_ticker,
                    value=price_fb,
                    delta_pct=delta_fb,
                    currency=currency,
                    format_spec=fmt,
                )
            cached = self._lookup_cached(term)
            if cached is not None:
                return MarketKpi(
                    term=term,
                    yf_ticker=yf_ticker,
                    value=cached.value,
                    delta_pct=cached.delta_pct,
                    currency=cached.currency,
                    format_spec=fmt,
                    is_stale=True,
                    error=f"silent_failure: {exc.reason[:80]}",
                )
            return MarketKpi(
                term=term,
                yf_ticker=yf_ticker,
                value=None,
                delta_pct=None,
                currency=currency,
                format_spec=fmt,
                error=f"silent_failure: {exc.reason[:80]}",
            )
        except (KeyError, ValueError, IndexError, AttributeError) as exc:
            cached = self._lookup_cached(term)
            if cached is not None:
                return MarketKpi(
                    term=term,
                    yf_ticker=yf_ticker,
                    value=cached.value,
                    delta_pct=cached.delta_pct,
                    currency=cached.currency,
                    format_spec=fmt,
                    is_stale=True,
                    error=f"parse_error: {str(exc)[:80]}",
                )
            return MarketKpi(
                term=term,
                yf_ticker=yf_ticker,
                value=None,
                delta_pct=None,
                currency=currency,
                format_spec=fmt,
                error=f"parse_error: {str(exc)[:80]}",
            )

    def _lookup_cached(self, term: str) -> MarketKpi | None:
        """Cerca un KPI esistente in cache per il termine specificato."""
        with self._lock:
            for k in self._cache.kpis:
                if k.term == term and k.value is not None:
                    return k
        return None

    @staticmethod
    def _build_unavailable_kpis(reason: str) -> list[MarketKpi]:
        """Placeholder KPIs per quando il fetch e' impossibile."""
        return [
            MarketKpi(
                term=term,
                yf_ticker=yf_ticker,
                value=None,
                delta_pct=None,
                currency=currency,
                format_spec=fmt,
                error=reason,
            )
            for term, yf_ticker, currency, fmt in _KPI_DEFINITIONS
        ]


# ─────────────────────────────────────────────────────────── singleton
# BUGFIX v7.1.1: race condition nel pattern "if _singleton is None: ...".
#
# functools.lru_cache NON garantisce un'unica esecuzione della funzione
# wrapped sotto contesa: garantisce solo che tutti i chiamanti VEDANO
# alla fine lo stesso valore in cache, ma la funzione interna puo' essere
# chiamata piu' volte se piu' thread la invocano prima che il primo
# completi. Per un VERO singleton thread-safe serve un Lock esplicito,
# applicato col pattern double-checked locking.
_singleton_lock = Lock()
_singleton_instance: LiveMarketService | None = None


def get_live_market_service() -> LiveMarketService:
    """Lazy singleton accessor thread-safe (double-checked locking).

    Garantisce che la classe ``LiveMarketService`` venga istanziata
    una sola volta anche sotto N thread concorrenti che chiamano qui.
    """
    global _singleton_instance  # noqa: PLW0603 — singleton pattern
    # Fast path (sente la lettura senza lock; OK in CPython con GIL)
    if _singleton_instance is not None:
        return _singleton_instance
    # Slow path: acquisisci lock e ricontrolla.
    with _singleton_lock:
        if _singleton_instance is None:
            _singleton_instance = LiveMarketService()
        return _singleton_instance


def _reset_singleton_for_testing() -> None:
    """Resetta il singleton — uso ESCLUSIVO nei test."""
    global _singleton_instance  # noqa: PLW0603
    with _singleton_lock:
        _singleton_instance = None


# ─────────────────────────────────────────────────── multi-window deltas (v7.2 B10)
# Numero di trading day per finestre temporali (Rule 7: nominati, no magic).
_TRADING_DAYS_1W: int = 5
_TRADING_DAYS_1M: int = 21


def fetch_delta_windows(
    tickers: list[tuple[str, str]],
) -> list[DeltaWindow]:
    """v7.2 (B10): Calcola variazioni % 1W / 1M / YTD per N ticker.

    Usa ``yfinance`` con ``period="1y"`` per coprire tutti gli orizzonti
    in un unico fetch per ticker. Errori di rete o ticker errati ritornano
    DeltaWindow con tutti i delta=None e messaggio in ``error``: nessuna
    eccezione propagata.

    Args:
        tickers: Lista di tuple (yahoo_ticker, label_display).
            Esempio: ``[("SPY", "S&P 500"), ("BTC-USD", "Bitcoin")]``.

    Returns:
        Lista di DeltaWindow nello stesso ordine dei tickers in input.

    Note:
        Funzione module-level (non metodo): cosi' Streamlit puo' applicare
        ``@st.cache_data`` direttamente senza preoccuparsi di self-hashing.
    """
    try:
        import yfinance as yf
    except ImportError:
        # Fallback: tutti unavailable
        return [
            DeltaWindow(
                term=label,
                ticker=ticker,
                delta_1w=None,
                delta_1m=None,
                delta_ytd=None,
                error="yfinance non installato (poetry install)",
            )
            for ticker, label in tickers
        ]

    results: list[DeltaWindow] = []
    today = date.today()
    for ticker, label in tickers:
        try:
            data = yf.download(
                tickers=ticker,
                period="1y",
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=False,
                group_by="column",
            )
        except (OSError, ValueError, KeyError) as exc:
            log.warning(
                "delta_window.fetch_failed",
                ticker=ticker,
                error=str(exc),
            )
            results.append(
                DeltaWindow(
                    term=label, ticker=ticker,
                    delta_1w=None, delta_1m=None, delta_ytd=None,
                    error=str(exc),
                )
            )
            continue

        if data is None or data.empty:
            results.append(
                DeltaWindow(
                    term=label, ticker=ticker,
                    delta_1w=None, delta_1m=None, delta_ytd=None,
                    error="Nessun dato yfinance",
                )
            )
            continue

        # Normalizza columns MultiIndex -> flat
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Cerca colonna "Close" case-insensitive
        close_col = None
        for col in data.columns:
            if str(col).lower() == "close":
                close_col = col
                break
        if close_col is None:
            results.append(
                DeltaWindow(
                    term=label, ticker=ticker,
                    delta_1w=None, delta_1m=None, delta_ytd=None,
                    error="colonna Close mancante",
                )
            )
            continue

        close = data[close_col].dropna()
        if close.empty:
            results.append(
                DeltaWindow(
                    term=label, ticker=ticker,
                    delta_1w=None, delta_1m=None, delta_ytd=None,
                    error="serie close vuota",
                )
            )
            continue

        last = float(close.iloc[-1])

        # 1W = 5 trading day fa (l'indice e' il 6° dalla fine — len-_TRADING_DAYS_1W-1)
        ref_1w: float | None = None
        if len(close) > _TRADING_DAYS_1W:
            ref_1w = float(close.iloc[-_TRADING_DAYS_1W - 1])

        # 1M = ~21 trading day fa
        ref_1m: float | None = None
        if len(close) > _TRADING_DAYS_1M:
            ref_1m = float(close.iloc[-_TRADING_DAYS_1M - 1])

        # YTD = primo trading day dell'anno corrente
        ref_ytd: float | None = None
        # close.index e' DatetimeIndex; gestiamo tz-aware/naive
        try:
            year_mask = close.index.year == today.year
            year_data = close[year_mask]
            if not year_data.empty:
                ref_ytd = float(year_data.iloc[0])
        except (AttributeError, TypeError):
            ref_ytd = None

        def _pct(ref: float | None) -> float | None:
            if ref is None or ref == 0:
                return None
            return (last - ref) / ref

        results.append(
            DeltaWindow(
                term=label,
                ticker=ticker,
                delta_1w=_pct(ref_1w),
                delta_1m=_pct(ref_1m),
                delta_ytd=_pct(ref_ytd),
                last_price=last,
            )
        )

    return results