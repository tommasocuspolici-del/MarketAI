"""Aggregazione posizioni e aggiornamento prezzi live eToro.

Estratto da etoro_importer.py (ROADMAP_CODE_QUALITY_v1.0, Settimana 7, P6).
"""
from __future__ import annotations

import logging

import pandas as pd

from personal.data_entry.etoro_position_builder import (
    _build_fx_cache,
    _get_live_price_usd,
    _resolve_ticker_from_placeholder,
)

log = logging.getLogger(__name__)


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


def aggregate_by_real_ticker(df: pd.DataFrame) -> pd.DataFrame:
    """Aggrega posizioni con lo stesso ticker reale.

    Args:
        df: DataFrame canonico con colonna ``real_ticker``. Deve contenere
            almeno ``quantity``, ``open_price``, ``current_price``.

    Returns:
        DataFrame aggregato: una riga per ticker con ``total_units``,
        ``avg_open_price``, ``market_value``, ``profit_eur``, ``profit_pct``.
    """
    return _aggregate_positions(df)


def update_live_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Sostituisce current_price e ricalcola market_value/profit usando yfinance.

    Args:
        df: DataFrame canonico con colonna ``real_ticker`` (o ``ticker`` con
            placeholder ``#ID`` che vengono risolti internamente).

    Returns:
        Copia del DataFrame con ``current_price``, ``market_value``,
        ``profit_eur``, ``profit_pct`` aggiornati per i ticker con prezzo
        disponibile su yfinance. Ticker ``#ID`` non risolvibili sono lasciati
        invariati. Prezzi sempre in USD (conversione GBX/EUR applicata).
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
