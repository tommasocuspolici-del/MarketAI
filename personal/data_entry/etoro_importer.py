"""EtoroImporter: facade unica (v7.3.1) con aggregazione, ticker reali e prezzi live.

Novità v7.3.1:
  - Estrazione ticker reale per tutte le posizioni (API e XLSX).
  - Metodo aggregate_by_real_ticker() per unire posizioni con lo stesso
    ticker sottostante (corregge l'errore #3040).
  - Funzione update_live_prices() che recupera prezzi da yfinance e
    ricalcola market value / profit, risolvendo il problema del valore
    totale errato.
  - Metodo get_portfolio_overview() per inserire i dati eToro nella
    sezione "patrimonio" dell'applicazione.
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

__version__ = "7.3.1"

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

# Mapping manuale instrument_id → ticker reale (ultima risorsa se l'API non fornisce il ticker)
_MANUAL_TICKER_MAP: dict[int, str] = {
    3040: "CSPX",
    # aggiungere altri id se necessario
}


def _extract_real_ticker_from_raw(ticker_col: str, instrument_id: int | None = None) -> str:
    """Determina il ticker reale da una stringa 'ticker' del DataFrame canonico."""
    if ticker_col.startswith("#"):
        # è un placeholder "#id"
        iid = int(ticker_col[1:]) if ticker_col[1:].isdigit() else None
        if iid and iid in _MANUAL_TICKER_MAP:
            return _MANUAL_TICKER_MAP[iid]
        return ticker_col  # nessun mapping
    return ticker_col


class EtoroImporter:
    """Facade unificata per import posizioni eToro.

    Aggiunte le capacità di estrazione ticker reale, aggregazione e
    aggiornamento prezzi live.
    """

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
        return "ℹ️ Credenziali API eToro assenti: userai il file XLSX."

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
                return self.import_via_xlsx(xlsx_source, notes=f"Fallback dopo errore API: {exc}")
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

        # Classificazione (tier 1-4) – invariata rispetto alla 7.3.0
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
            resolved, still = _resolve_instrument_ids_via_orders(client, candidate_via_order)
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
                notes=f"Tutte le {n_unresolvable} posizioni sono irrecuperabili.",
            )

        instruments: dict[int, EtoroInstrument] = {}
        if resolvable_with_id:
            instrument_ids = list({p.instrument_id for p in resolvable_with_id})  # type: ignore
            try:
                instruments = client.get_instruments(instrument_ids)
            except EtoroClientError as exc:
                log.warning("Lookup instrument fallito: %s", exc)

        rates: dict[int, EtoroInstrumentRate] = {}
        if resolvable_with_id:
            try:
                rates = client.get_rates([p.instrument_id for p in resolvable_with_id])  # type: ignore
            except EtoroClientError as exc:
                log.warning("Lookup rates fallito: %s", exc)

        all_resolvable = resolvable_with_id + resolvable_ticker_only
        df = _api_positions_to_dataframe(all_resolvable, instruments, rates)

        # Aggiungi colonna 'real_ticker' basandosi sulla risoluzione strumento
        df["real_ticker"] = df.apply(
            lambda row: _resolve_real_ticker_for_row(row, instruments, client),
            axis=1,
        )

        # Costruzione note
        notes_parts = [f"Importate {n_resolvable} posizioni via API."]
        if len(resolvable_ticker_only) > 0:
            notes_parts.append(
                f"{len(resolvable_ticker_only)} posizioni importate tramite ticker_from_api."
            )
        if len(resolvable_via_order) > 0:
            notes_parts.append(
                f"{len(resolvable_via_order)} posizioni risolte via orderId."
            )
        if n_unresolvable > 0:
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

        # Allinea al formato canonico
        df = _align_canonical_schema(df)

        # Estrai ticker reale dalla colonna "Nome" se presente
        if "Nome" in df.columns:
            df["real_ticker"] = df["Nome"].apply(_extract_ticker_from_nome)
        else:
            # Se non c'è Nome, prova a usare il ticker normale
            df["real_ticker"] = df["ticker"].apply(
                lambda x: _extract_real_ticker_from_raw(x)
            )

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

    def get_portfolio_overview(self, df: pd.DataFrame, etoro_total_value: float = 0.0) -> dict:
        """Restituisce un dizionario pronto per la sezione patrimonio."""
        aggr = _aggregate_positions(df)
        return {
            "eToro": {
                "valore_corrente": etoro_total_value if etoro_total_value else aggr["market_value"].sum(),
                "posizioni": aggr.to_dict(orient="records"),
                "aggiornato_il": pd.Timestamp.now().isoformat(),
            }
        }


# ─────────────────────────────────────────────────────── helpers pubblici
def update_live_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Sostituisce current_price e ricalcola market_value/profit usando yfinance."""
    if "real_ticker" not in df.columns:
        # Prova a determinarlo dalla colonna ticker
        df["real_ticker"] = df["ticker"].apply(lambda x: _extract_real_ticker_from_raw(x))
    df = df.copy()
    total = len(df)
    for idx, row in df.iterrows():
        real_ticker = row["real_ticker"]
        price = _get_live_price_yfinance(real_ticker)
        if price is not None:
            df.at[idx, "current_price"] = price
            qty = row["quantity"]
            df.at[idx, "market_value"] = qty * price
            invested = row["open_price"] * qty
            df.at[idx, "profit_eur"] = (qty * price) - invested
            df.at[idx, "profit_pct"] = ((qty * price) / invested - 1) * 100 if invested else 0.0
    return df


def aggregate_by_real_ticker(df: pd.DataFrame) -> pd.DataFrame:
    """Funzione standalone per aggregare."""
    return _aggregate_positions(df)


# ─────────────────────────────────────────────────────── funzioni interne
def _resolve_real_ticker_for_row(
    row: pd.Series,
    instruments: dict[int, EtoroInstrument],
    client: EtoroClient | None = None,
) -> str:
    """Restituisce il ticker reale per una riga del DataFrame API."""
    ticker = row["ticker"]
    if not ticker.startswith("#"):
        return ticker
    # Prova a estrarre l'instrument_id dal placeholder "#1234"
    iid_str = ticker[1:]
    if iid_str.isdigit():
        iid = int(iid_str)
        if iid in _MANUAL_TICKER_MAP:
            return _MANUAL_TICKER_MAP[iid]
        if iid in instruments:
            return instruments[iid].best_symbol
        # Ultimo tentativo: search API (costoso, meglio evitare in loop)
        if client:
            try:
                results = client.search_instrument(ticker)
                if results:
                    return results[0].best_symbol
            except Exception:
                pass
    return ticker  # fallback


def _extract_ticker_from_nome(nome: str) -> str:
    """Estrae il ticker reale da una stringa Nome (es. 'iShares Core S&P 500 (CSPX)')"""
    if not nome:
        return ""
    match = re.search(r'\(([A-Z0-9\.]+)\)$', str(nome).strip())
    if match:
        return match.group(1)
    return nome  # No parentesi, restituisci Nome come ticker


def _get_live_price_yfinance(ticker: str) -> float | None:
    """Prezzo live via yfinance con mappatura degli exchange noti."""
    exchange_map = {
        "CSPX": "CSPX.L",
        "VOO": "VOO",
        "QQQ": "QQQ",
        # Aggiungi altri se necessario
    }
    symbol = exchange_map.get(ticker.upper(), ticker)
    try:
        stock = yf.Ticker(symbol)
        data = stock.history(period="1d")
        if not data.empty:
            return data["Close"].iloc[-1]
    except Exception:
        pass
    return None


def _aggregate_positions(df: pd.DataFrame) -> pd.DataFrame:
    """Raggruppa per real_ticker, somma quantità, calcola prezzo medio ponderato e market value."""
    if "real_ticker" not in df.columns:
        raise ValueError("DataFrame must have 'real_ticker' column. Run update_live_prices or assign it first.")
    grouped = df.groupby("real_ticker", as_index=False).agg(
        total_units=("quantity", "sum"),
        total_invested=("open_price", lambda x, q=df.loc[x.index, "quantity"]: (x * q).sum() if len(x) > 0 else 0),
        last_current_price=("current_price", "last"),
        raw_action=("raw_action", "first"),
    )
    grouped["avg_open_price"] = grouped["total_invested"] / grouped["total_units"]
    grouped["market_value"] = grouped["total_units"] * grouped["last_current_price"]
    grouped["profit_eur"] = grouped["market_value"] - grouped["total_invested"]
    grouped["profit_pct"] = (grouped["profit_eur"] / grouped["total_invested"]) * 100
    return grouped.rename(columns={"real_ticker": "ticker"})


def _resolve_instrument_ids_via_orders(
    client: EtoroClient, positions: list[EtoroPosition]
) -> tuple[list[EtoroPosition], list[EtoroPosition]]:
    if not positions:
        return [], []
    if not hasattr(client, "get_instrument_id_from_order"):
        log.warning("EtoroClient non supporta get_instrument_id_from_order.")
        return [], positions

    unique_order_ids = list({p.order_id for p in positions if p.order_id is not None})
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

        raw_action = inst.name if inst and inst.name else (pos.display_name_from_api or ticker)

        current_price: float | None = None
        if rate and rate.mid_price is not None:
            current_price = rate.mid_price
        elif pos.close_rate is not None:
            current_price = pos.close_rate

        market_value = current_price * pos.units if current_price is not None and pos.units else None
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
    for col in ("quantity", "open_price", "current_price", "market_value", "profit_pct", "profit_eur"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_date"] = pd.to_datetime(df["open_date"], errors="coerce", utc=True)
    return df.reset_index(drop=True)