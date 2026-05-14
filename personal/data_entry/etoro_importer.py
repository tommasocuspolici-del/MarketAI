"""EtoroImporter: facade unica (v7.4.0) con fix conversione valuta GBX/EUR→USD.

Novità v7.4.0:
  - FIX CRITICO #1: _INSTRUMENT_ID_TO_REAL_TICKER[3040] corretto da "EUNL.DE"
    a "SWDA.L" (iShares Core MSCI World UCITS ETF, LSE, GBX). Il codice
    precedente puntava alla classe Xetra/EUR; il portfolio reale mostra SWDA.L.
  - FIX CRITICO #2: openRate dall'API eToro per ETF LSE (*.L) è in GBX (pence
    sterling), non in USD. Introdotta conversione GBX→USD:
        price_usd = price_gbx / 100 * GBP/USD
    Stessa logica applicata ai ticker EUR (*.DE, *.MI ecc.) tramite EUR/USD.
  - FIX: _get_live_price_usd restituisce prezzi sempre in USD per qualunque
    mercato (sostituisce la vecchia _get_live_price_yfinance che restituiva
    il valore grezzo in valuta nativa).
  - FIX: _override_prices_for_numeric_tickers corregge open_price → USD oltre
    a current_price (prima open_price rimaneva in GBX causando P/L -98%).
  - FIX: currency non più hardcoded a "USD"; derivata dal suffisso del ticker
    e poi normalizzata a "USD" dopo la conversione.
  - FIX: _api_positions_to_dataframe usa conversionRateAsk/Bid dall'API eToro
    per convertire open_rate dalla valuta nativa in USD. Fallback su GBP/USD
    o EUR/USD da yfinance se il campo API non è disponibile.
  - Aggiunta public function get_live_price_usd(ticker) per uso da P2/altri
    moduli senza duplicare la logica di conversione GBX.

Novità v7.3.3:
  - Fix aggregazione: calcolo corretto del totale investito senza riferimento
    a variabili esterne.
  - _override_prices_for_numeric_tickers ora gestisce NaN in open_price.
  - Allineato ai nuovi campi dei modelli (symbolFull, lastExecution,
    conversion rates).
  - Migliorata robustezza generale del parsing.

Novità v7.3.2:
  - Tabella di associazione instrumentID numerico (es. #3040) → ticker reale
    (SWDA.L, CSPX, EIMI.L). Facilmente aggiornabile.
  - I prezzi per gli strumenti numerici vengono sempre presi da yfinance,
    ignorando il close_rate errato dell'API.
  - La mappatura è utilizzata sia per l'API che per il fallback XLSX.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

import pandas as pd
import yfinance as yf

from personal.data_entry.etoro_client import (
    EtoroAuthError,
    EtoroClient,
    EtoroClientError,
)
from personal.data_entry.etoro_models import (
    EtoroInstrument,
    EtoroInstrumentRate,
    EtoroPortfolioResponse,
    EtoroPosition,
)
from personal.data_entry.etoro_parser import EToroParseError, EToroParser

__version__ = "7.4.0"

__all__ = [
    "EtoroImporter",
    "EtoroImportError",
    "EtoroImportResult",
    "update_live_prices",
    "aggregate_by_real_ticker",
    "get_live_price_usd",       # ← nuovo export pubblico
]

log = logging.getLogger(__name__)


class EtoroImportError(Exception):
    """Errore generico durante l'import."""


@dataclass(frozen=True, slots=True)
class EtoroImportResult:
    positions: pd.DataFrame
    source: str
    n_positions: int
    n_warnings: int = 0
    notes: str = ""


_CANONICAL_COLUMNS = [
    "ticker",
    "direction",
    "quantity",
    "open_price",
    "current_price",
    "open_date",
    "market_value",
    "profit_pct",
    "profit_eur",
    "currency",
    "raw_action",
]

# ───────────────────────────────────────────────────────────────
#  MAPPATURA INSTRUMENT ID NUMERICO → TICKER REALE
#  Aggiorna questa tabella quando compaiono nuovi codici interni.
#  I ticker devono essere nel formato riconosciuto da yfinance.
# ───────────────────────────────────────────────────────────────
_INSTRUMENT_ID_TO_REAL_TICKER: dict[int, str] = {
    # v7.4.0 FIX: 3040 era "EUNL.DE" (Xetra/EUR) → corretto a "SWDA.L" (LSE/GBX)
    # ISIN IE00B4L5Y983: stessa UCITS ETF, listino diverso.
    3040:  "SWDA.L",    # iShares Core MSCI World UCITS ETF   (GBX, LSE)
    3434:  "CSPX.L",    # iShares Core S&P 500 UCITS ETF      (GBX, LSE)
    15435: "EIMI.L",    # iShares Core MSCI EM IMI UCITS ETF  (GBX, LSE)
    3394:  "EUN5.DE",   # iShares EUR Corp Bond UCITS ETF      (EUR, Xetra)
    10569: "IBCN.DE",   # iShares EUR Govt Bond 3-7yr UCITS ETF(EUR, Xetra)
    # ... aggiungi qui altre corrispondenze
}

# ───────────────────────────────────────────────────────────────
#  MAPPA SUFFISSO TICKER → VALUTA NATIVA DI QUOTAZIONE
#  L'API eToro restituisce openRate e closeRate nella valuta nativa
#  del listino su cui lo strumento è quotato.
# ───────────────────────────────────────────────────────────────
_SUFFIX_TO_CURRENCY: dict[str, str] = {
    ".L":  "GBX",   # London Stock Exchange  → pence sterling (GBX = GBP/100)
    ".DE": "EUR",   # Deutsche Börse / Xetra → euro
    ".MI": "EUR",   # Borsa Italiana         → euro
    ".PA": "EUR",   # Euronext Paris         → euro
    ".AS": "EUR",   # Euronext Amsterdam     → euro
    ".BR": "EUR",   # Euronext Bruxelles     → euro
    ".LS": "EUR",   # Euronext Lisbona       → euro
}

# Tassi FX di fallback (usati se yfinance non è raggiungibile)
_FX_FALLBACK: dict[str, float] = {
    "GBP_USD": 1.27,
    "EUR_USD": 1.08,
}


# ─────────────────────────────────────────────────── FX helpers
def _get_instrument_currency(ticker: str) -> str:
    """Determina la valuta nativa di quotazione dal suffisso del ticker.

    Ritorna 'GBX', 'EUR' o 'USD' (default per tutto il resto).
    """
    upper = ticker.upper()
    for suffix, ccy in _SUFFIX_TO_CURRENCY.items():
        if upper.endswith(suffix.upper()):
            return ccy
    return "USD"


def _fetch_fx_rate(yf_pair: str, fallback: float) -> float:
    """Recupera un tasso FX da yfinance. fast_info → history → fallback."""
    try:
        t = yf.Ticker(yf_pair)
        fi = t.fast_info
        price = getattr(fi, "last_price", None)
        if price is not None and float(price) > 0:
            return float(price)
        hist = t.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:  # noqa: BLE001
        pass
    return fallback


def _build_fx_cache() -> dict[str, float]:
    """Scarica GBP/USD e EUR/USD una volta sola per importazione.

    Centralizzato qui per evitare N chiamate yfinance ridondanti durante
    il loop sulle posizioni.
    """
    return {
        "GBP_USD": _fetch_fx_rate("GBPUSD=X", _FX_FALLBACK["GBP_USD"]),
        "EUR_USD": _fetch_fx_rate("EURUSD=X", _FX_FALLBACK["EUR_USD"]),
    }


def _native_to_usd(price: float, currency: str, fx: dict[str, float]) -> float:
    """Converte un prezzo dalla valuta nativa del listino in USD.

    GBX (pence sterling) → USD : price / 100 * GBP_USD
    EUR                  → USD : price * EUR_USD
    USD                  → USD : invariato
    """
    if currency == "GBX":
        return price / 100.0 * fx.get("GBP_USD", _FX_FALLBACK["GBP_USD"])
    if currency == "EUR":
        return price * fx.get("EUR_USD", _FX_FALLBACK["EUR_USD"])
    return float(price)


def _get_live_price_usd(ticker: str, fx: dict[str, float] | None = None) -> float | None:
    """Prezzo live via yfinance, sempre convertito in USD.

    Per ticker *.L (LSE): yfinance restituisce GBX (pence) →
        price_usd = price_gbx / 100 * GBP/USD
    Per ticker *.DE, *.MI ecc. (EUR): →
        price_usd = price_eur * EUR/USD
    Per tutti gli altri (USD): invariato.

    Args:
        ticker: Ticker Yahoo Finance (es. "SWDA.L", "CSPX.L", "EUN5.DE").
        fx: Cache dei tassi FX. Se None, viene costruita on-demand.

    Returns:
        Prezzo in USD, o None se il fetch fallisce.
    """
    if fx is None:
        fx = _build_fx_cache()
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period="1d")
        if data.empty:
            return None
        price_native = float(data["Close"].iloc[-1])
        currency = _get_instrument_currency(ticker)
        return _native_to_usd(price_native, currency, fx)
    except Exception:  # noqa: BLE001
        pass
    return None


# ─────────────────────────────────────── public alias (usato da P2 e altri moduli)
def get_live_price_usd(ticker: str) -> float | None:
    """Public wrapper: prezzo live in USD per qualunque ticker (GBX/EUR/USD).

    Costruisce la cache FX internamente; per uso in loop preferire
    _get_live_price_usd(ticker, fx) passando una cache condivisa.
    """
    return _get_live_price_usd(ticker, _build_fx_cache())


# ─────────────────────────────────────────────────────── EtoroImporter
class EtoroImporter:
    """Facade unificata per import posizioni eToro."""

    def __init__(
        self,
        *,
        api_key_var: str = "ETORO_API_KEY",
        user_key_var: str = "ETORO_USER_KEY",
    ) -> None:
        self._api_key_var = api_key_var
        self._user_key_var = user_key_var

    @property
    def has_api_credentials(self) -> bool:
        api_key = os.environ.get(self._api_key_var, "").strip()
        user_key = os.environ.get(self._user_key_var, "").strip()
        return bool(api_key and user_key)

    @property
    def credential_status_message(self) -> str:
        if self.has_api_credentials:
            return "✅ API eToro configurata."
        return "ℹ️ Credenziali API eToro assenti: sarà usato il file XLSX."

    def import_open_positions(
        self,
        *,
        xlsx_source: str | bytes | BinaryIO | None = None,
        force_xlsx: bool = False,
    ) -> EtoroImportResult:
        if not force_xlsx and self.has_api_credentials:
            try:
                return self.import_via_api()
            except EtoroClientError as exc:
                log.warning("API fallita, fallback XLSX: %s", exc)
                if xlsx_source is None:
                    raise EtoroImportError(
                        f"API fallita ({exc}) e nessun XLSX di fallback."
                    ) from exc
                return self.import_via_xlsx(
                    xlsx_source, notes=f"Fallback dopo errore API: {exc}"
                )
        if xlsx_source is None:
            raise EtoroImportError("Nessuna fonte disponibile.")
        return self.import_via_xlsx(xlsx_source)

    def import_via_api(self) -> EtoroImportResult:
        client = EtoroClient.from_env(
            api_key_var=self._api_key_var, user_key_var=self._user_key_var
        )
        portfolio = client.get_real_portfolio()
        all_positions = portfolio.client_portfolio.positions

        if not all_positions:
            return EtoroImportResult(
                positions=_empty_canonical_df(),
                source="api",
                n_positions=0,
                notes="Nessuna posizione aperta.",
            )

        # Classificazione (tier 1-4) invariata
        resolvable_with_id: list[EtoroPosition] = []
        resolvable_ticker_only: list[EtoroPosition] = []
        candidate_via_order: list[EtoroPosition] = []
        unresolvable: list[EtoroPosition] = []

        for pos in all_positions:
            if pos.instrument_id is not None:
                resolvable_with_id.append(pos)
            elif pos.ticker_from_api is not None:
                resolvable_ticker_only.append(pos)
            elif pos.order_id is not None:
                candidate_via_order.append(pos)
            else:
                unresolvable.append(pos)

        resolvable_via_order: list[EtoroPosition] = []
        if candidate_via_order:
            resolved, still = _resolve_instrument_ids_via_orders(
                client, candidate_via_order
            )
            resolvable_via_order = resolved
            resolvable_with_id.extend(resolved)
            unresolvable.extend(still)

        n_unresolvable = len(unresolvable)
        n_resolvable = len(resolvable_with_id) + len(resolvable_ticker_only)

        if n_resolvable == 0:
            return EtoroImportResult(
                positions=_empty_canonical_df(),
                source="api",
                n_positions=0,
                n_warnings=n_unresolvable,
                notes="Nessuna posizione recuperabile.",
            )

        instruments: dict[int, EtoroInstrument] = {}
        if resolvable_with_id:
            instrument_ids = list({p.instrument_id for p in resolvable_with_id})  # type: ignore
            try:
                instruments = client.get_instruments(instrument_ids)
            except EtoroClientError as exc:
                log.warning("Lookup instrument fallito: %s", exc)

        # Quote correnti dall'API — includono conversionRateAsk/Bid per la conversione FX.
        rates: dict[int, EtoroInstrumentRate] = {}
        if resolvable_with_id:
            try:
                rates = client.get_rates(
                    [p.instrument_id for p in resolvable_with_id]  # type: ignore
                )
            except EtoroClientError as exc:
                log.warning("Lookup rates fallito: %s", exc)

        all_resolvable = resolvable_with_id + resolvable_ticker_only

        # Cache FX costruita una volta per tutta l'importazione
        fx = _build_fx_cache()
        log.debug("etoro_importer.fx_cache GBP/USD=%.4f EUR/USD=%.4f",
                  fx["GBP_USD"], fx["EUR_USD"])

        df = _api_positions_to_dataframe(all_resolvable, instruments, rates, fx)

        df["real_ticker"] = df.apply(
            lambda row: _resolve_real_ticker_for_row(row, instruments), axis=1
        )

        # Correzione prezzi + conversione valuta nativa → USD per i ticker numerici
        df = _override_prices_for_numeric_tickers(df, fx)

        notes_parts = [f"Importate {n_resolvable} posizioni via API."]
        if resolvable_ticker_only:
            notes_parts.append(
                f"{len(resolvable_ticker_only)} posizioni importate tramite ticker_from_api."
            )
        if resolvable_via_order:
            notes_parts.append(
                f"{len(resolvable_via_order)} posizioni risolte via orderId."
            )
        if n_unresolvable:
            notes_parts.append(f"{n_unresolvable} posizioni scartate.")
        return EtoroImportResult(
            positions=df,
            source="api",
            n_positions=n_resolvable,
            n_warnings=n_unresolvable,
            notes=" ".join(notes_parts),
        )

    def import_via_xlsx(
        self, source: str | bytes | BinaryIO, *, notes: str = ""
    ) -> EtoroImportResult:
        parser = EToroParser()
        try:
            df = parser.parse(source)
        except EToroParseError as exc:
            raise EtoroImportError(f"Impossibile leggere XLSX: {exc}") from exc

        df = _align_canonical_schema(df)

        if "Nome" in df.columns:
            df["real_ticker"] = df["Nome"].apply(_extract_ticker_from_nome)
        else:
            df["real_ticker"] = df["ticker"].apply(_resolve_ticker_from_placeholder)

        fx = _build_fx_cache()
        df = _override_prices_for_numeric_tickers(df, fx)

        return EtoroImportResult(
            positions=df,
            source="xlsx",
            n_positions=len(df),
            notes=notes or "Parsing XLSX completato.",
        )

    def aggregate_by_real_ticker(self, df: pd.DataFrame) -> pd.DataFrame:
        """Aggrega posizioni con lo stesso ticker reale."""
        return _aggregate_positions(df)

    def get_portfolio_overview(
        self, df: pd.DataFrame, etoro_total_value: float = 0.0
    ) -> dict:
        """Restituisce un dizionario pronto per la sezione patrimonio."""
        aggr = _aggregate_positions(df)
        total = etoro_total_value if etoro_total_value else aggr["market_value"].sum()
        return {
            "eToro": {
                "valore_corrente": total,
                "posizioni": aggr.to_dict(orient="records"),
                "aggiornato_il": pd.Timestamp.now().isoformat(),
            }
        }


# ─────────────────────────────────────────────────────── funzioni pubbliche
def update_live_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Sostituisce current_price e ricalcola market_value/profit usando yfinance.

    Per le righe che hanno un real_ticker valido (non placeholder "#xxx")
    richiede il prezzo corrente e aggiorna tutte le metriche.
    Prezzi sempre in USD (GBX→USD per *.L, EUR→USD per *.DE ecc.).
    open_price è assunto già corretto in USD (post-import v7.4.0).
    """
    if "real_ticker" not in df.columns:
        df = df.copy()
        df["real_ticker"] = df["ticker"].apply(_resolve_ticker_from_placeholder)
    else:
        df = df.copy()

    fx = _build_fx_cache()

    for idx, row in df.iterrows():
        ticker = row["real_ticker"]
        if not ticker or ticker.startswith("#"):
            continue
        price = _get_live_price_usd(ticker, fx)
        if price is not None:
            df.at[idx, "current_price"] = price
            qty = float(row["quantity"]) if pd.notna(row["quantity"]) else 0.0
            df.at[idx, "market_value"] = qty * price
            invested = float(row["open_price"]) * qty if pd.notna(row["open_price"]) else 0.0
            df.at[idx, "profit_eur"] = (qty * price) - invested
            df.at[idx, "profit_pct"] = (
                ((qty * price) / invested - 1) * 100 if invested > 0 else 0.0
            )
    return df


def aggregate_by_real_ticker(df: pd.DataFrame) -> pd.DataFrame:
    """Funzione standalone per aggregare."""
    return _aggregate_positions(df)


# ─────────────────────────────────────────────────────── helper interni
def _resolve_ticker_from_placeholder(ticker_col: str) -> str:
    """Converte un placeholder '#3040' in un ticker reale, se mappato."""
    if ticker_col.startswith("#"):
        iid_str = ticker_col[1:]
        if iid_str.isdigit():
            iid = int(iid_str)
            if iid in _INSTRUMENT_ID_TO_REAL_TICKER:
                return _INSTRUMENT_ID_TO_REAL_TICKER[iid]
    return ticker_col


def _resolve_real_ticker_for_row(
    row: pd.Series,
    instruments: dict[int, EtoroInstrument],
) -> str:
    """Determina il ticker reale per una riga proveniente dall'API.

    Priorità:
    1. Ticker non numerico (già un simbolo reale) → restituiscilo così.
    2. Placeholder `#id` con id presente nella mappatura manuale → usa quella.
    3. Placeholder `#id` con id risolto via /instruments → usa best_symbol.
    4. Altrimenti mantieni il placeholder.
    """
    ticker = row["ticker"]
    if not ticker.startswith("#"):
        return ticker

    iid_str = ticker[1:]
    if not iid_str.isdigit():
        return ticker
    iid = int(iid_str)

    if iid in _INSTRUMENT_ID_TO_REAL_TICKER:
        return _INSTRUMENT_ID_TO_REAL_TICKER[iid]

    if iid in instruments:
        return instruments[iid].best_symbol
    return ticker


def _extract_ticker_from_nome(nome: str) -> str:
    """Estrae il ticker reale da una stringa Nome (es. 'iShares Core S&P 500 (CSPX)')"""
    if not nome:
        return ""
    match = re.search(r'\(([A-Z0-9\.]+)\)$', str(nome).strip())
    if match:
        return match.group(1)
    return nome


def _override_prices_for_numeric_tickers(
    df: pd.DataFrame,
    fx: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Per le righe con ticker placeholder (#...), corregge current_price E open_price.

    v7.4.0 — fix rispetto alla v7.3.3:
      · Converte open_price dalla valuta nativa (GBX/EUR) in USD.
        Prima open_price rimaneva il raw openRate dell'API (es. 9782.20 GBX)
        che veniva trattato come USD, producendo un costo base ~100x gonfiato
        per i ticker LSE e un P/L di -98.77% invece di +10%.
      · Aggiorna df["currency"] = "USD" dopo la conversione.
      · Usa la cache FX condivisa per non fare chiamate yfinance ripetute.
    """
    df = df.copy()
    if fx is None:
        fx = _build_fx_cache()

    for idx, row in df.iterrows():
        original_ticker = row["ticker"]
        real_ticker = row["real_ticker"]

        if not (
            original_ticker.startswith("#")
            and real_ticker
            and not real_ticker.startswith("#")
        ):
            continue

        # Valuta nativa del listino reale (es. GBX per SWDA.L)
        native_currency = _get_instrument_currency(real_ticker)

        # ── current_price: prezzo live yfinance → USD ─────────────────────
        price_usd = _get_live_price_usd(real_ticker, fx)
        if price_usd is None:
            log.warning(
                "etoro_importer._override_prices: nessun prezzo yfinance per %s",
                real_ticker,
            )
            continue

        # ── open_price: raw API (GBX/EUR) → USD ───────────────────────────
        # BUGFIX v7.4.0: prima questa conversione non veniva fatta, lasciando
        # open_price in GBX (es. 9782.20) che veniva sommato come se fosse USD.
        open_price_native = row["open_price"]
        if pd.notna(open_price_native) and float(open_price_native) > 0:
            open_price_usd = _native_to_usd(float(open_price_native), native_currency, fx)
        else:
            open_price_usd = 0.0

        qty = float(row["quantity"]) if pd.notna(row["quantity"]) else 0.0
        market_value = qty * price_usd
        invested = open_price_usd * qty

        df.at[idx, "current_price"] = price_usd
        df.at[idx, "open_price"]    = open_price_usd   # ← fix chiave
        df.at[idx, "market_value"]  = market_value
        df.at[idx, "profit_eur"]    = market_value - invested
        df.at[idx, "profit_pct"]    = (
            ((market_value / invested) - 1) * 100 if invested > 0 else 0.0
        )
        df.at[idx, "currency"] = "USD"  # normalizzato dopo conversione

    return df


def _aggregate_positions(df: pd.DataFrame) -> pd.DataFrame:
    """Raggruppa per real_ticker, somma quantità, calcola prezzo medio ponderato."""
    if "real_ticker" not in df.columns:
        raise ValueError("DataFrame must have 'real_ticker' column.")

    for col in ["quantity", "open_price", "current_price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["invested_value"] = df["open_price"] * df["quantity"]

    grouped = df.groupby("real_ticker", as_index=False).agg(
        total_units=("quantity", "sum"),
        total_invested=("invested_value", "sum"),
        last_current_price=("current_price", "last"),
        raw_action=("raw_action", "first"),
    )
    grouped["avg_open_price"] = grouped["total_invested"] / grouped["total_units"]
    grouped["market_value"]   = grouped["total_units"] * grouped["last_current_price"]
    grouped["profit_eur"]     = grouped["market_value"] - grouped["total_invested"]
    grouped["profit_pct"]     = (
        grouped["profit_eur"] / grouped["total_invested"].replace(0, pd.NA)
    ) * 100
    return grouped.rename(columns={"real_ticker": "ticker"})


def _resolve_instrument_ids_via_orders(
    client: EtoroClient, positions: list[EtoroPosition]
) -> tuple[list[EtoroPosition], list[EtoroPosition]]:
    if not positions:
        return [], []
    if not hasattr(client, "get_instrument_id_from_order"):
        return [], positions

    unique_order_ids = list({pos.order_id for pos in positions if pos.order_id is not None})
    order_to_iid: dict[int, int] = {}
    for oid in unique_order_ids:
        iid = client.get_instrument_id_from_order(oid)
        if iid is not None:
            order_to_iid[oid] = iid

    resolved, still = [], []
    for pos in positions:
        iid = order_to_iid.get(pos.order_id) if pos.order_id else None
        if iid is not None:
            resolved.append(pos.model_copy(update={"instrument_id": iid}))
        else:
            still.append(pos)
    return resolved, still


def _empty_canonical_df() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype="object") for col in _CANONICAL_COLUMNS})


def _align_canonical_schema(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    for col in _CANONICAL_COLUMNS:
        if col in df.columns:
            out[col] = df[col].values
        else:
            out[col] = pd.NA
    return out.reset_index(drop=True)


def _api_positions_to_dataframe(
    positions: list[EtoroPosition],
    instruments: dict[int, EtoroInstrument],
    rates: dict[int, EtoroInstrumentRate],
    fx: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Converte posizioni API in DataFrame canonico con open_price/current_price in USD.

    v7.4.0:
      - Usa conversionRateAsk/Bid dall'API (già normalizzati nativo→USD)
        quando disponibili.
      - Fallback su _native_to_usd(fx) se il campo API non è presente.
      - currency impostata a "USD" (tutto normalizzato).
    """
    if fx is None:
        fx = _build_fx_cache()

    rows = []
    for pos in positions:
        inst = instruments.get(pos.instrument_id) if pos.instrument_id else None
        rate = rates.get(pos.instrument_id) if pos.instrument_id else None

        # ── Ticker display ────────────────────────────────────────────────
        if inst is not None:
            ticker = inst.best_symbol
        elif pos.ticker_from_api:
            ticker = pos.ticker_from_api
        elif pos.instrument_id is not None:
            ticker = f"#{pos.instrument_id}"
        else:
            ticker = "UNKNOWN"

        raw_action = (
            inst.name if inst and inst.name
            else (pos.display_name_from_api or ticker)
        )

        # ── Conversione FX: tasso nativo→USD ─────────────────────────────
        # Preferenza: conversionRate dall'API eToro (mid bid/ask).
        # Per SWDA.L: conversionRateBid ≈ GBX→USD ≈ 0.0127
        # Se assente: fallback su _native_to_usd con yfinance.
        native_currency = _get_instrument_currency(ticker)

        api_conv: float | None = None
        if rate is not None:
            bid = rate.conversion_rate_bid
            ask = rate.conversion_rate_ask
            if bid is not None and ask is not None:
                api_conv = (bid + ask) / 2.0
            elif bid is not None:
                api_conv = bid
            elif ask is not None:
                api_conv = ask

        def _to_usd(price_native: float) -> float:
            if api_conv is not None and api_conv > 0:
                return price_native * api_conv
            return _native_to_usd(price_native, native_currency, fx)

        open_price_usd = _to_usd(pos.open_rate)

        # ── Prezzo corrente (API rates o close_rate dall'unrealizedPnL) ──
        current_price_native: float | None = None
        if rate and rate.mid_price is not None:
            current_price_native = rate.mid_price
        elif pos.close_rate is not None:
            current_price_native = pos.close_rate

        current_price_usd = (
            _to_usd(current_price_native)
            if current_price_native is not None else None
        )

        market_value = (
            current_price_usd * pos.units
            if current_price_usd is not None and pos.units
            else None
        )
        profit_pct = (pos.pnl / pos.amount * 100.0) if pos.amount else None

        rows.append({
            "ticker":        ticker,
            "direction":     pos.direction,
            "quantity":      pos.units,
            "open_price":    open_price_usd,    # ← USD (convertito)
            "current_price": current_price_usd, # ← USD (convertito)
            "open_date":     pos.open_date_time,
            "market_value":  market_value,
            "profit_pct":    profit_pct,
            "profit_eur":    pos.pnl,
            "currency":      "USD",             # ← normalizzato
            "raw_action":    raw_action,
        })

    if not rows:
        return _empty_canonical_df()

    df = pd.DataFrame(rows, columns=_CANONICAL_COLUMNS)
    for col in (
        "quantity", "open_price", "current_price", "market_value",
        "profit_pct", "profit_eur",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_date"] = pd.to_datetime(df["open_date"], errors="coerce", utc=True)
    return df.reset_index(drop=True)
