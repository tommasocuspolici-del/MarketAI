"""MarketContextBuilder — Settimana 8 Roadmap Unificata.

Costruisce MarketContextForPersonal leggendo i dati dal DB dell'engine.
Rule 21: engine/ ↔ personal/ SOLO via bridge/api_contracts.py.

Usato da P7_Scenari_Ricchezza (Monte Carlo con tasso engine),
P6_Profilo_Investitore (regime corrente), personal/allocator/.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from bridge.api_contracts import MarketContextForPersonal
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient
    from shared.db.macro_repo import MacroRepository

__version__ = "1.0.0"
__all__ = ["MarketContextBuilder", "build_market_context"]

log = get_logger(__name__)

_FALLBACK_RISK_FREE   = 0.045
_FALLBACK_EQ_RETURN   = 0.07
_FALLBACK_EQ_VOL      = 0.18
_FALLBACK_BOND_RETURN = 0.04
_FALLBACK_INFLATION   = 0.025


class MarketContextBuilder:
    """Costruisce MarketContextForPersonal dai dati DuckDB dell'engine."""

    def __init__(self, duckdb: DuckDBClient, macro_repo: MacroRepository) -> None:
        self._db   = duckdb
        self._repo = macro_repo

    def build(self) -> MarketContextForPersonal:
        risk_free_rate    = self._get_risk_free_rate()
        eq_return, eq_vol = self._get_equity_params()
        bond_return       = self._get_bond_return(risk_free_rate)
        inflation         = self._get_inflation()
        regime            = self._get_regime()
        vix               = self._get_vix()

        ctx = MarketContextForPersonal(
            as_of=datetime.now(UTC),
            risk_free_rate=risk_free_rate,
            equity_expected_return=eq_return,
            equity_volatility=eq_vol,
            bond_expected_return=bond_return,
            bond_volatility=max(eq_vol * 0.25, 0.03),  # ~1/4 equity vol
            inflation_rate=inflation,
            current_regime=regime,
            vix=vix,
        )
        log.info(
            "market_context.built",
            risk_free=round(risk_free_rate * 100, 2),
            eq_return=round(eq_return * 100, 2),
            eq_vol=round(eq_vol * 100, 2),
            regime=regime, vix=round(vix, 2),
        )
        return ctx

    def _get_risk_free_rate(self) -> float:
        try:
            df = self._repo.read_macro("FEDFUNDS")
            if df is not None and not df.empty:
                return float(df["value"].dropna().iloc[-1]) / 100.0
        except Exception:
            pass
        return _FALLBACK_RISK_FREE

    def _get_equity_params(self) -> tuple[float, float]:
        try:
            import numpy as np

            from shared.db.prices_repo import get_prices_repository
            from shared.types import TimeFrame
            df = get_prices_repository().read_prices(ticker="SPY", timeframe=TimeFrame.D1)
            if df is not None and len(df) >= 252:
                closes  = df["close"].dropna().to_numpy(dtype=np.float64)[-252:]
                log_ret = np.diff(np.log(closes))
                ann_ret = float(np.clip(np.mean(log_ret) * 252, 0.02, 0.20))
                ann_vol = float(np.clip(np.std(log_ret, ddof=1) * np.sqrt(252), 0.08, 0.40))
                return ann_ret, ann_vol
        except Exception:
            pass
        return _FALLBACK_EQ_RETURN, _FALLBACK_EQ_VOL

    def _get_bond_return(self, risk_free: float) -> float:
        try:
            df = self._repo.read_macro("DGS10")
            if df is not None and not df.empty:
                return float(df["value"].dropna().iloc[-1]) / 100.0
        except Exception:
            pass
        return max(risk_free - 0.005, 0.02)

    def _get_inflation(self) -> float:
        try:
            df = self._repo.read_macro("CPIAUCSL")
            if df is not None and not df.empty:
                return float(df["value"].dropna().iloc[-1]) / 100.0
        except Exception:
            pass
        return _FALLBACK_INFLATION

    def _get_regime(self) -> str:
        try:
            rows = self._db.query(
                "SELECT regime FROM regime_reports ORDER BY computed_at DESC LIMIT 1"
            )
            if rows and rows[0][0]:
                return str(rows[0][0])
        except Exception:
            pass
        return "transition"

    def _get_vix(self) -> float:
        try:
            rows = self._db.query(
                "SELECT vix_level FROM vix_signals ORDER BY computed_at DESC LIMIT 1"
            )
            if rows and rows[0][0]:
                return float(rows[0][0])
        except Exception:
            pass
        return 20.0


def build_market_context() -> MarketContextForPersonal:
    """Factory function per uso rapido da UI senza DI manuale."""
    from shared.db.duckdb_client import get_duckdb_client
    from shared.db.macro_repo import get_macro_repository
    builder = MarketContextBuilder(
        duckdb=get_duckdb_client(),
        macro_repo=get_macro_repository(),
    )
    return builder.build()
