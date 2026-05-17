# engine/portfolio/rebalancing_engine.py
"""
RebalancingEngine: calcola il piano ottimale di ribilanciamento portafoglio.

Metodi supportati:
  · Markowitz (Mean-Variance): massimizza rendimento atteso per dato rischio
  · HRP (Hierarchical Risk Parity): clustering gerarchico, robusto out-of-sample
  · Risk Parity: equal risk contribution per ogni asset
  · Equal Weight: sempllice 1/N, come benchmark

Processo completo:
  1. Carica portafoglio corrente (pesi attuali da SQLite personal layer)
  2. Carica matrice di covarianza (DCC-GARCH da DuckDB)
  3. Calcola pesi target con il metodo configurato
  4. Calcola il drift: pesi_attuali vs pesi_target
  5. Genera lista di trade (ticker, azione, importo EUR)
  6. Applica filtri: min_trade, threshold, tax-awareness
  7. Persiste il report su DuckDB

CONNESSIONE CON PERSONAL LAYER (Regola 21 + 22):
  · Pesi attuali: letti da SQLite via bridge/personal_client.py
  · Profilo rischio: letto da InvestorProfile → determina il target_vol
  · Tax impact: letto da TaxCalculator (personal/tax/calculator.py)
  · Output: mostrato in P10_Rebalancing.py

IMPORTANTE — Disclaimer (Regola 22):
  Il RebalancingEngine produce SUGGERIMENTI, non ordini automatici.
  L'utente deve sempre confermare ogni trade prima dell'esecuzione.
  Non è connesso a nessun broker.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import numpy as np
import numpy.typing as npt
import pandas as pd
import structlog
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform

if TYPE_CHECKING:
    from shared.db.duckdb_client import DuckDBClient

__version__ = "1.0.0"
log = structlog.get_logger(__name__)

RebalancingMethod = Literal["markowitz", "hrp", "risk_parity", "equal_weight"]


@dataclass
class TradeInstruction:
    """Un singolo ordine di ribilanciamento suggerito."""
    ticker:        str
    action:        Literal["BUY", "SELL", "HOLD"]
    current_weight: float
    target_weight:  float
    drift_pct:     float           # target - current in punti percentuali
    estimated_eur: float           # valore in EUR del trade
    tax_note:      str = ""        # es. "Plusvalenza stimata: €450"
    priority:      int = 1         # 1=alta, 2=media, 3=bassa


@dataclass
class RebalancingReport:
    """Report completo del piano di ribilanciamento."""
    report_id:            str
    computed_at:          datetime
    profile_id:           str
    method:               str
    current_weights:      dict[str, float]
    target_weights:       dict[str, float]
    trades:               list[TradeInstruction]
    portfolio_value_eur:  float
    current_vol_annual:   float
    expected_vol_annual:  float
    current_hhi:          float
    expected_hhi:         float
    total_turnover_pct:   float
    estimated_tax_eur:    float
    n_trades:             int
    summary:              str


class RebalancingEngine:
    """
    Calcola il piano ottimale di ribilanciamento per il portafoglio dell'utente.

    Uso:
        engine = RebalancingEngine(duckdb=client, profile_risk="moderate")
        report = engine.run(
            current_weights={"AAPL": 0.30, "MSFT": 0.25, "SPY": 0.45},
            portfolio_value_eur=50_000.0,
            profile_id="me",
        )
    """

    def __init__(
        self,
        duckdb:        DuckDBClient,
        profile_risk:  str = "moderate",
        method:        RebalancingMethod = "hrp",
        min_trade_eur: float = 50.0,
        drift_threshold: float = 0.05,
    ) -> None:
        self._duckdb     = duckdb
        self._profile    = profile_risk
        self._method     = method
        self._min_trade  = min_trade_eur
        self._threshold  = drift_threshold

    def run(
        self,
        current_weights:     dict[str, float],
        portfolio_value_eur: float,
        profile_id:          str,
        expected_returns:    dict[str, float] | None = None,
    ) -> RebalancingReport:
        """
        Esegue l'ottimizzazione e genera il piano di ribilanciamento.

        Args:
            current_weights:     {ticker: peso corrente}
            portfolio_value_eur: valore totale del portafoglio in EUR
            profile_id:          ID profilo utente
            expected_returns:    {ticker: rendimento annuo atteso} (solo per Markowitz)

        Returns:
            RebalancingReport con lista di trade e metriche di rischio.
        """
        tickers  = list(current_weights.keys())
        cov_matrix = self._load_covariance(tickers)
        w_current  = np.array([current_weights[t] for t in tickers], dtype=np.float64)
        w_current  = w_current / np.sum(w_current)

        # ── Calcola pesi target con il metodo scelto ─────────────────────────
        if self._method == "hrp":
            w_target = self._optimize_hrp(cov_matrix)
        elif self._method == "markowitz":
            mu = np.array(
                [expected_returns.get(t, 0.07) for t in tickers], dtype=np.float64
            ) if expected_returns else np.full(len(tickers), 0.07, dtype=np.float64)
            w_target = self._optimize_markowitz(mu, cov_matrix)
        elif self._method == "risk_parity":
            w_target = self._optimize_risk_parity(cov_matrix)
        else:  # equal_weight
            w_target = np.full(len(tickers), 1.0 / len(tickers), dtype=np.float64)

        target_weights = {tickers[i]: float(w_target[i]) for i in range(len(tickers))}

        # ── Volatilità corrente e attesa ──────────────────────────────────────
        vol_current  = float(np.sqrt(w_current @ cov_matrix @ w_current) * np.sqrt(252))
        vol_expected = float(np.sqrt(w_target  @ cov_matrix @ w_target)  * np.sqrt(252))

        # ── HHI corrente e atteso ─────────────────────────────────────────────
        hhi_current  = float(np.sum(w_current ** 2))
        hhi_expected = float(np.sum(w_target  ** 2))

        # ── Genera trade instructions ─────────────────────────────────────────
        trades = self._generate_trades(
            tickers, w_current, w_target, portfolio_value_eur
        )

        # ── Turnover totale ───────────────────────────────────────────────────
        total_turnover = float(
            np.sum(np.abs(w_target - w_current)) / 2
        )

        # ── Stima impatto fiscale ─────────────────────────────────────────────
        tax_estimate = self._estimate_tax_impact(trades, portfolio_value_eur)

        report = RebalancingReport(
            report_id=str(uuid.uuid4()),
            computed_at=datetime.now(UTC),
            profile_id=profile_id,
            method=self._method,
            current_weights=current_weights,
            target_weights=target_weights,
            trades=trades,
            portfolio_value_eur=portfolio_value_eur,
            current_vol_annual=vol_current,
            expected_vol_annual=vol_expected,
            current_hhi=hhi_current,
            expected_hhi=hhi_expected,
            total_turnover_pct=total_turnover,
            estimated_tax_eur=tax_estimate,
            n_trades=len([t for t in trades if t.action != "HOLD"]),
            summary=self._build_summary(
                vol_current, vol_expected, hhi_current, hhi_expected,
                total_turnover, tax_estimate, len(trades)
            ),
        )

        self._persist(report)
        log.info(
            "rebalancing.done",
            profile=profile_id, method=self._method,
            n_trades=report.n_trades,
            turnover=round(total_turnover * 100, 1),
            vol_before=round(vol_current * 100, 1),
            vol_after=round(vol_expected * 100, 1),
        )
        return report

    # ─── Metodi di ottimizzazione ─────────────────────────────────────────────

    def _optimize_hrp(self, cov_matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """
        Hierarchical Risk Parity (Lopez de Prado, 2016).

        Vantaggi rispetto a Markowitz:
          · Non richiede stime dei rendimenti attesi (instabili e difficili)
          · Più robusto out-of-sample (meno overfitting)
          · Risultati intuitivi: clustering raggruppa asset simili

        Algoritmo:
          1. Calcola matrice di distanza da correlazioni: d = sqrt((1 - rho) / 2)
          2. Clustering gerarchico Ward sulla matrice di distanza
          3. Quasi-diagonalizzazione: riordina la matrice di covarianza
          4. Recursive bisection: assegna il budget di rischio in modo top-down
        """
        n = cov_matrix.shape[0]

        # 1. Matrice di correlazione → distanza
        std_diag  = np.sqrt(np.diag(cov_matrix))
        corr      = cov_matrix / np.outer(std_diag, std_diag)
        np.fill_diagonal(corr, 1.0)
        corr      = np.clip(corr, -1.0, 1.0)
        dist      = np.sqrt((1.0 - corr) / 2.0)
        np.fill_diagonal(dist, 0.0)

        # 2. Clustering gerarchico Ward
        condensed  = squareform(dist, checks=False)
        link_matrix = linkage(condensed, method="ward")

        # 3. Ordinamento quasi-diagonale (seriation)
        sort_ix = self._get_quasi_diagonal(link_matrix, n)

        # 4. Recursive bisection
        weights = pd.Series(1.0, index=sort_ix)
        cluster_items = [sort_ix]

        while cluster_items:
            cluster_items = [
                item[j:k]
                for item in cluster_items
                for j, k in ((0, len(item) // 2), (len(item) // 2, len(item)))
                if len(item) > 1
            ]
            for sub_cluster in cluster_items:
                if len(sub_cluster) <= 1:
                    continue
                cov_matrix[np.ix_(sub_cluster, sub_cluster)]
                left_half  = sub_cluster[: len(sub_cluster) // 2]
                right_half = sub_cluster[len(sub_cluster) // 2:]

                w_left  = self._cluster_variance(cov_matrix, left_half)
                w_right = self._cluster_variance(cov_matrix, right_half)

                alpha = 1 - w_left / (w_left + w_right)
                weights[left_half]  *= alpha
                weights[right_half] *= 1 - alpha

        w: npt.NDArray[np.float64] = np.asarray(weights.values, dtype=np.float64)
        total = float(w.sum())
        return w / total

    @staticmethod
    def _get_quasi_diagonal(link: npt.NDArray[np.float64], n: int) -> list[int]:
        """Ordina gli indici in modo quasi-diagonale seguendo il dendrogramma."""
        link_int = link[:, :2].astype(int)
        sort_ix  = pd.Series([n + len(link_int) - 1])
        while sort_ix.max() >= n:
            sort_ix.index = range(0, sort_ix.shape[0] * 2, 2)
            df = sort_ix[sort_ix >= n]
            i  = df.index
            j  = df.values - n
            sort_ix[i]     = link_int[j, 0]
            df_tmp         = pd.Series(link_int[j, 1], index=i + 1)
            sort_ix        = pd.concat([sort_ix, df_tmp]).sort_index()
            sort_ix.index  = range(sort_ix.shape[0])
        return [int(x) for x in sort_ix.tolist()]

    @staticmethod
    def _cluster_variance(cov: npt.NDArray[np.float64], idx: list[int]) -> float:
        """Varianza del portafoglio equal-weight sul cluster."""
        sub = cov[np.ix_(idx, idx)]
        n   = len(idx)
        w   = np.ones(n, dtype=np.float64) / n
        return float(w @ sub @ w)

    def _optimize_markowitz(
        self, mu: npt.NDArray[np.float64], cov_matrix: npt.NDArray[np.float64]
    ) -> npt.NDArray[np.float64]:
        """
        Ottimizzazione Mean-Variance tramite cvxpy.
        Massimizza: μᵀw - λ/2 * wᵀΣw
        Soggetto a: Σw = 1, w >= min_weight, w <= max_weight
        """
        try:
            import cvxpy as cp
            n      = len(mu)
            w_var  = cp.Variable(n, nonneg=True)
            lambda_ = 3.0   # risk aversion

            objective = cp.Maximize(
                mu @ w_var - lambda_ / 2 * cp.quad_form(w_var, cov_matrix)  # type: ignore[attr-defined]
            )
            constraints = [
                cp.sum(w_var) == 1,  # type: ignore[attr-defined]
                w_var >= 0.02,    # min weight
                w_var <= 0.40,    # max weight
            ]
            prob = cp.Problem(objective, constraints)
            prob.solve(solver=cp.OSQP, warm_start=True)  # type: ignore[no-untyped-call]

            if w_var.value is not None:
                w: npt.NDArray[np.float64] = np.array(w_var.value, dtype=np.float64)
                w = np.clip(w, 0, 1)
                total = float(w.sum())
                return w / total
        except Exception as exc:
            log.warning("markowitz.failed", error=str(exc)[:100], fallback="hrp")

        return self._optimize_hrp(cov_matrix)

    def _optimize_risk_parity(self, cov_matrix: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """
        Equal Risk Contribution: ogni asset contribuisce ugualmente al rischio.
        Risolto iterativamente (Newton-Raphson).
        """
        n  = cov_matrix.shape[0]
        w  = np.ones(n, dtype=np.float64) / n

        for _ in range(500):
            port_var = float(w @ cov_matrix @ w)
            if port_var <= 0:
                break
            mrc  = (cov_matrix @ w) / np.sqrt(port_var)
            rc   = w * mrc
            target_rc = port_var / n

            # Gradient ascent verso equal risk contribution
            grad = rc - target_rc
            w   -= 0.01 * grad
            w    = np.clip(w, 1e-6, None)
            w   /= w.sum()

            if np.max(np.abs(grad)) < 1e-8:
                break

        total = float(w.sum())
        return w / total

    # ─── Trade generation e utilità ──────────────────────────────────────────

    def _generate_trades(
        self,
        tickers:     list[str],
        w_current:   npt.NDArray[np.float64],
        w_target:    npt.NDArray[np.float64],
        total_eur:   float,
    ) -> list[TradeInstruction]:
        trades = []
        for i, ticker in enumerate(tickers):
            drift = float(w_target[i] - w_current[i])
            eur   = abs(drift) * total_eur

            if abs(drift) < self._threshold and eur < self._min_trade:
                action: Literal["BUY", "SELL", "HOLD"] = "HOLD"
            elif drift > 0:
                action = "BUY"
            else:
                action = "SELL"

            trades.append(TradeInstruction(
                ticker=ticker,
                action=action,
                current_weight=float(w_current[i]),
                target_weight=float(w_target[i]),
                drift_pct=drift * 100,
                estimated_eur=round(eur, 2) if action != "HOLD" else 0.0,
                priority=1 if abs(drift) > 0.10 else (2 if abs(drift) > 0.05 else 3),
            ))

        # Ordina per priorità decrescente (maggiore drift prima)
        return sorted(trades, key=lambda t: -abs(t.drift_pct))

    def _estimate_tax_impact(
        self, trades: list[TradeInstruction], total_eur: float
    ) -> float:
        """
        Stima l'impatto fiscale dei SELL (regime IT: 26% capital gain).
        Assume una plusvalenza media del 15% sulle posizioni vendute.
        Questo è un'approssimazione — il calcolo esatto richiede TaxCalculator.
        """
        total_sell_eur = sum(
            t.estimated_eur for t in trades if t.action == "SELL"
        )
        assumed_gain_pct = 0.15   # plusvalenza media assunta
        return round(total_sell_eur * assumed_gain_pct * 0.26, 2)

    def _load_covariance(self, tickers: list[str]) -> npt.NDArray[np.float64]:
        """Carica la matrice di covarianza dal DB (DCC-GARCH)."""
        n = len(tickers)
        try:
            rows = self._duckdb.query(
                "SELECT covariance_matrix_json FROM correlation_reports "
                "ORDER BY computed_at DESC LIMIT 1"
            )
            row = rows[0] if rows else None
            if row and row[0]:
                full_cov = json.loads(row[0])
                cov = np.zeros((n, n), dtype=np.float64)
                for i, ti in enumerate(tickers):
                    for j, tj in enumerate(tickers):
                        cov[i, j] = full_cov.get(ti, {}).get(tj, 0.0)
                        if i == j and cov[i, j] <= 0:
                            cov[i, j] = 0.04  # 20% vol default
                # Assicura che la matrice sia definita positiva
                min_eig = np.min(np.linalg.eigvals(cov))
                if min_eig < 1e-8:
                    cov += np.eye(n) * (abs(min_eig) + 1e-6)
                return cov
        except Exception as exc:
            log.warning("rebalancing.cov_load_failed", error=str(exc)[:100])

        # Fallback: matrice diagonale
        return np.eye(n, dtype=np.float64) * 0.04

    @staticmethod
    def _build_summary(
        vol_before: float, vol_after: float,
        hhi_before: float, hhi_after: float,
        turnover:   float, tax:       float,
        n_trades:   int,
    ) -> str:
        vol_delta   = (vol_after - vol_before) * 100
        vol_sign    = "+" if vol_delta > 0 else ""
        hhi_delta   = (hhi_after - hhi_before)
        div_improve = "migliora" if hhi_delta < 0 else "peggiora"
        return (
            f"Piano di ribilanciamento: {n_trades} operazioni. "
            f"Turnover: {turnover * 100:.1f}% del portafoglio. "
            f"Volatilità: {vol_before * 100:.1f}% → {vol_after * 100:.1f}% "
            f"({vol_sign}{vol_delta:.1f}%). "
            f"Diversificazione {div_improve} (HHI: {hhi_before:.2f} → {hhi_after:.2f}). "
            f"Impatto fiscale stimato: €{tax:,.0f}."
        )

    def _persist(self, r: RebalancingReport) -> None:
        self._duckdb.execute(
            """INSERT INTO rebalancing_reports
               (report_id, computed_at, profile_id, method,
                current_vol, target_vol, current_hhi, expected_hhi,
                total_trades, total_turnover_pct, estimated_tax_impact_eur,
                trades_json, weights_current_json, weights_target_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [r.report_id, r.computed_at, r.profile_id, r.method,
             r.current_vol_annual, r.expected_vol_annual,
             r.current_hhi, r.expected_hhi,
             r.n_trades, r.total_turnover_pct, r.estimated_tax_eur,
             json.dumps([vars(t) for t in r.trades]),
             json.dumps(r.current_weights),
             json.dumps(r.target_weights)],
        )


# pandas import necessario per HRP
