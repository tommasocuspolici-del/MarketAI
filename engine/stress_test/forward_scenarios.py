"""Forward Scenario Generator — scenari sintetici forward-looking (Regola 24).

Regola 24: i stress test DEVONO includere scenari sintetici forward-looking
derivati dall'analisi di mercato corrente. Solo scenari storici = violazione.

Scenari implementati (5):
  · RECESSION:        -0.20% drift/giorno, +60% volatilità, drawdown prolungato
  · INFLATION_SHOCK:  -0.08% drift, +40% vol, correlazione negativa con bond
  · CREDIT_CRISIS:    -0.30% drift, +80% vol, spike di volatilità iniziale
  · GOLDILOCKS:       +0.12% drift, -20% vol (scenario favorevole)
  · BASE:             drift e vol storici invariati (scenario neutro di riferimento)

Metodologia (completamente vettorizzata, Regola 8):
  1. Calcola rendimenti log-storici dall'OHLCV input
  2. Stima drift e volatilità storici con numpy
  3. Genera rendimenti sintetici con numpy.random (seed fisso per riproducibilità)
  4. Ricostruisce il OHLCV stressed mantenendo la struttura originale (ts, index)

ANTI-REGRESSIONE:
  · Seed numpy = 42 per tutti gli scenari (risultati deterministici nei test).
  · I prezzi sintetici partono SEMPRE dal close[0] storico (non modificano
    il punto di partenza — evita bias di confronto tra scenari).
  · Lo schema output del DataFrame stressed è identico all'input (stesse colonne).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from shared.logger import get_logger

if TYPE_CHECKING:
    from engine.backtesting.engine import BacktestResult
    from engine.backtesting.strategy import Strategy

__version__ = "9.0.0"
__all__ = [
    "ScenarioType",
    "ScenarioConfig",
    "ForwardScenarioGenerator",
    "StressTestRunner",
]

log = get_logger(__name__)

# Seed numpy per riproducibilità (Regola 7: nessun magic number)
_SCENARIO_SEED: int = 42

# Parametri scenari (tutti documentati)
_SCENARIO_PARAMS: dict[str, dict[str, float]] = {
    "recession": {
        "drift_adj":  -0.0020,   # -0.20%/giorno aggiuntivo rispetto a storico
        "vol_mult":    1.60,     # +60% volatilità
        "spike_days":  0,        # nessuno spike iniziale
        "spike_mult":  1.0,
    },
    "inflation_shock": {
        "drift_adj":  -0.0008,
        "vol_mult":    1.40,
        "spike_days":  5,        # 5 giorni di spike all'inizio
        "spike_mult":  2.0,
    },
    "credit_crisis": {
        "drift_adj":  -0.0030,
        "vol_mult":    1.80,
        "spike_days":  10,
        "spike_mult":  3.0,
    },
    "goldilocks": {
        "drift_adj":  +0.0012,
        "vol_mult":    0.80,
        "spike_days":  0,
        "spike_mult":  1.0,
    },
    "base": {
        "drift_adj":   0.0,
        "vol_mult":    1.0,
        "spike_days":  0,
        "spike_mult":  1.0,
    },
}


class ScenarioType(StrEnum):
    """Tipi di scenario per forward stress test."""
    RECESSION        = "recession"
    INFLATION_SHOCK  = "inflation_shock"
    CREDIT_CRISIS    = "credit_crisis"
    GOLDILOCKS       = "goldilocks"
    BASE             = "base"


@dataclass(frozen=True)
class ScenarioConfig:
    """Parametri di configurazione per uno scenario stress test."""
    scenario_type: ScenarioType
    drift_adj:     float    # aggiustamento drift rispetto a storico (per barra)
    vol_mult:      float    # moltiplicatore volatilità storica
    spike_days:    int      # prime N barre con volatilità spike
    spike_mult:    float    # moltiplicatore spike iniziale


class ForwardScenarioGenerator:
    """Genera OHLCV sintetici stressed per scenari forward-looking.

    Completamente vettorizzato con numpy (Regola 8, Regola 24):
      1. Estrae drift e vol storici dall'OHLCV
      2. Applica aggiustamenti di scenario con numpy random
      3. Ricostruisce prezzi da log-returns cumulativi
      4. Mantiene struttura e timestamp dell'OHLCV originale
    """

    def generate(
        self,
        ohlcv: pd.DataFrame,
        scenario: ScenarioType,
    ) -> pd.DataFrame:
        """Genera un OHLCV stressed per uno scenario specifico.

        Args:
            ohlcv:    OHLCV storico (base di partenza). Colonne: ts, open,
                      high, low, close, volume.
            scenario: Tipo di scenario da applicare.

        Returns:
            DataFrame OHLCV con prezzi stressed e stesso indice/ts dell'input.
            Il prezzo iniziale (close[0]) è invariato — solo il percorso cambia.
        """
        if len(ohlcv) < 5:
            raise ValueError(f"OHLCV troppo corto per stress test: {len(ohlcv)} barre")

        close_col = "close" if "close" in ohlcv.columns else "Close"
        close = ohlcv[close_col].to_numpy(dtype=np.float64)
        n     = len(close)

        # Calcola drift e vol storici (vettorizzato)
        log_returns  = np.diff(np.log(np.maximum(close, 1e-9)))
        hist_drift   = float(np.mean(log_returns))
        hist_vol     = float(np.std(log_returns)) or 1e-9

        # Parametri scenario
        params = _SCENARIO_PARAMS.get(str(scenario), _SCENARIO_PARAMS["base"])
        cfg = ScenarioConfig(
            scenario_type=scenario,
            drift_adj=float(params["drift_adj"]),
            vol_mult=float(params["vol_mult"]),
            spike_days=int(params["spike_days"]),
            spike_mult=float(params["spike_mult"]),
        )

        # Genera rendimenti sintetici (deterministici con seed fisso)
        rng = np.random.default_rng(_SCENARIO_SEED)
        stressed_drift = hist_drift + cfg.drift_adj
        stressed_vol   = hist_vol * cfg.vol_mult

        synth_returns  = rng.normal(stressed_drift, stressed_vol, n - 1)

        # Applica spike iniziale se richiesto dallo scenario
        if cfg.spike_days > 0:
            spike_n = min(cfg.spike_days, n - 1)
            spike_vol = stressed_vol * cfg.spike_mult
            synth_returns[:spike_n] = rng.normal(
                stressed_drift * cfg.spike_mult,
                spike_vol,
                spike_n,
            )

        # Ricostruisce prezzi da close[0] (punto di partenza invariato)
        stressed_log_prices = np.log(close[0]) + np.concatenate([[0.0], np.cumsum(synth_returns)])
        stressed_close = np.exp(stressed_log_prices)

        # Mantiene OHLC spread proporzionale al close originale (vettorizzato)
        ratio = stressed_close / np.maximum(close, 1e-9)
        stressed_df = ohlcv.copy()
        stressed_df[close_col] = stressed_close

        for col in ("open", "high", "low"):
            if col in stressed_df.columns:
                stressed_df[col] = ohlcv[col].to_numpy(dtype=np.float64) * ratio

        log.debug(
            "forward_scenario.generated",
            scenario=str(scenario),
            n_bars=n,
            hist_drift=round(hist_drift, 5),
            stressed_drift=round(stressed_drift, 5),
            vol_mult=cfg.vol_mult,
        )
        return stressed_df

    def generate_all(
        self,
        ohlcv: pd.DataFrame,
    ) -> dict[str, pd.DataFrame]:
        """Genera OHLCV stressed per tutti i scenari disponibili.

        Returns:
            {scenario_name: stressed_ohlcv_df}
        """
        results: dict[str, pd.DataFrame] = {}
        for scenario in ScenarioType:
            try:
                results[str(scenario)] = self.generate(ohlcv, scenario)
            except Exception as exc:
                log.warning(
                    "forward_scenario.skip",
                    scenario=str(scenario),
                    error=str(exc)[:80],
                )
        return results


class StressTestRunner:
    """Esegue una strategia su tutti gli scenari forward-looking.

    Regola 24: includi SEMPRE scenari sintetici, non solo storici.

    Output: dict {scenario_name: BacktestResult} con tutti i risultati
    comparabili (stesso inizial cash, fees, slippage).
    """

    def __init__(
        self,
        initial_cash: float = 10_000.0,
        fees: float = 0.001,
        slippage: float = 0.001,
    ) -> None:
        from engine.backtesting.engine import MIN_FEES, MIN_SLIPPAGE, BacktestError
        if fees < MIN_FEES:
            raise BacktestError(f"fees {fees} < minimum {MIN_FEES} (Rule 23)")
        if slippage < MIN_SLIPPAGE:
            raise BacktestError(f"slippage {slippage} < minimum {MIN_SLIPPAGE} (Rule 23)")
        self._initial_cash = initial_cash
        self._fees         = fees
        self._slippage     = slippage
        self._generator    = ForwardScenarioGenerator()

    def run_all_scenarios(
        self,
        strategy: Strategy,
        ohlcv: pd.DataFrame,
        ticker: str = "UNKNOWN",
    ) -> dict[str, BacktestResult]:
        """Esegue la strategia su tutti gli scenari e ritorna i risultati.

        Args:
            strategy: Strategia da testare su ogni scenario.
            ohlcv:    OHLCV storico (base per generare gli stressed).
            ticker:   Identificatore del ticker.

        Returns:
            {scenario_name: BacktestResult}. Il run 'base' è il benchmark.
        """
        from engine.backtesting.engine import BacktestEngine

        engine = BacktestEngine(
            initial_cash=self._initial_cash,
            fees=self._fees,
            slippage=self._slippage,
        )
        stressed_map = self._generator.generate_all(ohlcv)
        results: dict[str, BacktestResult] = {}

        for scenario_name, stressed_ohlcv in stressed_map.items():
            try:
                result = engine.run(
                    stressed_ohlcv,
                    strategy,
                    ticker=f"{ticker}_{scenario_name}",
                )
                results[scenario_name] = result
                log.info(
                    "stress_runner.scenario_done",
                    scenario=scenario_name,
                    sharpe=round(result.performance.sharpe_ratio, 3),
                    max_dd=round(result.performance.max_drawdown, 3),
                )
            except Exception as exc:
                log.warning(
                    "stress_runner.scenario_skip",
                    scenario=scenario_name,
                    error=str(exc)[:80],
                )
                continue

        return results

    def compare_scenarios(
        self,
        results: dict[str, BacktestResult],
    ) -> pd.DataFrame:
        """Costruisce un DataFrame comparativo tra scenari.

        Ordina per Sharpe ratio descrescente. Il 'base' è sempre incluso
        come riferimento per il confronto.

        Returns:
            DataFrame con colonne: scenario, sharpe, max_dd, total_return,
            n_trades, fees_total.
        """
        rows: list[dict[str, object]] = []
        for scenario, result in results.items():
            p = result.performance
            rows.append({
                "scenario":    scenario,
                "sharpe":      round(float(p.sharpe_ratio), 3),
                "max_dd":      round(float(p.max_drawdown), 3),
                "total_return": round(float(p.total_return), 3),
                "n_trades":    result.n_trades,
                "fees_total":  round(result.fees_total, 2),
                "is_stressed": scenario != "base",
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        return df.sort_values("sharpe", ascending=False).reset_index(drop=True)
