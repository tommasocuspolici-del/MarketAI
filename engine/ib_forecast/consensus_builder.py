"""Consensus Builder — aggregazione previsioni da tutte le fonti IB.

Regola 33: solo previsioni reali da DB.
Regola 34: consensus cachato in ib_consensus (TTL: ib_consensus = 86400s).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from statistics import median
from typing import TYPE_CHECKING

from engine.ib_forecast.schemas import IBConsensus, IBSignal
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["ConsensusBuilder"]

log = get_logger(__name__)

# Soglie per generare segnale [-1, +1] da indicatori macro
_GDP_THRESHOLDS = {"bull": 2.5, "bear": 0.5}
_CPI_THRESHOLDS = {"bull": 2.5, "bear": 4.0}  # CPI bassa=bull, alta=bear
_RATES_THRESHOLDS = {"bull": 0.0, "bear": 5.0}  # Tassi bassi=bull


class ConsensusBuilder:
    """Aggrega previsioni da ib_forecasts e genera segnale IB.

    Args:
        client: DuckDBClient per lettura/scrittura (Regola 34).
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client

    def build(self, lookback_days: int = 30) -> list[IBConsensus]:
        """Calcola consensus mediano per ogni indicatore/horizon.

        Args:
            lookback_days: Considera previsioni degli ultimi N giorni.

        Returns:
            Lista di IBConsensus per tutti gli indicatori disponibili.
        """
        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        try:
            rows = self._client.query(
                "SELECT indicator, horizon, value, source, confidence "
                "FROM ib_forecasts "
                "WHERE fetched_at >= ? AND value IS NOT NULL "
                "ORDER BY indicator, horizon, fetched_at DESC",
                [cutoff],
            )
        except Exception as exc:
            log.warning("consensus_builder.db_read_failed", error=str(exc)[:100])
            return []

        if not rows:
            log.info("consensus_builder.no_data")
            return []

        # Raggruppa per (indicator, horizon)
        groups: dict[tuple[str, str], list[tuple[float, str]]] = {}
        for ind, hor, val, src, conf in rows:
            key = (str(ind), str(hor))
            groups.setdefault(key, []).append((float(val), str(src)))

        consensus_list: list[IBConsensus] = []
        for (indicator, horizon), values_sources in groups.items():
            values = [v for v, _ in values_sources]
            sources = list({s for _, s in values_sources})

            consensus_val = median(values)
            consensus_low = min(values) if len(values) > 1 else None
            consensus_high = max(values) if len(values) > 1 else None

            c = IBConsensus(
                indicator=indicator,
                horizon=horizon,
                consensus_value=consensus_val,
                consensus_low=consensus_low,
                consensus_high=consensus_high,
                source_count=len(sources),
                sources=sources,
                method="median",
                data_quality="ok" if len(values) >= 2 else "single_source",
                computed_at=datetime.now(UTC),
            )
            consensus_list.append(c)
            self._persist_consensus(c)

        log.info("consensus_builder.built", count=len(consensus_list))
        return consensus_list

    def build_signal(self, consensus_list: list[IBConsensus] | None = None) -> IBSignal:
        """Genera segnale [-1, +1] dal consensus IB per Composite Signal v3."""
        if consensus_list is None:
            consensus_list = self.build()

        gdp_signal = self._indicator_signal("GDP", consensus_list, _GDP_THRESHOLDS, invert=False)
        cpi_signal = self._indicator_signal("CPI", consensus_list, _CPI_THRESHOLDS, invert=True)
        rates_signal = self._indicator_signal("FEDFUNDS", consensus_list, _RATES_THRESHOLDS, invert=True)

        # SP500 signal: diretto (consensus price vs attuale)
        sp_signal = self._sp500_signal(consensus_list)

        signals = [s for s in [gdp_signal, cpi_signal, rates_signal, sp_signal] if s is not None]
        composite = sum(signals) / len(signals) if signals else 0.0
        composite = max(-1.0, min(1.0, composite))

        signal = IBSignal(
            signal_date=datetime.now(UTC),
            score=composite,
            gdp_signal=gdp_signal,
            inflation_signal=cpi_signal,
            rates_signal=rates_signal,
            equity_signal=sp_signal,
            source_count=len({s for c in consensus_list for s in c.sources}),
            data_quality="ok" if consensus_list else "no_data",
        )

        self._persist_signal(signal)
        log.info("consensus_builder.signal", score=round(composite, 4))
        return signal

    def _indicator_signal(
        self,
        indicator: str,
        consensus_list: list[IBConsensus],
        thresholds: dict[str, float],
        invert: bool = False,
    ) -> float | None:
        """Converte consensus di un indicatore in score [-1, +1]."""
        relevant = [c for c in consensus_list if c.indicator == indicator and c.consensus_value is not None]
        if not relevant:
            return None
        latest = sorted(relevant, key=lambda c: c.computed_at or datetime.min)[-1]
        val = latest.consensus_value
        if val is None:
            return None

        bull_threshold = thresholds["bull"]
        bear_threshold = thresholds["bear"]

        if not invert:
            if val >= bull_threshold:
                score = min(1.0, (val - bull_threshold) / bull_threshold)
            elif val <= bear_threshold:
                score = max(-1.0, -(bear_threshold - val) / bear_threshold)
            else:
                score = (val - bear_threshold) / (bull_threshold - bear_threshold) * 2 - 1
        else:
            # Per CPI e tassi: alto = bearish
            if val <= bull_threshold:
                score = min(1.0, (bull_threshold - val) / bull_threshold)
            elif val >= bear_threshold:
                score = max(-1.0, -(val - bear_threshold) / bear_threshold)
            else:
                score = 1.0 - (val - bull_threshold) / (bear_threshold - bull_threshold) * 2

        return max(-1.0, min(1.0, score))

    def _sp500_signal(self, consensus_list: list[IBConsensus]) -> float | None:
        """Segnale SP500 basato su target consensus vs prezzo attuale."""
        relevant = [c for c in consensus_list if c.indicator == "SP500" and c.consensus_value is not None]
        if not relevant:
            return None
        try:
            rows = self._client.query(
                "SELECT close FROM ohlcv_data WHERE ticker='SPY' ORDER BY ts DESC LIMIT 1"
            )
            if not rows:
                return None
            current = float(rows[0][0]) * 10  # SPY → S&P 500 approssimato
            target = relevant[-1].consensus_value
            if target and current > 0:
                upside = (target - current) / current
                return max(-1.0, min(1.0, upside * 5))  # Scale
        except Exception:
            pass
        return None

    def _persist_consensus(self, c: IBConsensus) -> None:
        try:
            self._client.execute(
                """
                INSERT INTO ib_consensus
                    (indicator, horizon, consensus_value, consensus_low, consensus_high,
                     source_count, method, data_quality, computed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (indicator, horizon) DO UPDATE SET
                    consensus_value=excluded.consensus_value,
                    consensus_low=excluded.consensus_low,
                    consensus_high=excluded.consensus_high,
                    source_count=excluded.source_count,
                    computed_at=excluded.computed_at
                """,
                [c.indicator, c.horizon, c.consensus_value, c.consensus_low,
                 c.consensus_high, c.source_count, c.method, c.data_quality, c.computed_at],
            )
        except Exception as exc:
            log.debug("consensus_builder.persist_skip", error=str(exc)[:80])

    def _persist_signal(self, signal: IBSignal) -> None:
        try:
            self._client.execute(
                """
                INSERT INTO ib_signal
                    (signal_date, score, gdp_signal, inflation_signal, rates_signal,
                     equity_signal, source_count, data_quality)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (signal_date) DO UPDATE SET
                    score=excluded.score, gdp_signal=excluded.gdp_signal,
                    inflation_signal=excluded.inflation_signal
                """,
                [signal.signal_date, signal.score, signal.gdp_signal,
                 signal.inflation_signal, signal.rates_signal, signal.equity_signal,
                 signal.source_count, signal.data_quality],
            )
        except Exception as exc:
            log.debug("consensus_builder.signal_persist_skip", error=str(exc)[:80])
