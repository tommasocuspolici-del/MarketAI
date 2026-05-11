# engine/risk/cvar_calculator.py
"""
CVaRCalculator: Value at Risk e Expected Shortfall con distribuzioni fat-tail.

Il problema con il VaR normale:
  I rendimenti finanziari hanno code più spesse della distribuzione normale.
  Il VaR normale al 95% sottostima sistematicamente le perdite estreme
  del 20-40% su dati di mercato reali.

Soluzione: t di Student con gradi di libertà stimati via MLE.
  · df basso (3-5) → code molto grasse (simile a mercati in crisi)
  · df alto (>30)  → si avvicina alla normale (mercati calmi)

Formule:
  VaR(a) = mu + sigma * t_ppf(1-a, df)  [1-a = quantile sinistro]
  CVaR(a) = mu - sigma * t_pdf(t_ppf(1-a, df), df) / (1-a) * (df + t_ppf^2) / (df-1)

Regola 8: scipy.stats per tutti i calcoli probabilistici.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import structlog
from scipy import stats

from shared.types import TimeFrame

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient
    from shared.db.prices_repo import PricesRepository

__version__ = "1.0.0"
log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class RiskMetrics:
    ticker:          str
    computed_at:     datetime
    var_95_normal:   float    # VaR 95% distribuzione normale
    var_95_tstudent: float    # VaR 95% t-Student (fat-tail)
    cvar_95:         float    # CVaR 95% = Expected Shortfall
    var_99_tstudent: float    # VaR 99% t-Student
    cvar_99:         float    # CVaR 99%
    tail_df:         float    # Gradi di libertà stimati (fat-tail proxy)
    skewness:        float
    kurtosis:        float
    cvar_vs_var_ratio: float  # CVaR/VaR: > 1.3 indica tail risk significativo


class CVaRCalculator:
    """
    Calcola VaR e CVaR con distribuzione t di Student.
    Stima i gradi di libertà via Maximum Likelihood Estimation.
    """

    def __init__(
        self,
        prices_repo: PricesRepository,
        duckdb:      DuckDBClient,
        lookback_days: int = 252,
    ) -> None:
        self._repo     = prices_repo
        self._duckdb   = duckdb
        self._lookback = lookback_days

    def compute(self, ticker: str, exchange: str) -> RiskMetrics:
        """
        Calcola tutte le metriche di rischio per un ticker.

        Il calcolo usa i rendimenti logaritmici giornalieri (log returns)
        che sono più adatti alla modellazione statistica dei prezzi finanziari.
        """
        df = self._repo.read_ohlcv(
            ticker=ticker, exchange=exchange,
            timeframe=TimeFrame.D1, limit=self._lookback,
        )
        if df is None or len(df) < 30:
            raise ValueError(f"{ticker}: dati insufficienti per CVaR")

        closes   = df["close"].to_numpy(dtype=np.float64)
        log_rets = np.diff(np.log(closes))  # log returns

        mu    = float(np.mean(log_rets))
        sigma = float(np.std(log_rets, ddof=1))

        # ── Stima gradi di libertà t-Student via MLE ─────────────────────────
        # scipy.stats.t.fit ritorna (df, loc, scale)
        try:
            df_est, loc_est, scale_est = stats.t.fit(log_rets, floc=mu)
            df_est = float(max(2.1, df_est))   # df > 2 per varianza finita
        except Exception:
            df_est    = 5.0    # fallback conservativo
            loc_est   = mu
            scale_est = sigma

        # ── VaR Normale ───────────────────────────────────────────────────────
        var_95_normal = float(stats.norm.ppf(0.05, loc=mu, scale=sigma))

        # ── VaR t-Student ─────────────────────────────────────────────────────
        var_95_t = float(stats.t.ppf(0.05, df=df_est, loc=loc_est, scale=scale_est))
        var_99_t = float(stats.t.ppf(0.01, df=df_est, loc=loc_est, scale=scale_est))

        # ── CVaR = Expected Shortfall ─────────────────────────────────────────
        # CVaR(a) = E[X | X < VaR(a)]
        # Formula analitica per t-Student:
        # CVaR = loc - scale * t_pdf(t_ppf(a), df) / a * (df + t_ppf(a)^2) / (df - 1)
        def cvar_t(alpha: float) -> float:
            q   = stats.t.ppf(alpha, df=df_est)
            pdf = stats.t.pdf(q, df=df_est)
            return float(
                loc_est - scale_est * pdf / alpha * (df_est + q**2) / (df_est - 1)
            )

        cvar_95 = cvar_t(0.05)
        cvar_99 = cvar_t(0.01)

        # ── Statistiche descrittive ───────────────────────────────────────────
        skew = float(stats.skew(log_rets))
        kurt = float(stats.kurtosis(log_rets))   # excess kurtosis (normale=0)
        cvar_var_ratio = float(abs(cvar_95) / abs(var_95_t)) if abs(var_95_t) > 0 else 1.0

        metrics = RiskMetrics(
            ticker=ticker,
            computed_at=datetime.now(UTC),
            var_95_normal=var_95_normal,
            var_95_tstudent=var_95_t,
            cvar_95=cvar_95,
            var_99_tstudent=var_99_t,
            cvar_99=cvar_99,
            tail_df=df_est,
            skewness=skew,
            kurtosis=kurt,
            cvar_vs_var_ratio=cvar_var_ratio,
        )

        self._persist(metrics)
        log.info(
            "cvar.computed",
            ticker=ticker,
            var_95_normal=round(var_95_normal * 100, 2),
            var_95_t=round(var_95_t * 100, 2),
            cvar_95=round(cvar_95 * 100, 2),
            tail_df=round(df_est, 1),
            kurtosis=round(kurt, 2),
        )
        return metrics

    def _persist(self, m: RiskMetrics) -> None:
        self._duckdb.execute(
            """INSERT OR REPLACE INTO risk_metrics
               (ticker, computed_at, var_95_normal, var_95_tstudent, cvar_95,
                var_99_tstudent, cvar_99, tail_df, skewness, kurtosis)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [m.ticker, m.computed_at, m.var_95_normal, m.var_95_tstudent,
             m.cvar_95, m.var_99_tstudent, m.cvar_99, m.tail_df,
             m.skewness, m.kurtosis],
        )
