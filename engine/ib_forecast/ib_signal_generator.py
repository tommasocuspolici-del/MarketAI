"""IB Signal Generator — segnale [-1,+1] da consensus IB per Composite Signal v3.

Regola 33: solo previsioni reali da ib_consensus.
Regola 34: segnale persistito in ib_signal (TTL: ib_consensus = 86400s).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from engine.ib_forecast.schemas import IBConsensus, IBSignal
from shared.logger import get_logger

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
__all__ = ["IBSignalGenerator"]

log = get_logger(__name__)

# Soglie per conversione valore → segnale [-1, +1]
_SIGNAL_RULES: dict[str, dict[str, Any]] = {
    "GDP":          {"bull_above": 2.5, "bear_below": 0.5,  "inverted": False},
    "CPI":          {"bull_above": 0.0, "bear_below": 4.0,  "inverted": True},  # inflazione alta = bear
    "FEDFUNDS":     {"bull_above": 0.0, "bear_below": 5.0,  "inverted": True},  # tassi alti = bear
    "SP500":        {"bull_above": 5.0, "bear_below": -5.0, "inverted": False},
    "UNEMPLOYMENT": {"bull_above": 0.0, "bear_below": 5.0,  "inverted": True},  # disoccupazione alta = bear
}


def _value_to_signal(value: float, rules: dict[str, Any]) -> float:
    """Converte un valore in segnale [-1, +1] secondo le soglie."""
    bull_above: float = rules["bull_above"]
    bear_below: float = rules["bear_below"]
    inverted: bool = rules["inverted"]

    if inverted:
        # Valori alti = bear
        if value >= bear_below:
            return -1.0
        if value <= bull_above:
            return 1.0
        span = bear_below - bull_above
        return round(1.0 - 2.0 * (value - bull_above) / span, 3) if span > 0 else 0.0
    else:
        # Valori alti = bull
        if value >= bull_above:
            return 1.0
        if value <= bear_below:
            return -1.0
        span = bull_above - bear_below
        return round(-1.0 + 2.0 * (value - bear_below) / span, 3) if span > 0 else 0.0


class IBSignalGenerator:
    """Genera segnale IB da consensus aggregato.

    Args:
        client: DuckDBClient per persistenza (Regola 34).
    """

    def __init__(self, client: DuckDBClient) -> None:
        self._client = client

    def generate(self, consensus_list: list[IBConsensus]) -> IBSignal | None:
        """Calcola segnale [-1,+1] da lista di consensus.

        Args:
            consensus_list: Lista IBConsensus da ConsensusBuilder.

        Returns:
            IBSignal con score composito, o None se dati insufficienti.
        """
        if not consensus_list:
            log.warning("ib_signal.no_consensus")
            return None

        component_signals: dict[str, float] = {}
        weights: dict[str, float] = {
            "GDP":          0.30,
            "CPI":          0.25,
            "FEDFUNDS":     0.20,
            "SP500":        0.15,
            "UNEMPLOYMENT": 0.10,
        }

        for cons in consensus_list:
            indicator = cons.indicator.upper()
            if indicator not in _SIGNAL_RULES or cons.consensus_value is None:
                continue
            sig = _value_to_signal(cons.consensus_value, _SIGNAL_RULES[indicator])
            # Usa il peggior scenario (consensus_low) per un segnale conservativo
            if cons.consensus_low is not None:
                sig_low = _value_to_signal(cons.consensus_low, _SIGNAL_RULES[indicator])
                sig = (sig + sig_low) / 2.0
            component_signals[indicator] = sig

        if not component_signals:
            log.warning("ib_signal.no_valid_components")
            return None

        # Score pesato
        total_weight = sum(weights.get(k, 0.5) for k in component_signals)
        if total_weight == 0:
            return None

        composite = sum(
            component_signals[k] * weights.get(k, 0.5)
            for k in component_signals
        ) / total_weight

        signal = IBSignal(
            signal_date=datetime.now(UTC),
            score=round(max(-1.0, min(1.0, composite)), 4),
            gdp_signal=component_signals.get("GDP"),
            inflation_signal=component_signals.get("CPI"),
            rates_signal=component_signals.get("FEDFUNDS"),
            equity_signal=component_signals.get("SP500"),
            source_count=sum(1 for c in consensus_list if c.consensus_value is not None),
            data_quality="ok" if len(component_signals) >= 3 else "partial",
        )

        self._persist(signal)
        log.info("ib_signal.generated", score=signal.score, components=len(component_signals))
        return signal

    def read_latest(self) -> IBSignal | None:
        """Legge l'ultimo segnale IB da DB (Regola 34: cache-first)."""
        try:
            rows = self._client.query(
                "SELECT signal_date, score, gdp_signal, inflation_signal, "
                "rates_signal, equity_signal, source_count, data_quality "
                "FROM ib_signal ORDER BY signal_date DESC LIMIT 1"
            )
            if not rows:
                return None
            r = rows[0]
            return IBSignal(
                signal_date=r[0],
                score=float(r[1]),
                gdp_signal=float(r[2]) if r[2] is not None else None,
                inflation_signal=float(r[3]) if r[3] is not None else None,
                rates_signal=float(r[4]) if r[4] is not None else None,
                equity_signal=float(r[5]) if r[5] is not None else None,
                source_count=int(r[6]) if r[6] else 0,
                data_quality=str(r[7]) if r[7] else "ok",
            )
        except Exception as exc:
            log.warning("ib_signal.read_failed", error=str(exc)[:100])
            return None

    def _persist(self, signal: IBSignal) -> None:
        """Salva segnale in ib_signal (Regola 34)."""
        try:
            self._client.execute(
                """
                INSERT INTO ib_signal
                    (signal_date, score, gdp_signal, inflation_signal,
                     rates_signal, equity_signal, source_count, data_quality)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (signal_date)
                DO UPDATE SET
                    score=excluded.score,
                    gdp_signal=excluded.gdp_signal,
                    inflation_signal=excluded.inflation_signal,
                    rates_signal=excluded.rates_signal,
                    equity_signal=excluded.equity_signal,
                    source_count=excluded.source_count,
                    data_quality=excluded.data_quality
                """,
                [
                    signal.signal_date, signal.score,
                    signal.gdp_signal, signal.inflation_signal,
                    signal.rates_signal, signal.equity_signal,
                    signal.source_count, signal.data_quality,
                ],
            )
        except Exception as exc:
            log.warning("ib_signal.persist_failed", error=str(exc)[:100])
