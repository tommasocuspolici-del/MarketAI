"""Costruzione DataFrame canonico dalle posizioni eToro (API e XLSX).

Contiene tutta la logica di parsing, conversione FX e building del DataFrame.
Estratto da etoro_importer.py (ROADMAP_CODE_QUALITY_v1.0, Settimana 7, P6).
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import pandas as pd
import yfinance as yf

from engine.market_data.instrument_registry import InstrumentRegistry
from shared.resilience.error_policy import apply_error_policy

if TYPE_CHECKING:
    from personal.data_entry.etoro_client import EtoroClient
    from personal.data_entry.etoro_models import (
        EtoroInstrument,
        EtoroInstrumentRate,
        EtoroPosition,
    )

log = logging.getLogger(__name__)

# ─── Schema canonico ────────────────────────────────────────────────────────
_CANONICAL_COLUMNS = [
    "ticker", "direction", "quantity", "open_price", "current_price",
    "open_date", "market_value", "profit_pct", "profit_eur", "currency",
    "raw_action",
]

# ─── FX helpers ─────────────────────────────────────────────────────────────
_SUFFIX_TO_CURRENCY: dict[str, str] = {
    ".L":  "GBX", ".DE": "EUR", ".MI": "EUR",
    ".PA": "EUR", ".AS": "EUR", ".BR": "EUR", ".LS": "EUR",
}
_FX_FALLBACK: dict[str, float] = {"GBP_USD": 1.27, "EUR_USD": 1.08}

# ─── InstrumentRegistry singleton ───────────────────────────────────────────
_registry_instance: InstrumentRegistry | None = None


def _get_instrument_registry() -> InstrumentRegistry | None:
    global _registry_instance
    if _registry_instance is None:
        try:
            _registry_instance = InstrumentRegistry()
        except Exception:  # noqa: BLE001
            log.warning("etoro_position_builder: InstrumentRegistry non disponibile (DuckDB?)")
            return None
    return _registry_instance


def _get_instrument_currency(ticker: str) -> str:
    upper = ticker.upper()
    for suffix, ccy in _SUFFIX_TO_CURRENCY.items():
        if upper.endswith(suffix.upper()):
            return ccy
    return "USD"


def _fetch_fx_rate(yf_pair: str, fallback: float) -> float:
    try:
        t = yf.Ticker(yf_pair)
        fi = t.fast_info
        price = getattr(fi, "last_price", None)
        if price is not None and float(price) > 0:
            return float(price)
        hist = t.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as exc:  # noqa: BLE001
        log.warning("[RECOVER] etoro_position_builder._fetch_fx_rate: %s: %s", yf_pair, type(exc).__name__)
    return fallback


def _build_fx_cache() -> dict[str, float]:
    return {
        "GBP_USD": _fetch_fx_rate("GBPUSD=X", _FX_FALLBACK["GBP_USD"]),
        "EUR_USD": _fetch_fx_rate("EURUSD=X", _FX_FALLBACK["EUR_USD"]),
    }


def _native_to_usd(price: float, currency: str, fx: dict[str, float]) -> float:
    if currency == "GBX":
        return price / 100.0 * fx.get("GBP_USD", _FX_FALLBACK["GBP_USD"])
    if currency == "EUR":
        return price * fx.get("EUR_USD", _FX_FALLBACK["EUR_USD"])
    return float(price)


@apply_error_policy(level="RECOVER", fallback=None, context="etoro_position_builder._get_live_price_usd")
def _get_live_price_usd(ticker: str, fx: dict[str, float] | None = None) -> float | None:
    if fx is None:
        fx = _build_fx_cache()
    stock = yf.Ticker(ticker)
    data = stock.history(period="1d")
    if data.empty:
        return None
    price_native = float(data["Close"].iloc[-1])
    currency = _get_instrument_currency(ticker)
    return _native_to_usd(price_native, currency, fx)


def get_live_price_usd(ticker: str) -> float | None:
    """Public: prezzo live in USD per qualunque ticker (GBX/EUR/USD)."""
    return _get_live_price_usd(ticker, _build_fx_cache())


# ─── DataFrame builders ──────────────────────────────────────────────────────

def _empty_canonical_df() -> pd.DataFrame:
    return pd.DataFrame({col: pd.Series(dtype="object") for col in _CANONICAL_COLUMNS})


def _align_canonical_schema(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    for col in _CANONICAL_COLUMNS:
        out[col] = df[col].values if col in df.columns else pd.NA
    return out.reset_index(drop=True)


def _api_positions_to_dataframe(
    positions: list[EtoroPosition],
    instruments: dict[int, EtoroInstrument],
    rates: dict[int, EtoroInstrumentRate],
    fx: dict[str, float] | None = None,
) -> pd.DataFrame:
    if fx is None:
        fx = _build_fx_cache()
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
        native_currency = _get_instrument_currency(ticker)
        api_conv: float | None = None
        if rate is not None:
            bid, ask = rate.conversion_rate_bid, rate.conversion_rate_ask
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
        current_price_native: float | None = None
        if rate and rate.mid_price is not None:
            current_price_native = rate.mid_price
        elif pos.close_rate is not None:
            current_price_native = pos.close_rate
        current_price_usd = _to_usd(current_price_native) if current_price_native is not None else None
        market_value = current_price_usd * pos.units if current_price_usd is not None and pos.units else None
        profit_pct = (pos.pnl / pos.amount * 100.0) if pos.amount else None
        rows.append({
            "ticker": ticker, "direction": pos.direction, "quantity": pos.units,
            "open_price": open_price_usd, "current_price": current_price_usd,
            "open_date": pos.open_date_time, "market_value": market_value,
            "profit_pct": profit_pct, "profit_eur": pos.pnl, "currency": "USD",
            "raw_action": raw_action,
        })
    if not rows:
        return _empty_canonical_df()
    df = pd.DataFrame(rows, columns=_CANONICAL_COLUMNS)
    for col in ("quantity", "open_price", "current_price", "market_value", "profit_pct", "profit_eur"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_date"] = pd.to_datetime(df["open_date"], errors="coerce", utc=True)
    return df.reset_index(drop=True)


def _override_prices_for_numeric_tickers(
    df: pd.DataFrame, fx: dict[str, float] | None = None,
) -> pd.DataFrame:
    df = df.copy()
    if fx is None:
        fx = _build_fx_cache()
    for idx, row in df.iterrows():
        original_ticker = row["ticker"]
        real_ticker = row["real_ticker"]
        if not (original_ticker.startswith("#") and real_ticker and not real_ticker.startswith("#")):
            continue
        native_currency = _get_instrument_currency(real_ticker)
        price_usd = _get_live_price_usd(real_ticker, fx)
        if price_usd is None:
            log.warning("etoro_position_builder._override_prices: nessun prezzo per %s", real_ticker)
            continue
        open_price_native = row["open_price"]
        open_price_usd = (
            _native_to_usd(float(open_price_native), native_currency, fx)
            if pd.notna(open_price_native) and float(open_price_native) > 0 else 0.0
        )
        qty = float(row["quantity"]) if pd.notna(row["quantity"]) else 0.0
        market_value = qty * price_usd
        invested = open_price_usd * qty
        df.at[idx, "current_price"] = price_usd
        df.at[idx, "open_price"]    = open_price_usd
        df.at[idx, "market_value"]  = market_value
        df.at[idx, "profit_eur"]    = market_value - invested
        df.at[idx, "profit_pct"]    = ((market_value / invested) - 1) * 100 if invested > 0 else 0.0
        df.at[idx, "currency"]      = "USD"
    return df


# ─── Ticker resolution ───────────────────────────────────────────────────────

def _resolve_ticker_from_placeholder(ticker_col: str) -> str:
    if ticker_col.startswith("#"):
        iid_str = ticker_col[1:]
        if iid_str.isdigit():
            registry = _get_instrument_registry()
            if registry is not None:
                mapped = registry.get_ticker(int(iid_str))
                if mapped:
                    return mapped
    return ticker_col


def _resolve_real_ticker_for_row(row: pd.Series, instruments: dict[int, EtoroInstrument]) -> str:
    ticker = row["ticker"]
    if not ticker.startswith("#"):
        return ticker
    iid_str = ticker[1:]
    if not iid_str.isdigit():
        return ticker
    iid = int(iid_str)
    registry = _get_instrument_registry()
    if registry is not None:
        mapped = registry.get_ticker(iid)
        if mapped:
            return mapped
    if iid in instruments:
        return instruments[iid].best_symbol
    return ticker


def _extract_ticker_from_nome(nome: str) -> str:
    if not nome:
        return ""
    match = re.search(r'\(([A-Z0-9\.]+)\)$', str(nome).strip())
    return match.group(1) if match else nome


def _resolve_instrument_ids_via_orders(
    client: EtoroClient, positions: list[EtoroPosition],
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


# ─── API orchestration helper ────────────────────────────────────────────────

def build_api_positions_df(
    client: EtoroClient,
    all_positions: list[EtoroPosition],
) -> tuple[pd.DataFrame, int, int, str]:
    """Classifica, risolve e costruisce il DataFrame canonico dalle posizioni API.

    Returns:
        (df, n_resolvable, n_unresolvable, notes)
    """
    from personal.data_entry.etoro_client import EtoroClientError

    resolvable_with_id = [p for p in all_positions if p.instrument_id is not None]
    resolvable_ticker_only = [
        p for p in all_positions if p.instrument_id is None and p.ticker_from_api is not None
    ]
    candidate_via_order = [
        p for p in all_positions
        if p.instrument_id is None and p.ticker_from_api is None and p.order_id is not None
    ]
    unresolvable = [
        p for p in all_positions
        if p.instrument_id is None and p.ticker_from_api is None and p.order_id is None
    ]

    resolvable_via_order: list = []
    if candidate_via_order:
        resolved, still = _resolve_instrument_ids_via_orders(client, candidate_via_order)
        resolvable_via_order = resolved
        resolvable_with_id.extend(resolved)
        unresolvable.extend(still)

    n_unresolvable = len(unresolvable)
    n_resolvable = len(resolvable_with_id) + len(resolvable_ticker_only)

    instruments: dict = {}
    if resolvable_with_id:
        try:
            instruments = client.get_instruments(
                list({p.instrument_id for p in resolvable_with_id})  # type: ignore[arg-type]
            )
        except EtoroClientError as exc:
            log.warning("Lookup instrument fallito: %s", exc)

    rates: dict = {}
    if resolvable_with_id:
        try:
            rates = client.get_rates(
                [p.instrument_id for p in resolvable_with_id]  # type: ignore[arg-type]
            )
        except EtoroClientError as exc:
            log.warning("Lookup rates fallito: %s", exc)

    all_resolvable = resolvable_with_id + resolvable_ticker_only
    fx = _build_fx_cache()
    log.debug("etoro_position_builder.fx_cache GBP/USD=%.4f EUR/USD=%.4f", fx["GBP_USD"], fx["EUR_USD"])

    df = _api_positions_to_dataframe(all_resolvable, instruments, rates, fx)
    df["real_ticker"] = df.apply(lambda row: _resolve_real_ticker_for_row(row, instruments), axis=1)
    df = _override_prices_for_numeric_tickers(df, fx)

    notes_parts = [f"Importate {n_resolvable} posizioni via API."]
    if resolvable_ticker_only:
        notes_parts.append(f"{len(resolvable_ticker_only)} posizioni via ticker_from_api.")
    if resolvable_via_order:
        notes_parts.append(f"{len(resolvable_via_order)} posizioni risolte via orderId.")
    if n_unresolvable:
        notes_parts.append(f"{n_unresolvable} posizioni scartate.")

    return df, n_resolvable, n_unresolvable, " ".join(notes_parts)
