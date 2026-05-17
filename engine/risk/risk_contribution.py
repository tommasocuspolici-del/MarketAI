# engine/risk/risk_contribution.py
"""
RiskContributionAnalyzer: decompone il rischio del portafoglio per asset.

Concetto fondamentale:
  La volatilità del portafoglio NON è la somma delle volatilità individuali.
  Dipende dalle correlazioni. Un asset volatile ma poco correlato agli altri
  contribuisce meno al rischio totale di un asset meno volatile ma altamente
  correlato.

Formula:
  Dato portafoglio p con pesi w e matrice di covarianza Σ:
    sigma_p = sqrt(w^T Sigma w)

  Contributo marginale dell'asset i:
    MRC_i = (Sigma*w)_i / sigma_p   [vettore delle derivate parziali]

  Contributo al rischio (RC) in termini assoluti:
    RC_i = w_i * MRC_i

  Contributo al rischio percentuale:
    PRC_i = RC_i / sigma_p   (somma a 1 per costruzione)

  Herfindahl-Hirschman Index (concentrazione):
    HHI = Σ PRC_i²          (0 = perfettamente diversificato, 1 = tutto su 1 asset)

Input:
  · Pesi correnti dal portafoglio eToro (personal layer via bridge)
  · Matrice di covarianza dal modulo DCC-GARCH (già in DuckDB)

Output:
  · Risk contribution % per ogni asset → UI: bar chart orizzontale
  · HHI di concentrazione
  · Raccomandazione: quale asset ridurre per migliorare la diversificazione
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
import structlog

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
log = structlog.get_logger(__name__)


@dataclass
class PortfolioRiskReport:
    computed_at:         datetime
    profile_id:          str
    weights:             dict[str, float]     # {ticker: weight}
    risk_contributions:  dict[str, float]     # {ticker: % contribution}
    portfolio_vol_annual: float
    portfolio_cvar_95:   float
    hhi:                 float                # [0, 1]
    largest_contributor: str
    largest_contrib_pct: float
    recommendation:      str


class RiskContributionAnalyzer:
    """
    Decompone il rischio di portafoglio per asset usando la matrice di covarianza.
    """

    def __init__(self, duckdb: DuckDBClient) -> None:
        self._duckdb = duckdb

    def analyze(
        self,
        weights:    dict[str, float],
        profile_id: str,
    ) -> PortfolioRiskReport:
        """
        Calcola il risk contribution di ogni asset nel portafoglio.

        Args:
            weights:    {ticker: peso in [0,1], somma = 1}
            profile_id: ID profilo per persistenza

        Returns:
            PortfolioRiskReport con tutti i campi calcolati.
        """
        tickers = list(weights.keys())
        w       = np.array([weights[t] for t in tickers], dtype=np.float64)

        # Normalizza i pesi (per sicurezza)
        w = w / np.sum(w)

        # Carica matrice covarianza dal DB (output DCC-GARCH)
        cov_matrix = self._load_covariance(tickers)

        # Volatilità portafoglio
        port_var = float(w @ cov_matrix @ w)
        port_vol = float(np.sqrt(port_var))

        # Risk Contribution
        mrc = (cov_matrix @ w) / port_vol if port_vol > 0 else np.zeros(len(w))
        rc  = w * mrc              # contributo assoluto (scala della vol)
        prc = rc / port_vol if port_vol > 0 else rc  # contributo percentuale

        risk_contributions = {
            tickers[i]: float(np.clip(prc[i], 0, 1))
            for i in range(len(tickers))
        }

        # HHI di concentrazione del rischio
        hhi = float(np.sum(prc ** 2))

        # Largest contributor
        max_ticker = max(risk_contributions, key=lambda k: risk_contributions[k])
        max_pct    = risk_contributions[max_ticker]

        # CVaR portafoglio (aggregato dai CVaR individuali con correlazione)
        port_cvar = self._estimate_portfolio_cvar(tickers, w, cov_matrix)

        # Raccomandazione
        recommendation = self._build_recommendation(
            risk_contributions, weights, hhi
        )

        report = PortfolioRiskReport(
            computed_at=datetime.now(UTC),
            profile_id=profile_id,
            weights=weights,
            risk_contributions=risk_contributions,
            portfolio_vol_annual=port_vol * np.sqrt(252.0),
            portfolio_cvar_95=port_cvar,
            hhi=hhi,
            largest_contributor=max_ticker,
            largest_contrib_pct=max_pct,
            recommendation=recommendation,
        )

        self._persist(report)
        log.info(
            "risk_contribution.done",
            profile=profile_id,
            vol_annual=round(report.portfolio_vol_annual * 100, 2),
            hhi=round(hhi, 3),
            largest=max_ticker,
        )
        return report

    def _load_covariance(self, tickers: list[str]) -> npt.NDArray[np.float64]:
        """
        Carica la matrice di covarianza stimata dal modulo DCC-GARCH.
        Se non disponibile, usa correlazione storica dai prezzi.
        """
        n = len(tickers)
        try:
            rows = self._duckdb.query(
                "SELECT covariance_matrix_json FROM correlation_reports "
                "ORDER BY computed_at DESC LIMIT 1"
            )
            row = rows[0] if rows else None
            if row and row[0]:
                full_cov = json.loads(row[0])
                # Estrai sotto-matrice per i ticker del portafoglio
                cov = np.zeros((n, n), dtype=np.float64)
                for i, ti in enumerate(tickers):
                    for j, tj in enumerate(tickers):
                        cov[i, j] = full_cov.get(ti, {}).get(tj, 0.01 if i == j else 0.0)
                return cov
        except Exception as exc:
            log.warning("risk_contribution.cov_from_db_failed", error=str(exc)[:100])

        # Fallback: matrice identità (assume no correlazione)
        log.warning("risk_contribution.using_identity_cov", tickers=tickers)
        return np.eye(n, dtype=np.float64) * np.float64(0.04)  # vol 20% per default

    def _estimate_portfolio_cvar(
        self,
        tickers:    list[str],
        weights:    npt.NDArray[np.float64],
        cov_matrix: npt.NDArray[np.float64],
    ) -> float:
        """
        Stima il CVaR del portafoglio aggregato.
        Usa l'approssimazione normal + fat-tail adjustment.
        """
        from scipy import stats
        port_vol_daily = float(np.sqrt(weights @ cov_matrix @ weights))
        # CVaR normale al 95% per il portafoglio (come proxy)
        cvar_approx = float(
            stats.norm.pdf(stats.norm.ppf(0.05)) / 0.05 * port_vol_daily
        )
        # Fat-tail multiplier empirico (df=5 → ~1.35x rispetto alla normale)
        return -cvar_approx * 1.35

    @staticmethod
    def _build_recommendation(
        risk_contributions: dict[str, float],
        weights:            dict[str, float],
        hhi:                float,
    ) -> str:
        max_ticker = max(risk_contributions, key=lambda k: risk_contributions[k])
        max_pct    = risk_contributions[max_ticker]
        n_assets   = len(weights)

        if hhi > 0.40:
            return (
                f"⚠️ Concentrazione rischio critica (HHI={hhi:.2f}). "
                f"{max_ticker} assorbe {max_pct:.0%} del rischio totale. "
                f"Considera di ridurre la posizione o aggiungere asset poco correlati."
            )
        if max_pct > 0.35:
            return (
                f"⚠️ {max_ticker} domina il rischio ({max_pct:.0%}). "
                f"Il portafoglio è correttamente diversificato per numero "
                f"({n_assets} asset) ma non per rischio."
            )
        return (
            f"✅ Diversificazione del rischio accettabile (HHI={hhi:.2f}). "
            f"Il maggiore contributore è {max_ticker} ({max_pct:.0%})."
        )

    def _persist(self, r: PortfolioRiskReport) -> None:
        self._duckdb.execute(
            """INSERT INTO portfolio_risk_report
               (computed_at, profile_id, portfolio_vol_annual, portfolio_cvar_95,
                component_json, hhi_concentration, largest_contributor, largest_contrib_pct)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [r.computed_at, r.profile_id, r.portfolio_vol_annual,
             r.portfolio_cvar_95, json.dumps(r.risk_contributions),
             r.hhi, r.largest_contributor, r.largest_contrib_pct],
        )
