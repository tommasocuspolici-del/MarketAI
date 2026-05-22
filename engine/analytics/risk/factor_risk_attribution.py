"""Factor Risk Attribution — Barra-style decomposition.

Decompone il rischio del portafoglio in fattori sistematici
(Fama-French 5: Mkt, SMB, HML, RMW, CMA) + idiosincratico.
Usa regressione OLS su rendimenti storici.

Se i rendimenti Fama-French non sono disponibili, estrae fattori latenti
via PCA come proxy (stessa filosofia, dati interni).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.linear_model import LinearRegression

from shared.feature_flags import is_enabled
from shared.logger import get_logger

__version__ = "11.0.0"

__all__ = ["FactorRiskAttribution", "AttributionResult", "FactorExposure"]

log = get_logger(__name__)

FEATURE_FLAG = "factor_risk_attribution"
FAMA_FRENCH_FACTORS: list[str] = ["Mkt-RF", "SMB", "HML", "RMW", "CMA"]
MIN_REGRESSION_SAMPLES: int = 60
N_PCA_FACTORS: int = 5      # numero fattori latenti se FF non disponibili


@dataclass
class FactorExposure:
    """Esposizione ai fattori di rischio per un singolo asset."""

    ticker: str
    factor_loadings: dict[str, float]   # factor → beta
    r_squared: float
    tracking_error: float               # std del residuo (annualizzata)


@dataclass
class AttributionResult:
    """Risultato decomposizione rischio per il portafoglio."""

    portfolio_variance: float
    systematic_variance: float          # variance spiegata dai fattori
    idiosyncratic_variance: float
    factor_contributions: dict[str, float]   # factor → variance contribution
    pct_systematic: float               # systematic/total
    exposures: list[FactorExposure] = field(default_factory=list)


class FactorRiskAttribution:
    """Barra-style factor risk decomposition.

    Se factor_returns è None, usa PCA sui rendimenti del portafoglio
    per stimare fattori latenti (proxy Fama-French).

    Feature flag: factor_risk_attribution (default false per compatibilità
    con sklearn opzionale).
    """

    def __init__(self) -> None:
        pass

    def compute(
        self,
        portfolio_weights: dict[str, float],
        returns_matrix: pd.DataFrame,
        factor_returns: pd.DataFrame | None = None,
    ) -> AttributionResult:
        """Calcola decomposizione rischio Barra-style.

        Parameters
        ----------
        portfolio_weights:
            Mappa ticker → peso (verranno normalizzati internamente).
        returns_matrix:
            DataFrame con colonne=tickers, righe=date (rendimenti giornalieri).
        factor_returns:
            DataFrame con colonne=FAMA_FRENCH_FACTORS, righe=date.
            Se None, viene stimato via PCA.
        """
        tickers = list(portfolio_weights.keys())
        weights_arr = np.array([portfolio_weights[t] for t in tickers], dtype=float)
        w_sum = weights_arr.sum()
        if abs(w_sum) > 1e-12:
            weights_arr /= w_sum

        # Allinea i rendimenti agli asset nel portafoglio
        avail = [t for t in tickers if t in returns_matrix.columns]
        if not avail:
            log.warning("factor_risk.no_common_tickers")
            return self._empty_result()

        rets = returns_matrix[avail].dropna()
        if len(rets) < MIN_REGRESSION_SAMPLES:
            log.warning(
                "factor_risk.insufficient_samples",
                n=len(rets),
                required=MIN_REGRESSION_SAMPLES,
            )

        # Fattori: usa quelli forniti o proxy PCA
        if factor_returns is not None:
            factors = factor_returns.reindex(rets.index).dropna()
            factors = factors.reindex(rets.index).fillna(0.0)
            factor_names = list(factors.columns)
        else:
            factors = self._estimate_factor_returns_proxy(rets)
            factor_names = list(factors.columns)

        # Regressione per ogni asset
        exposures: list[FactorExposure] = []
        residuals_list: list[np.ndarray] = []
        loadings_matrix: list[list[float]] = []

        for ticker in avail:
            ret_series = rets[ticker].to_numpy(dtype=float)
            factor_df = factors.reindex(rets.index).fillna(0.0)
            expo = self._regress_loadings(
                asset_returns=pd.Series(ret_series, index=rets.index),
                factor_returns=factor_df,
            )
            expo = FactorExposure(
                ticker=ticker,
                factor_loadings=expo.factor_loadings,
                r_squared=expo.r_squared,
                tracking_error=expo.tracking_error,
            )
            exposures.append(expo)
            loadings_matrix.append([expo.factor_loadings.get(f, 0.0) for f in factor_names])

            # Calcola residui per stima varianza idiosincratica
            X = factors.reindex(rets.index).fillna(0.0).to_numpy(dtype=float)
            betas = np.array([expo.factor_loadings.get(f, 0.0) for f in factor_names])
            fitted = X @ betas
            residuals_list.append(ret_series - fitted)

        # Varianza portafoglio
        weights_sub = np.array([portfolio_weights.get(t, 0.0) for t in avail], dtype=float)
        w_sub_sum = weights_sub.sum()
        if abs(w_sub_sum) > 1e-12:
            weights_sub /= w_sub_sum

        port_returns = rets[avail].to_numpy(dtype=float) @ weights_sub
        port_variance = float(np.var(port_returns, ddof=1))

        # Varianza sistematica: var(B'w * F)
        B = np.array(loadings_matrix)         # (n_assets, n_factors)
        port_factor_exposure = weights_sub @ B  # (n_factors,)
        factor_cov = np.cov(
            factors.reindex(rets.index).fillna(0.0).to_numpy(dtype=float),
            rowvar=False,
        ) if len(factor_names) > 1 else np.array([[np.var(
            factors.reindex(rets.index).fillna(0.0).to_numpy(dtype=float)[:, 0], ddof=1
        )]])

        systematic_variance = float(port_factor_exposure @ factor_cov @ port_factor_exposure)
        idiosyncratic_variance = max(port_variance - systematic_variance, 0.0)

        # Contributo per fattore: (exposure_i)² * var(factor_i)
        factor_contributions: dict[str, float] = {}
        if factor_cov.ndim == 2:
            for j, fname in enumerate(factor_names):
                fc = float(port_factor_exposure[j] ** 2 * factor_cov[j, j])
                factor_contributions[fname] = fc

        pct_systematic = systematic_variance / port_variance if port_variance > 1e-12 else 0.0

        log.info(
            "factor_risk.computed",
            n_assets=len(avail),
            pct_systematic=round(pct_systematic, 3),
            port_variance=round(port_variance, 6),
        )

        return AttributionResult(
            portfolio_variance=port_variance,
            systematic_variance=systematic_variance,
            idiosyncratic_variance=idiosyncratic_variance,
            factor_contributions=factor_contributions,
            pct_systematic=pct_systematic,
            exposures=exposures,
        )

    def _estimate_factor_returns_proxy(
        self,
        returns_matrix: pd.DataFrame,
    ) -> pd.DataFrame:
        """Proxy Fama-French: usa PCA per estrarre fattori latenti."""
        rets_clean = returns_matrix.dropna()
        n_components = min(N_PCA_FACTORS, rets_clean.shape[1], rets_clean.shape[0] - 1)
        if n_components < 1:
            # Fallback: usa solo il primo momento (mercato)
            factor_names = ["PC1"]
            return pd.DataFrame(
                {"PC1": rets_clean.mean(axis=1)},
                index=rets_clean.index,
            )

        pca = PCA(n_components=n_components)
        components = pca.fit_transform(rets_clean.to_numpy(dtype=float))
        factor_names = [f"PC{i+1}" for i in range(n_components)]
        return pd.DataFrame(components, index=rets_clean.index, columns=factor_names)

    def _regress_loadings(
        self,
        asset_returns: pd.Series,
        factor_returns: pd.DataFrame,
    ) -> FactorExposure:
        """OLS regression of asset returns on factor returns."""
        common_idx = asset_returns.index.intersection(factor_returns.index)
        if len(common_idx) < 2:
            factor_names = list(factor_returns.columns)
            return FactorExposure(
                ticker="unknown",
                factor_loadings={f: 0.0 for f in factor_names},
                r_squared=0.0,
                tracking_error=0.0,
            )

        y = asset_returns.reindex(common_idx).to_numpy(dtype=float)
        X = factor_returns.reindex(common_idx).to_numpy(dtype=float)
        factor_names = list(factor_returns.columns)

        model = LinearRegression(fit_intercept=True)
        model.fit(X, y)
        betas = model.coef_.tolist()
        r2 = float(model.score(X, y))

        y_hat = model.predict(X)
        residuals = y - y_hat
        tracking_error = float(np.std(residuals, ddof=1) * np.sqrt(252))

        return FactorExposure(
            ticker="",
            factor_loadings={f: float(b) for f, b in zip(factor_names, betas)},
            r_squared=max(0.0, min(1.0, r2)),
            tracking_error=tracking_error,
        )

    @staticmethod
    def _empty_result() -> AttributionResult:
        return AttributionResult(
            portfolio_variance=0.0,
            systematic_variance=0.0,
            idiosyncratic_variance=0.0,
            factor_contributions={},
            pct_systematic=0.0,
            exposures=[],
        )
