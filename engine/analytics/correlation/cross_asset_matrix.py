"""Cross-Asset Correlation Matrix regime-conditioned.

Calcola correlazioni per 13 asset cross-class: equity, bond, credit, commodity, FX, VIX.
Produce diversification score e segnale per Composite Signal v2.

Performance target: < 500ms per 13 asset su 5 anni (Rule 30).
Regola 8: numpy per calcoli.
Regola 27: persist via DuckDB.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from engine.analytics.correlation.dcc_ewma_enhanced import DCCEWMAEnhanced

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
log = logging.getLogger(__name__)

# Asset universe cross-class (configurabile in correlation_v2.yaml)
_DEFAULT_UNIVERSE: dict[str, str] = {
    "SPY":     "us_equity_large",
    "IWM":     "us_equity_small",
    "QQQ":     "us_equity_tech",
    "TLT":     "bond_long",
    "IEF":     "bond_medium",
    "HYG":     "credit_hy",
    "LQD":     "credit_ig",
    "GLD":     "commodity_gold",
    "USO":     "commodity_oil",
    "COPX":    "commodity_copper",
    "UUP":     "fx_dollar",
    "FXE":     "fx_euro",
    "^VIX":    "volatility",
}

_TABLE = "cross_asset_regime"


@dataclass
class CrossAssetMatrixResult:
    """Output CrossAssetMatrix."""
    snapshot_date:        date
    correlation_matrix:   np.ndarray  # type: ignore[type-arg]
    asset_names:          list[str]
    avg_equity_bond_corr: float | None
    avg_equity_gold_corr: float | None
    credit_equity_corr:   float | None
    diversification_score: float           # [0,1]
    correlation_signal:   float            # [-1,+1] per Composite
    vix_regime:           str              # 'crisis_coupling'|'normal'|'divergence'
    regime_matrices:      dict[str, np.ndarray] = field(default_factory=dict)  # type: ignore[type-arg]


class CrossAssetMatrix:
    """Calcola matrice di correlazione cross-asset regime-conditioned.

    Args:
        client:    DuckDBClient per persistenza.
        universe:  Dict ticker â†’ categoria asset.

    Usage::

        matrix = CrossAssetMatrix(client=get_duckdb_client())
        result = matrix.compute(returns_df)
        print(result.diversification_score)
    """

    def __init__(
        self,
        client: DuckDBClient | None = None,
        universe: dict[str, str] | None = None,
    ) -> None:
        self._client  = client
        self._universe = universe or _DEFAULT_UNIVERSE
        self._ewma = DCCEWMAEnhanced()

    def compute(
        self,
        returns: pd.DataFrame,
        regime_labels: pd.Series | None = None,
        snapshot_date: date | None = None,
    ) -> CrossAssetMatrixResult:
        """Calcola correlazioni cross-asset e genera segnale.

        Args:
            returns:       DataFrame rendimenti log (col=asset, row=date).
            regime_labels: Serie con regime per ogni data.
            snapshot_date: Data snapshot (default oggi).

        Returns:
            CrossAssetMatrixResult con tutte le metriche.
        """
        snapshot_date = snapshot_date or date.today()

        # Filtra per asset universe disponibili
        available = [a for a in self._universe if a in returns.columns]
        if len(available) < 3:
            log.warning("cross_asset_matrix.insufficient_assets n=%d", len(available))
            return self._empty_result(snapshot_date, available)

        r = returns[available].dropna(how="all")
        ewma_result = self._ewma.compute(r, regime_labels)

        # Aggregati chiave
        avg_eq_bond  = self._avg_correlation(ewma_result.correlation_matrix, available,
                                              ["SPY","IWM","QQQ"], ["TLT","IEF"])
        avg_eq_gold  = self._avg_correlation(ewma_result.correlation_matrix, available,
                                              ["SPY","IWM"], ["GLD"])
        credit_eq    = self._avg_correlation(ewma_result.correlation_matrix, available,
                                              ["HYG","LQD"], ["SPY"])

        diversification = self._diversification_score(ewma_result.correlation_matrix)
        vix_regime      = self._classify_vix_regime(ewma_result.correlation_matrix, available)

        # Segnale correlazione per Composite v2:
        # Alta diversificazione = segnale positivo (mercati sani, non in panico)
        corr_signal = self._compute_signal(diversification, ewma_result.correlation_matrix, available)

        result = CrossAssetMatrixResult(
            snapshot_date=snapshot_date,
            correlation_matrix=ewma_result.correlation_matrix,
            asset_names=available,
            avg_equity_bond_corr=avg_eq_bond,
            avg_equity_gold_corr=avg_eq_gold,
            credit_equity_corr=credit_eq,
            diversification_score=diversification,
            correlation_signal=corr_signal,
            vix_regime=vix_regime,
        )

        if self._client:
            self._persist(result)

        return result

    # â”€â”€â”€ Aggregati â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    @staticmethod
    def _avg_correlation(
        matrix: np.ndarray,  # type: ignore[type-arg]
        names: list[str],
        group_a: list[str],
        group_b: list[str],
    ) -> float | None:
        """Media delle correlazioni tra asset del gruppo A e del gruppo B."""
        idxA = [names.index(a) for a in group_a if a in names]
        idxB = [names.index(b) for b in group_b if b in names]
        if not idxA or not idxB:
            return None
        vals = [matrix[i, j] for i in idxA for j in idxB]
        return float(np.mean(vals)) if vals else None

    @staticmethod
    def _diversification_score(matrix: np.ndarray) -> float:  # type: ignore[type-arg]
        """D = 1 - mean(|off-diagonal correlations|).

        D=1: portfolio non correlato (max diversificazione).
        D=0: tutti si muovono insieme (crisi).
        """
        n = matrix.shape[0]
        if n < 2:
            return 1.0
        off_diag = matrix[np.triu_indices(n, k=1)]
        return float(np.clip(1.0 - np.mean(np.abs(off_diag)), 0.0, 1.0))

    @staticmethod
    def _classify_vix_regime(matrix: np.ndarray, names: list[str]) -> str:  # type: ignore[type-arg]
        """Classifica regime VIX in base alla correlazione con equity."""
        if "^VIX" not in names:
            return "normal"
        vix_idx = names.index("^VIX")
        eq_idxs = [names.index(a) for a in ["SPY","IWM","QQQ"] if a in names]
        if not eq_idxs:
            return "normal"
        vix_eq_corr = float(np.mean([matrix[vix_idx, i] for i in eq_idxs]))
        if vix_eq_corr < -0.6:
            return "crisis_coupling"    # VIX molto negativa con equity = panico
        if vix_eq_corr > -0.3:
            return "divergence"         # VIX decorrelato da equity = anomalia
        return "normal"

    @staticmethod
    def _compute_signal(
        diversification: float,
        matrix: np.ndarray,  # type: ignore[type-arg]
        names: list[str],
    ) -> float:
        """Segnale [-1,+1] per Composite v2.

        Logica:
          Alta diversificazione + bassa correlazione crisi â†’ segnale positivo (ambiente sano)
          Bassa diversificazione + high corr in stress â†’ segnale negativo
        """
        # Diversification contribuisce positivamente (alta div = buono)
        d_signal = float(2 * diversification - 1)  # [0,1] â†’ [-1,+1]

        # Credit-equity correlation: alta correlazione HY/SPY in rialzo = risk-on positivo
        cr_eq = CrossAssetMatrix._avg_correlation(matrix, names, ["HYG"], ["SPY"])
        cr_signal = 0.0
        if cr_eq is not None:
            cr_signal = float(np.clip(cr_eq, -1, 1)) * 0.3

        # Composito: 70% diversification, 30% credit-equity
        raw = 0.70 * d_signal + cr_signal
        return float(np.clip(raw, -1.0, 1.0))

    # â”€â”€â”€ Persist â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _persist(self, result: CrossAssetMatrixResult) -> None:
        try:
            self._client.execute(
                f"""
                INSERT INTO {_TABLE}
                    (regime_date, avg_equity_bond_corr, avg_equity_gold_corr,
                     avg_equity_fx_corr, credit_equity_corr, vix_correlation_regime,
                     diversification_score, correlation_signal)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT (regime_date) DO UPDATE SET
                    avg_equity_bond_corr  = excluded.avg_equity_bond_corr,
                    avg_equity_gold_corr  = excluded.avg_equity_gold_corr,
                    credit_equity_corr    = excluded.credit_equity_corr,
                    vix_correlation_regime = excluded.vix_correlation_regime,
                    diversification_score = excluded.diversification_score,
                    correlation_signal    = excluded.correlation_signal,
                    computed_at           = NOW()
                """,
                [result.snapshot_date, result.avg_equity_bond_corr,
                 result.avg_equity_gold_corr, None,
                 result.credit_equity_corr, result.vix_regime,
                 result.diversification_score, result.correlation_signal],
            )
        except Exception as exc:
            log.warning("cross_asset_matrix.persist_failed: %s", str(exc)[:120])

    @staticmethod
    def _empty_result(snapshot_date: date, available: list[str]) -> CrossAssetMatrixResult:
        n = max(len(available), 1)
        return CrossAssetMatrixResult(
            snapshot_date=snapshot_date,
            correlation_matrix=np.eye(n),
            asset_names=available,
            avg_equity_bond_corr=None,
            avg_equity_gold_corr=None,
            credit_equity_corr=None,
            diversification_score=1.0,
            correlation_signal=0.0,
            vix_regime="normal",
        )
