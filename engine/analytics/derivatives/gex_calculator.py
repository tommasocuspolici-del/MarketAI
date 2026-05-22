"""Gamma Exposure (GEX) Calculator.

GEX = Σ_strike (Γ × OI × spot²) per call - Σ (Γ × OI × spot²) per put
GEX > 0 → market maker long gamma → smorzamento volatilità (mean reversion)
GEX < 0 → market maker short gamma → amplificazione volatilità (trend)

Dati: strike/OI da Yahoo Finance options chain (EOD)
Feature flag: gex_calculator (default: false)

Il zero-gamma level (flip point) è lo strike dove il GEX cumulativo
cambia segno — livello di supporto/resistenza chiave.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

from shared.feature_flags import is_enabled
from shared.logger import get_logger

__version__ = "11.0.0"

__all__ = ["GEXCalculator", "GEXResult"]

log = get_logger(__name__)

FEATURE_FLAG = "gex_calculator"
RISK_FREE_RATE: float = 0.05


@dataclass
class GEXResult:
    """Risultato calcolo Gamma Exposure per un asset."""

    ticker: str
    total_gex: float            # Σ GEX positivo - Σ GEX negativo (in $ gamma)
    call_gex: float
    put_gex: float
    zero_gamma_level: float     # strike dove GEX ≈ 0 (flipping point)
    is_positive_gamma: bool     # True if total_gex > 0
    gex_by_strike: pd.DataFrame  # strike → gex


class GEXCalculator:
    """Calcola Gamma Exposure da option chain.

    Gamma Black-Scholes: Γ = N'(d1) / (S × σ × sqrt(T))
    GEX per contratto = Γ × OI × S² × 100  (100 = contract multiplier)
    Call GEX positivo (MM long gamma), Put GEX negativo (MM short gamma).
    """

    CONTRACT_MULTIPLIER: int = 100  # opzioni standard USA

    def __init__(self, risk_free_rate: float = RISK_FREE_RATE) -> None:
        self._r = risk_free_rate

    def compute(
        self,
        option_chain: pd.DataFrame,
        spot_price: float,
        days_to_expiry: int,
    ) -> GEXResult:
        """Calcola GEX per una singola scadenza.

        Parameters
        ----------
        option_chain:
            DataFrame con colonne: strike, optionType (call/put),
            openInterest, impliedVolatility.
        spot_price:
            Prezzo spot corrente.
        days_to_expiry:
            Giorni alla scadenza.
        """
        required = {"strike", "optionType", "openInterest", "impliedVolatility"}
        if not required.issubset(set(option_chain.columns)):
            missing = required - set(option_chain.columns)
            log.warning("gex.missing_columns", missing=missing)
            return self._empty_result("unknown", spot_price)

        if spot_price <= 0 or days_to_expiry <= 0:
            log.warning("gex.invalid_inputs", spot=spot_price, dte=days_to_expiry)
            return self._empty_result("unknown", spot_price)

        T = days_to_expiry / 365.0
        chain = option_chain.copy()
        chain["openInterest"] = pd.to_numeric(chain["openInterest"], errors="coerce").fillna(0)
        chain["impliedVolatility"] = pd.to_numeric(chain["impliedVolatility"], errors="coerce").fillna(0)
        chain = chain[chain["openInterest"] > 0]
        chain = chain[chain["impliedVolatility"] > 0]

        gex_records: list[dict] = []
        for _, row in chain.iterrows():
            K = float(row["strike"])
            sigma = float(row["impliedVolatility"])
            oi = float(row["openInterest"])
            opt_type = str(row["optionType"]).lower()

            if sigma < 1e-6 or K <= 0:
                continue

            gamma = self._black_scholes_gamma(spot_price, K, T, self._r, sigma)
            gex_value = gamma * oi * spot_price**2 * self.CONTRACT_MULTIPLIER

            # Call → MM long → GEX positivo; Put → MM short → GEX negativo
            if "put" in opt_type:
                gex_value = -gex_value

            gex_records.append({"strike": K, "gex": gex_value, "optionType": opt_type})

        if not gex_records:
            return self._empty_result("unknown", spot_price)

        gex_df = pd.DataFrame(gex_records)
        gex_by_strike = gex_df.groupby("strike")["gex"].sum().reset_index()
        gex_by_strike = gex_by_strike.sort_values("strike").reset_index(drop=True)

        call_gex = float(gex_df[gex_df["optionType"].str.contains("call")]["gex"].sum())
        put_gex = float(gex_df[gex_df["optionType"].str.contains("put")]["gex"].sum())
        total_gex = call_gex + put_gex

        # Zero-gamma level: strike dove GEX cumulativo cambia segno
        zero_gamma = self._find_zero_gamma_level(gex_by_strike, spot_price)

        log.info(
            "gex.computed",
            total_gex=round(total_gex / 1e6, 2),  # in milioni
            call_gex=round(call_gex / 1e6, 2),
            put_gex=round(put_gex / 1e6, 2),
            zero_gamma_level=round(zero_gamma, 2),
        )

        return GEXResult(
            ticker="",
            total_gex=total_gex,
            call_gex=call_gex,
            put_gex=put_gex,
            zero_gamma_level=zero_gamma,
            is_positive_gamma=total_gex > 0,
            gex_by_strike=gex_by_strike,
        )

    def _black_scholes_gamma(
        self,
        S: float,
        K: float,
        T: float,
        r: float,
        sigma: float,
    ) -> float:
        """Gamma Black-Scholes: N'(d1) / (S × σ × sqrt(T)).

        Uguale per call e put (proprietà della formula BS).
        """
        if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
            return 0.0

        try:
            d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
            gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
            return float(gamma)
        except (ValueError, ZeroDivisionError, FloatingPointError):
            return 0.0

    def compute_multi_expiry(
        self,
        chains_by_expiry: dict[int, pd.DataFrame],
        spot_price: float,
    ) -> GEXResult:
        """Aggrega GEX su più scadenze pesato per Open Interest.

        Parameters
        ----------
        chains_by_expiry:
            Mappa days_to_expiry → option chain DataFrame.
        spot_price:
            Prezzo spot corrente.
        """
        all_gex_records: list[pd.DataFrame] = []
        total_call_gex = 0.0
        total_put_gex = 0.0

        for dte, chain in chains_by_expiry.items():
            result = self.compute(chain, spot_price, dte)
            if not result.gex_by_strike.empty:
                all_gex_records.append(result.gex_by_strike)
            total_call_gex += result.call_gex
            total_put_gex += result.put_gex

        if not all_gex_records:
            return self._empty_result("", spot_price)

        combined = pd.concat(all_gex_records, ignore_index=True)
        gex_by_strike = combined.groupby("strike")["gex"].sum().reset_index()
        gex_by_strike = gex_by_strike.sort_values("strike").reset_index(drop=True)

        total_gex = total_call_gex + total_put_gex
        zero_gamma = self._find_zero_gamma_level(gex_by_strike, spot_price)

        return GEXResult(
            ticker="",
            total_gex=total_gex,
            call_gex=total_call_gex,
            put_gex=total_put_gex,
            zero_gamma_level=zero_gamma,
            is_positive_gamma=total_gex > 0,
            gex_by_strike=gex_by_strike,
        )

    def _find_zero_gamma_level(
        self,
        gex_by_strike: pd.DataFrame,
        spot_price: float,
    ) -> float:
        """Trova lo strike dove il GEX cumulativo cambia segno.

        Ordina gli strike e calcola la somma cumulativa del GEX.
        Il flip point è lo strike dove il segno cambia.
        """
        if gex_by_strike.empty:
            return spot_price

        sorted_df = gex_by_strike.sort_values("strike")
        cum_gex = sorted_df["gex"].cumsum().to_numpy()
        strikes = sorted_df["strike"].to_numpy()

        # Trova cambio di segno
        for i in range(len(cum_gex) - 1):
            if cum_gex[i] * cum_gex[i + 1] <= 0:
                # Interpolazione lineare tra i due strike
                return float(strikes[i])

        # Nessun flip: ritorna ATM (strike più vicino a spot)
        idx = int(np.argmin(np.abs(strikes - spot_price)))
        return float(strikes[idx])

    @staticmethod
    def _empty_result(ticker: str, spot_price: float) -> GEXResult:
        return GEXResult(
            ticker=ticker,
            total_gex=0.0,
            call_gex=0.0,
            put_gex=0.0,
            zero_gamma_level=spot_price,
            is_positive_gamma=False,
            gex_by_strike=pd.DataFrame(columns=["strike", "gex"]),
        )
