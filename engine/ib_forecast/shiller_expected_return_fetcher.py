"""Shiller Expected Return Fetcher per S&P 500.

Modello derivato (NON analyst consensus) basato sul dataset Yale Shiller.
Calcola il rendimento atteso decennale dell'S&P 500 come:

  expected_10y_real_return  = (1 / CAPE) * 100      (Shiller earnings yield)
  expected_10y_nominal_return = real + bond_yield   (proxy inflazione)

Il valore pubblicato e' la stima nominale 10Y in % (per matching con le
soglie di IBSignalGenerator: bull_above=5, bear_below=-5).

Fonte: serie ``shiller_cape_historical`` (gia' popolata da ``ShillerCAPEFetcher``).
Indipendente da Fed SEP / CBO / IMF: attiva il componente ``equity_signal``
del segnale IB composito.

Etichetta esplicita: ``source="shiller_model"`` e ``extraction_method="derived"``
per distinguere dal consensus di forecaster professionali.

Regola 33: nessuna previsione simulata — derivazione trasparente da dati Shiller.
Regola 34: cache-first; ricalcolato ad ogni ``fetch_latest_projections``
  perche' il calcolo e' istantaneo e segue la freshness dello Shiller dataset.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from engine.ib_forecast.schemas import ExtractedForecast
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["ShillerExpectedReturnFetcher"]

log = get_logger(__name__)


class ShillerExpectedReturnFetcher:
    """Pubblica il rendimento atteso 10Y dell'S&P 500 derivato dal CAPE Shiller.

    Args:
        client: DuckDBClient (lettura ``shiller_cape_historical`` + persistenza
            ``ib_forecasts``).
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client

    def fetch_latest_projections(self) -> list[ExtractedForecast]:
        """Calcola e persiste la stima 10Y di expected return per S&P 500.

        Ritorna sempre 1 forecast (o lista vuota se i dati Shiller mancano).
        """
        try:
            rows = self._client.query(
                "SELECT data_date, cape_ratio, bond_yield "
                "FROM shiller_cape_historical "
                "WHERE cape_ratio IS NOT NULL "
                "ORDER BY data_date DESC LIMIT 1"
            )
        except Exception as exc:
            log.warning("shiller_model.db_read_failed", error=str(exc)[:80])
            return []

        if not rows:
            log.info("shiller_model.no_cape_data")
            return []

        data_date, cape, bond_yield = rows[0]
        if cape is None or cape <= 0:
            log.warning("shiller_model.invalid_cape", cape=cape)
            return []

        # Earnings yield = 1/CAPE (Shiller framework: long-run real return).
        # Nominal return ~ real + 10Y bond yield proxy (Damodaran/Yale convention).
        earnings_yield_pct = (1.0 / float(cape)) * 100.0
        bond_yield_pct = float(bond_yield) if bond_yield is not None else 0.0
        expected_nominal_10y = round(earnings_yield_pct + bond_yield_pct * 0.5, 3)

        # report_id stabile (senza data_date) per evitare di accumulare
        # snapshot storici quando il dataset Shiller viene aggiornato.
        # La data della fonte sta in ``fetched_at``.
        report_id = "shiller_model_SP500_10Y"
        fetched_at = datetime.now(UTC)
        forecast = ExtractedForecast(
            report_id=report_id,
            source="shiller_model",
            indicator="SP500",
            horizon="10Y",
            value=expected_nominal_10y,
            unit="percent",
            extraction_method="derived",
            confidence=0.70,
            fetched_at=fetched_at,
        )

        self._persist([forecast])
        log.info("shiller_model.done",
                 cape=round(float(cape), 2),
                 expected_return_pct=expected_nominal_10y,
                 cape_date=str(data_date))
        return [forecast]

    def _persist(self, forecasts: list[ExtractedForecast]) -> None:
        """Delete-then-insert: la PK e' forecast_id (UUID auto)."""
        for f in forecasts:
            try:
                self._client.execute(
                    "DELETE FROM ib_forecasts WHERE report_id = ?",
                    [f.report_id],
                )
                self._client.execute(
                    """
                    INSERT INTO ib_forecasts
                        (report_id, source, indicator, horizon, value, unit,
                         extraction_method, confidence, fetched_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        f.report_id, f.source, f.indicator, f.horizon,
                        f.value, f.unit, f.extraction_method,
                        f.confidence, f.fetched_at,
                    ],
                )
            except Exception as exc:
                log.warning("shiller_model.persist_failed",
                            report_id=f.report_id, error=str(exc)[:120])
