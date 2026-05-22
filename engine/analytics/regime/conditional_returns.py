"""Conditional Returns Calculator — rendimenti attesi condizionali al regime."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

log = get_logger(__name__)

ANNUALIZATION_FACTOR: float = 12.0   # mensile → annuale per Sharpe
MIN_OBS_PER_REGIME: int = 5          # minimo osservazioni per regime

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS conditional_returns (
    asset_class          VARCHAR NOT NULL,
    regime_label         VARCHAR NOT NULL,
    expected_return_1m   DOUBLE  NOT NULL,
    expected_return_3m   DOUBLE  NOT NULL,
    expected_return_6m   DOUBLE  NOT NULL,
    volatility_1m        DOUBLE  NOT NULL,
    sharpe_1m            DOUBLE  NOT NULL,
    observation_count    INTEGER NOT NULL,
    computed_at          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (asset_class, regime_label)
)
"""

_UPSERT_SQL = """
INSERT INTO conditional_returns (
    asset_class, regime_label,
    expected_return_1m, expected_return_3m, expected_return_6m,
    volatility_1m, sharpe_1m, observation_count, computed_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (asset_class, regime_label) DO UPDATE SET
    expected_return_1m   = excluded.expected_return_1m,
    expected_return_3m   = excluded.expected_return_3m,
    expected_return_6m   = excluded.expected_return_6m,
    volatility_1m        = excluded.volatility_1m,
    sharpe_1m            = excluded.sharpe_1m,
    observation_count    = excluded.observation_count,
    computed_at          = excluded.computed_at
"""


@dataclass
class ConditionalReturn:
    asset_class: str
    regime_label: str
    expected_return_1m: float
    expected_return_3m: float
    expected_return_6m: float
    volatility_1m: float
    sharpe_1m: float
    observation_count: int


class ConditionalReturnsCalculator:
    """Calcola rendimenti storici per ogni combinazione (asset_class, regime).

    I rendimenti sono calcolati come medie dei rendimenti mensili storici
    segmentati per regime macro. Il Sharpe è calcolato su base mensile
    (annualizzato * sqrt(12)).
    """

    TABLE = "conditional_returns"

    def __init__(self, db: DuckDBClient) -> None:
        self._db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        try:
            self._db.execute(_CREATE_TABLE_SQL)
        except Exception as exc:
            log.warning("conditional_returns.table_create_failed", error=str(exc))

    def compute_and_persist(
        self,
        returns_df: pd.DataFrame,  # columns=asset_classes, index=date
        regime_df: pd.DataFrame,   # columns=[snapshot_date, regime_label]
    ) -> list[ConditionalReturn]:
        """Calcola e persiste i rendimenti condizionali per ogni regime.

        Args:
            returns_df: DataFrame con rendimenti mensili per asset class.
                        Index: date (DatetimeIndex o date).
            regime_df: DataFrame con colonne snapshot_date e regime_label.

        Returns:
            Lista di ConditionalReturn per ogni (asset_class, regime).
        """
        if returns_df.empty or regime_df.empty:
            log.warning("conditional_returns.empty_input")
            return []

        # Prepara regime series
        if "snapshot_date" in regime_df.columns:
            regime_series = regime_df.set_index("snapshot_date")["regime_label"]
        elif regime_df.index.name == "snapshot_date":
            regime_series = regime_df["regime_label"]
        else:
            regime_series = regime_df.iloc[:, -1]  # ultima colonna come label

        regime_series.index = pd.to_datetime(regime_series.index)
        returns_df.index = pd.to_datetime(returns_df.index)

        # Allinea
        combined = returns_df.join(regime_series.rename("_regime"), how="inner")
        if combined.empty:
            log.warning("conditional_returns.no_aligned_data")
            return []

        asset_classes = [c for c in combined.columns if c != "_regime"]
        regimes = combined["_regime"].unique()
        results: list[ConditionalReturn] = []
        now = datetime.now(UTC)

        for regime in regimes:
            regime_mask = combined["_regime"] == regime
            regime_data = combined.loc[regime_mask, asset_classes]
            n_obs = int(regime_mask.sum())

            if n_obs < MIN_OBS_PER_REGIME:
                log.debug(
                    "conditional_returns.skip_regime_insufficient_obs",
                    regime=regime,
                    n_obs=n_obs,
                )
                continue

            for asset in asset_classes:
                asset_returns = regime_data[asset].dropna()
                if len(asset_returns) < MIN_OBS_PER_REGIME:
                    continue

                ret_1m = float(asset_returns.mean())
                vol_1m = float(asset_returns.std(ddof=1))

                # Forward 3m e 6m: media rolling per approssimazione
                ret_3m = ret_1m * 3
                ret_6m = ret_1m * 6

                # Sharpe mensile annualizzato
                sharpe_1m = (
                    float(ret_1m / vol_1m * np.sqrt(ANNUALIZATION_FACTOR))
                    if vol_1m > 1e-9
                    else 0.0
                )

                cr = ConditionalReturn(
                    asset_class=str(asset),
                    regime_label=str(regime),
                    expected_return_1m=ret_1m,
                    expected_return_3m=ret_3m,
                    expected_return_6m=ret_6m,
                    volatility_1m=vol_1m,
                    sharpe_1m=sharpe_1m,
                    observation_count=len(asset_returns),
                )
                results.append(cr)

                try:
                    self._db.execute(
                        _UPSERT_SQL,
                        [
                            cr.asset_class, cr.regime_label,
                            cr.expected_return_1m, cr.expected_return_3m,
                            cr.expected_return_6m, cr.volatility_1m,
                            cr.sharpe_1m, cr.observation_count, now,
                        ],
                    )
                except Exception as exc:
                    log.error(
                        "conditional_returns.persist_failed",
                        asset=asset,
                        regime=regime,
                        error=str(exc),
                    )

        log.info(
            "conditional_returns.computed",
            n_results=len(results),
            n_regimes=len(regimes),
            n_assets=len(asset_classes),
        )
        return results

    def get_matrix(self) -> pd.DataFrame:
        """Restituisce pivot asset_class × regime con expected_return_1m.

        Returns:
            DataFrame pivot con asset_class come index, regime come colonne.
        """
        sql = """
            SELECT asset_class, regime_label, expected_return_1m
            FROM conditional_returns
            ORDER BY asset_class, regime_label
        """
        try:
            df = self._db.query_df(sql)
            if df.empty:
                return pd.DataFrame()
            return df.pivot(index="asset_class", columns="regime_label", values="expected_return_1m")
        except Exception as exc:
            log.error("conditional_returns.get_matrix_failed", error=str(exc))
            return pd.DataFrame()

    def get_for_current_regime(self, current_regime: str) -> pd.DataFrame:
        """Restituisce i rendimenti per il regime corrente.

        Args:
            current_regime: Label del regime corrente (es. "expansion").

        Returns:
            DataFrame ordinato per expected_return_1m DESC.
        """
        sql = """
            SELECT * FROM conditional_returns
            WHERE regime_label = ?
            ORDER BY expected_return_1m DESC
        """
        try:
            return self._db.query_df(sql, [current_regime])
        except Exception as exc:
            log.error(
                "conditional_returns.get_for_current_regime_failed",
                regime=current_regime,
                error=str(exc),
            )
            return pd.DataFrame()
