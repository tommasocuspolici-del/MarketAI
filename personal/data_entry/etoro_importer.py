"""EtoroImporter: facade unica (v7.3.3) con mappatura ticker numerici e prezzi live.

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

__version__ = "7.3.3"

__all__ = [
    "EtoroImporter",
    "EtoroImportError",
    "EtoroImportResult",
    "update_live_prices",
    "aggregate_by_real_ticker",
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
#  I ticker devono essere nel formato riconosciuto da yfinance
#  (es. "SWDA.L" per ETF su Borsa Italiana / Xetra, "CSPX.L" per LSE).
# ───────────────────────────────────────────────────────────────
_INSTRUMENT_ID_TO_REAL_TICKER: dict[int, str] = {
    3040: "EUNL.DE",      # iShares Core MSCI World UCITS ETF (EUR, Xetra) – ISIN IE00B4L5Y983
    3434: "CSPX.L",       # iShares Core S&P 500 UCITS ETF (GBX, LSE)
    15435: "EIMI.L",      # iShares Core MSCI EM IMI UCITS ETF (GBX, LSE)
    3394: "EUN5.DE",      # iShares EUR Corp Bond UCITS ETF (EUR, Xetra?)
    10569: "IBCN.DE",     # iShares EUR Govt Bond 3-7yr UCITS ETF (EUR, Xetra?)
    # ... aggiungi qui altre corrispondenze
}

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
        return (
            "ℹ️ Credenziali API eToro assenti: sarà usato il file XLSX."
        )

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

        # Quote correnti (API) – non le useremo più per i ticker numerici,
        # ma la chiamata resta per eventuali ticker "normali" (non numerici).
        rates: dict[int, EtoroInstrumentRate] = {}
        if resolvable_with_id:
            try:
                rates = client.get_rates(
                    [p.instrument_id for p in resolvable_with_id]  # type: ignore
                )
            except EtoroClientError as exc:
                log.warning("Lookup rates fallito: %s", exc)

        all_resolvable = resolvable_with_id + resolvable_ticker_only
        df = _api_positions_to_dataframe(all_resolvable, instruments, rates)

        # Aggiungi colonna real_ticker basata sulla mappatura
        df["real_ticker"] = df.apply(
            lambda row: _resolve_real_ticker_for_row(row, instruments), axis=1
        )

        # Sostituisci i prezzi per le righe con ticker numerici
        # usando il prezzo live da Yahoo Finance (ignora l'eventuale prezzo API)
        df = _override_prices_for_numeric_tickers(df)

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

        # Se la colonna "Nome" esiste, estrai il ticker reale da lì,
        # altrimenti usa la mappatura sul ticker numerico.
        if "Nome" in df.columns:
            df["real_ticker"] = df["Nome"].apply(_extract_ticker_from_nome)
        else:
            df["real_ticker"] = df["ticker"].apply(_resolve_ticker_from_placeholder)

        # Anche per XLSX, sovrascrivi i prezzi se il ticker è numerico
        df = _override_prices_for_numeric_tickers(df)

        return EtoroImportResult(
            positions=df,
            source="xlsx",
            n_positions=len(df),
            notes=notes or "Parsing XLSX completato.",
        )

    # ── Nuove funzionalità pubbliche ─────────────────────────────────
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
    """
    if "real_ticker" not in df.columns:
        # Tenta di ricavarlo dalla colonna ticker
        df = df.copy()
        df["real_ticker"] = df["ticker"].apply(_resolve_ticker_from_placeholder)
    else:
        df = df.copy()

    for idx, row in df.iterrows():
        ticker = row["real_ticker"]
        # Salta se il ticker è ancora un placeholder o vuoto
        if not ticker or ticker.startswith("#"):
            continue
        price = _get_live_price_yfinance(ticker)
        if price is not None:
            df.at[idx, "current_price"] = price
            qty = row["quantity"]
            df.at[idx, "market_value"] = qty * price
            invested = row["open_price"] * qty
            df.at[idx, "profit_eur"] = (qty * price) - invested
            df.at[idx, "profit_pct"] = (
                ((qty * price) / invested - 1) * 100 if invested else 0.0
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
        # Non mappato: restituisci il placeholder originale (non facciamo danni)
    return ticker_col


def _resolve_real_ticker_for_row(
    row: pd.Series,
    instruments: dict[int, EtoroInstrument],
) -> str:
    """Determina il ticker reale per una riga proveniente dall'API.
    
    Priorità:
    1. Ticker non numerico (già un simbolo reale) → restituiscilo così.
    2. Placeholder `#id` con id presente nella mappatura manuale → usa quella.
    3. Placeholder `#id` con id risolto via /instruments → usa best_symbol
       dello strumento (spesso è ancora un ticker generico, ma meglio di #id).
    4. Altrimenti mantieni il placeholder.
    """
    ticker = row["ticker"]
    if not ticker.startswith("#"):
        return ticker

    iid_str = ticker[1:]
    if not iid_str.isdigit():
        return ticker
    iid = int(iid_str)

    # Mappatura manuale ha la precedenza
    if iid in _INSTRUMENT_ID_TO_REAL_TICKER:
        return _INSTRUMENT_ID_TO_REAL_TICKER[iid]

    # Fallback: cerca fra gli strumenti risolti
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


def _get_live_price_yfinance(ticker: str) -> float | None:
    """Prezzo live via yfinance, con mappatura exchange se necessario."""
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period="1d")
        if not data.empty:
            return data["Close"].iloc[-1]
    except Exception:
        pass
    return None


def _override_prices_for_numeric_tickers(df: pd.DataFrame) -> pd.DataFrame:
    """Per le righe il cui ticker originario era un placeholder (#...), 
    rimpiazza il prezzo con quello live da yfinance e ricalcola le metriche.
    """
    df = df.copy()
    for idx, row in df.iterrows():
        original_ticker = row["ticker"]
        real_ticker = row["real_ticker"]
        # Se il ticker originale è un placeholder e abbiamo un real_ticker valido,
        # oppure il real_ticker è stato mappato esplicitamente
        if original_ticker.startswith("#") and real_ticker and not real_ticker.startswith("#"):
            price = _get_live_price_yfinance(real_ticker)
            if price is not None:
                df.at[idx, "current_price"] = price
                qty = row["quantity"]
                # Gestione NaN nel prezzo di carico
                invested = (row["open_price"] * qty) if pd.notna(row["open_price"]) else 0.0
                df.at[idx, "market_value"] = qty * price
                df.at[idx, "profit_eur"] = (qty * price) - invested
                df.at[idx, "profit_pct"] = (
                    ((qty * price) / invested - 1) * 100 if invested else 0.0
                )
    return df


def _aggregate_positions(df: pd.DataFrame) -> pd.DataFrame:
    """Raggruppa per real_ticker, somma quantità, calcola prezzo medio ponderato e market value."""
    if "real_ticker" not in df.columns:
        raise ValueError("DataFrame must have 'real_ticker' column.")
    
    # Assicuriamoci che le colonne numeriche siano pulite
    for col in ["quantity", "open_price", "current_price"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    
    # Calcoliamo il valore investito per riga per un'aggregazione sicura
    df["invested_value"] = df["open_price"] * df["quantity"]
    
    grouped = df.groupby("real_ticker", as_index=False).agg(
        total_units=("quantity", "sum"),
        total_invested=("invested_value", "sum"),
        last_current_price=("current_price", "last"),
        raw_action=("raw_action", "first"),
    )
    grouped["avg_open_price"] = grouped["total_invested"] / grouped["total_units"]
    grouped["market_value"] = grouped["total_units"] * grouped["last_current_price"]
    grouped["profit_eur"] = grouped["market_value"] - grouped["total_invested"]
    # Evitiamo divisioni per zero
    grouped["profit_pct"] = (grouped["profit_eur"] / grouped["total_invested"].replace(0, pd.NA)) * 100
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
) -> pd.DataFrame:
    rows = []
    for pos in positions:
        inst = instruments.get(pos.instrument_id) if pos.instrument_id else None
        rate = rates.get(pos.instrument_id) if pos.instrument_id else None

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

        current_price: float | None = None
        if rate and rate.mid_price is not None:
            current_price = rate.mid_price
        elif pos.close_rate is not None:
            current_price = pos.close_rate

        market_value = (
            current_price * pos.units
            if current_price is not None and pos.units
            else None
        )
        profit_pct = (pos.pnl / pos.amount * 100.0) if pos.amount else None

        rows.append({
            "ticker": ticker,
            "direction": pos.direction,
            "quantity": pos.units,
            "open_price": pos.open_rate,
            "current_price": current_price,
            "open_date": pos.open_date_time,
            "market_value": market_value,
            "profit_pct": profit_pct,
            "profit_eur": pos.pnl,
            "currency": "USD",
            "raw_action": raw_action,
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