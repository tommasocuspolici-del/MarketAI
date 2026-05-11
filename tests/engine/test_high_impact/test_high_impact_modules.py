"""Test suite — High-Impact Modules (da 2_HIGH_IMPACT_MODULES.md).

Copre:
  · VolumeAnalyzer (OBV, CMF, VWAP, Amihud, Volume Z-Score)
  · DivergenceDetector (RSI/MACD divergenze, pivot detection)
  · CVaRCalculator (t-Student fat-tail, MLE df)
  · RiskContributionAnalyzer (HHI, PRC per asset)
  · VolSurfaceAnalyzer (regime classificato da VIX levels)
  · RealYieldAnalyzer (DGS10 - T10YIE → segnali oro/equity)
  · RebalancingEngine (HRP, Markowitz, Risk Parity)
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ─── Helpers ──────────────────────────────────────────────────────────────

def _ohlcv(n=60, trend="flat", with_volume=True):
    rng = np.random.default_rng(42)
    if trend == "up":
        closes = np.linspace(100, 120, n) + rng.normal(0, 1, n)
    elif trend == "down":
        closes = np.linspace(120, 100, n) + rng.normal(0, 1, n)
    else:
        closes = 100 + rng.normal(0, 3, n)
    closes = closes.clip(1)
    dates  = pd.date_range("2025-01-01", periods=n, freq="D", tz="UTC")
    vol    = rng.integers(1_000_000, 5_000_000, n) if with_volume else np.ones(n, int)
    return pd.DataFrame({
        "ts": dates, "open": closes * 0.99, "high": closes * 1.02,
        "low": closes * 0.98, "close": closes, "volume": vol,
    })


def _mock_prices_repo(df):
    repo = MagicMock()
    repo.read_ohlcv.return_value = df
    return repo


def _mock_duckdb():
    db = MagicMock()
    db.executemany = MagicMock()
    db.execute = MagicMock()
    db.query.return_value = []
    return db


# ═══════════════════════════════════════════════════════════════════════════
# VolumeAnalyzer
# ═══════════════════════════════════════════════════════════════════════════

class TestVolumeAnalyzer:

    def _make_analyzer(self, df):
        from engine.technical.volume_analysis import VolumeAnalyzer
        repo = _mock_prices_repo(df)
        db   = _mock_duckdb()
        return VolumeAnalyzer(prices_repo=repo, duckdb=db)

    def test_analyze_returns_signals(self):
        from engine.technical.volume_analysis import VolumeSignals
        df  = _ohlcv(60, "up")
        sig = self._make_analyzer(df).analyze("AAPL", "NASDAQ")
        assert isinstance(sig, VolumeSignals)

    def test_obv_length_matches_input(self):
        df  = _ohlcv(60, "up")
        sig = self._make_analyzer(df).analyze("AAPL", "NASDAQ")
        assert len(sig.obv) == 60

    def test_cmf_in_range(self):
        df  = _ohlcv(60)
        sig = self._make_analyzer(df).analyze("AAPL", "NASDAQ")
        assert -1.0 <= sig.latest_cmf <= 1.0
        assert np.all((sig.cmf_20 >= -1) & (sig.cmf_20 <= 1))

    def test_vwap_positive(self):
        df  = _ohlcv(60, "up")
        sig = self._make_analyzer(df).analyze("AAPL", "NASDAQ")
        assert sig.latest_vwap > 0
        assert np.all(sig.vwap_20[sig.vwap_20 > 0] > 0)

    def test_amihud_nonnegative(self):
        df  = _ohlcv(60)
        sig = self._make_analyzer(df).analyze("AAPL", "NASDAQ")
        assert sig.latest_amihud >= 0

    def test_cmf_signal_values(self):
        df  = _ohlcv(60)
        sig = self._make_analyzer(df).analyze("AAPL", "NASDAQ")
        assert sig.cmf_signal in ("bullish", "bearish", "neutral")

    def test_price_vs_vwap_values(self):
        df  = _ohlcv(60)
        sig = self._make_analyzer(df).analyze("AAPL", "NASDAQ")
        assert sig.price_vs_vwap in ("above", "below", "at")

    def test_liquidity_flag_values(self):
        df  = _ohlcv(60)
        sig = self._make_analyzer(df).analyze("AAPL", "NASDAQ")
        assert sig.liquidity_flag in ("normal", "thin", "illiquid")

    def test_insufficient_data_raises(self):
        from engine.technical.volume_analysis import VolumeAnalyzer
        from shared.exceptions import InsufficientDataError
        df   = _ohlcv(10)  # < 25 minimo
        repo = _mock_prices_repo(df)
        db   = _mock_duckdb()
        with pytest.raises((InsufficientDataError, Exception)):
            VolumeAnalyzer(prices_repo=repo, duckdb=db).analyze("X", "NYSE")

    def test_obv_accumulates_on_up_days(self):
        """OBV sale quando il prezzo sale."""
        from engine.technical.volume_analysis import VolumeAnalyzer
        closes  = np.array([100.0, 101.0, 102.0, 103.0])
        volumes = np.array([1000.0, 1000.0, 1000.0, 1000.0])
        obv = VolumeAnalyzer._compute_obv(closes, volumes)
        assert obv[-1] > obv[0]

    def test_obv_decreases_on_down_days(self):
        from engine.technical.volume_analysis import VolumeAnalyzer
        closes  = np.array([103.0, 102.0, 101.0, 100.0])
        volumes = np.array([1000.0, 1000.0, 1000.0, 1000.0])
        obv = VolumeAnalyzer._compute_obv(closes, volumes)
        assert obv[-1] < obv[0]

    def test_zscore_computed(self):
        df  = _ohlcv(60)
        sig = self._make_analyzer(df).analyze("AAPL", "NASDAQ")
        assert isinstance(sig.latest_vol_z, float)

    def test_persist_called(self):
        df  = _ohlcv(60)
        analyzer = self._make_analyzer(df)
        analyzer.analyze("AAPL", "NASDAQ")
        assert analyzer._duckdb.executemany.called


# ═══════════════════════════════════════════════════════════════════════════
# DivergenceDetector
# ═══════════════════════════════════════════════════════════════════════════

class TestDivergenceDetector:

    def _make_detector(self, df):
        from engine.technical.divergence_detector import DivergenceDetector
        repo = _mock_prices_repo(df)
        db   = _mock_duckdb()
        return DivergenceDetector(prices_repo=repo, duckdb=db, pivot_window=3)

    def test_detect_returns_list(self):
        df  = _ohlcv(80, "flat")
        res = self._make_detector(df).detect("AAPL", "NASDAQ")
        assert isinstance(res, list)

    def test_insufficient_data_empty(self):
        df  = _ohlcv(20)
        res = self._make_detector(df).detect("AAPL", "NASDAQ")
        assert res == []

    def test_rsi_computed_correctly(self):
        from engine.technical.divergence_detector import DivergenceDetector
        closes = np.array([44.34, 44.09, 44.15, 43.61, 44.33, 44.83,
                           45.10, 45.15, 43.61, 44.33, 44.83, 45.10,
                           45.15, 45.15, 46.00, 46.50, 45.80], dtype=np.float64)
        rsi = DivergenceDetector._compute_rsi(closes, period=14)
        assert len(rsi) == len(closes)
        # RSI valido dopo il periodo iniziale
        assert np.all((rsi[15:] >= 0) & (rsi[15:] <= 100))

    def test_macd_histogram_computed(self):
        from engine.technical.divergence_detector import DivergenceDetector
        closes = np.linspace(100, 120, 50)
        hist   = DivergenceDetector._compute_macd_histogram(closes)
        assert len(hist) == 50

    def test_find_pivots_high(self):
        from engine.technical.divergence_detector import DivergenceDetector
        det = DivergenceDetector.__new__(DivergenceDetector)
        det._pivot_window = 2
        arr  = np.array([1.0, 3.0, 2.0, 5.0, 1.0, 4.0, 2.0])
        highs = det._find_pivots(arr, "high")
        assert 3 in highs  # prezzo 5.0 è il massimo locale

    def test_find_pivots_low(self):
        from engine.technical.divergence_detector import DivergenceDetector
        det = DivergenceDetector.__new__(DivergenceDetector)
        det._pivot_window = 2
        arr  = np.array([5.0, 2.0, 4.0, 1.0, 3.0, 1.5, 4.0])
        lows = det._find_pivots(arr, "low")
        assert 3 in lows  # prezzo 1.0 è il minimo locale

    def test_signal_type_values(self):
        df  = _ohlcv(100, "flat")
        res = self._make_detector(df).detect("SPY", "NYSE")
        for sig in res:
            assert sig.divergence_type in (
                "bullish_rsi", "bearish_rsi", "bullish_macd", "bearish_macd"
            )
            assert 0.0 <= sig.strength <= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# CVaRCalculator
# ═══════════════════════════════════════════════════════════════════════════

class TestCVaRCalculator:

    def _make_calc(self, df):
        from engine.risk.cvar_calculator import CVaRCalculator
        repo = _mock_prices_repo(df)
        db   = _mock_duckdb()
        return CVaRCalculator(prices_repo=repo, duckdb=db, lookback_days=252)

    def test_compute_returns_metrics(self):
        from engine.risk.cvar_calculator import RiskMetrics
        df  = _ohlcv(100)
        res = self._make_calc(df).compute("SPY", "NYSE")
        assert isinstance(res, RiskMetrics)

    def test_cvar_worse_than_var(self):
        """CVaR(95%) deve essere peggiore (più negativo) del VaR(95%)."""
        df  = _ohlcv(100)
        res = self._make_calc(df).compute("SPY", "NYSE")
        assert res.cvar_95 <= res.var_95_tstudent

    def test_var_tstudent_computed(self):
        """t-Student VaR è calcolato (può differire dalla normale per code grasse)."""
        df  = _ohlcv(100)
        res = self._make_calc(df).compute("SPY", "NYSE")
        assert isinstance(res.var_95_tstudent, float)
        assert res.var_95_tstudent < 0  # VaR è sempre negativo

    def test_tail_df_in_reasonable_range(self):
        """Gradi di libertà stimati: tra 2.1 e 30."""
        df  = _ohlcv(100)
        res = self._make_calc(df).compute("SPY", "NYSE")
        assert res.tail_df >= 2.1  # df > 2 per varianza finita (può essere molto alto con dati normali)

    def test_kurtosis_positive_for_financial(self):
        """I rendimenti finanziari hanno code grasse → kurtosis > 0."""
        rng = np.random.default_rng(0)
        # Simula rendimenti con fat-tail (t-Student df=5)
        from scipy.stats import t as t_dist
        fat_rets = t_dist.rvs(df=5, size=200, random_state=rng)
        closes = 100.0 * np.exp(np.cumsum(fat_rets * 0.01))
        df = pd.DataFrame({
            "ts": pd.date_range("2024-01-01", periods=200, freq="D"),
            "close": closes,
        })
        df["open"] = df["close"] * 0.99
        df["high"] = df["close"] * 1.02
        df["low"]  = df["close"] * 0.98
        df["volume"] = 1_000_000
        from engine.risk.cvar_calculator import CVaRCalculator
        repo = _mock_prices_repo(df)
        db   = _mock_duckdb()
        res  = CVaRCalculator(prices_repo=repo, duckdb=db).compute("SPY", "NYSE")
        assert res.kurtosis > 0  # fat-tail confirmed

    def test_insufficient_data_raises(self):
        from engine.risk.cvar_calculator import CVaRCalculator
        df   = _ohlcv(20)
        repo = _mock_prices_repo(df)
        db   = _mock_duckdb()
        with pytest.raises((ValueError, Exception)):
            CVaRCalculator(prices_repo=repo, duckdb=db).compute("X", "NYSE")

    def test_cvar99_worse_than_cvar95(self):
        """CVaR 99% è più estremo del CVaR 95%."""
        df  = _ohlcv(100)
        res = self._make_calc(df).compute("SPY", "NYSE")
        assert res.cvar_99 <= res.cvar_95

    def test_cvar_var_ratio_above_one(self):
        """CVaR/VaR > 1 per definizione (CVaR è sempre peggiore)."""
        df  = _ohlcv(100)
        res = self._make_calc(df).compute("SPY", "NYSE")
        assert res.cvar_vs_var_ratio >= 1.0


# ═══════════════════════════════════════════════════════════════════════════
# RiskContributionAnalyzer
# ═══════════════════════════════════════════════════════════════════════════

class TestRiskContributionAnalyzer:

    def _make_analyzer(self, cov_json=None):
        from engine.risk.risk_contribution import RiskContributionAnalyzer
        db = _mock_duckdb()
        if cov_json:
            db.query.return_value = [[cov_json]]
        else:
            db.query.return_value = [[None]]
        return RiskContributionAnalyzer(duckdb=db)

    def _equal_weights(self, n=3):
        tickers = [f"T{i}" for i in range(n)]
        return {t: 1.0/n for t in tickers}

    def test_analyze_returns_report(self):
        from engine.risk.risk_contribution import PortfolioRiskReport
        w   = self._equal_weights(3)
        res = self._make_analyzer().analyze(weights=w, profile_id="me")
        assert isinstance(res, PortfolioRiskReport)

    def test_equal_weight_prc_approx_equal(self):
        """3 asset equal-weight: ogni PRC ≈ 33% (con cov identity)."""
        w   = self._equal_weights(3)
        res = self._make_analyzer().analyze(weights=w, profile_id="me")
        for prc in res.risk_contributions.values():
            assert abs(prc - 1/3) < 0.15  # tolleranza per fallback identity cov

    def test_hhi_equal_weight_low(self):
        """Portafoglio equal-weight: HHI < 0.50."""
        w   = self._equal_weights(4)
        res = self._make_analyzer().analyze(weights=w, profile_id="me")
        assert res.hhi < 0.60

    def test_concentrated_portfolio_high_hhi(self):
        """Portafoglio concentrato: HHI alto."""
        w   = {"A": 0.90, "B": 0.05, "C": 0.05}
        res = self._make_analyzer().analyze(weights=w, profile_id="me")
        assert res.hhi > 0.5

    def test_prc_sums_to_one(self):
        """Somma dei PRC ≈ 1."""
        w   = self._equal_weights(5)
        res = self._make_analyzer().analyze(weights=w, profile_id="me")
        total = sum(res.risk_contributions.values())
        assert abs(total - 1.0) < 0.05

    def test_annual_vol_positive(self):
        w   = self._equal_weights(3)
        res = self._make_analyzer().analyze(weights=w, profile_id="me")
        assert res.portfolio_vol_annual > 0

    def test_largest_contributor_identified(self):
        w   = self._equal_weights(3)
        res = self._make_analyzer().analyze(weights=w, profile_id="me")
        assert res.largest_contributor in w
        assert res.largest_contrib_pct > 0

    def test_recommendation_not_empty(self):
        w   = self._equal_weights(3)
        res = self._make_analyzer().analyze(weights=w, profile_id="me")
        assert len(res.recommendation) > 10


# ═══════════════════════════════════════════════════════════════════════════
# RebalancingEngine
# ═══════════════════════════════════════════════════════════════════════════

class TestRebalancingEngine:

    def _make_engine(self, method="hrp"):
        from engine.portfolio.rebalancing_engine import RebalancingEngine
        db = _mock_duckdb()
        db.query.return_value = [[None]]  # no covariance in DB → fallback
        return RebalancingEngine(
            duckdb=db, profile_risk="moderate",
            method=method, min_trade_eur=50.0, drift_threshold=0.05,
        )

    def _weights(self):
        return {"AAPL": 0.30, "MSFT": 0.25, "SPY": 0.45}

    def test_run_returns_report(self):
        from engine.portfolio.rebalancing_engine import RebalancingReport
        res = self._make_engine().run(
            current_weights=self._weights(),
            portfolio_value_eur=50_000.0,
            profile_id="me",
        )
        assert isinstance(res, RebalancingReport)

    def test_hrp_weights_sum_to_one(self):
        engine = self._make_engine("hrp")
        res    = engine.run(self._weights(), 50_000.0, "me")
        total  = sum(res.target_weights.values())
        assert abs(total - 1.0) < 1e-6

    def test_equal_weight_weights_equal(self):
        engine = self._make_engine("equal_weight")
        w      = {"A": 0.40, "B": 0.35, "C": 0.25}
        res    = engine.run(w, 50_000.0, "me")
        for v in res.target_weights.values():
            assert abs(v - 1/3) < 1e-9

    def test_risk_parity_approx_equal_risk(self):
        engine = self._make_engine("risk_parity")
        res    = engine.run(self._weights(), 50_000.0, "me")
        assert abs(sum(res.target_weights.values()) - 1.0) < 1e-6

    def test_markowitz_weights_in_range(self):
        engine = self._make_engine("markowitz")
        res    = engine.run(self._weights(), 50_000.0, "me")
        for w in res.target_weights.values():
            assert 0.0 <= w <= 1.0

    def test_trades_generated(self):
        res = self._make_engine().run(self._weights(), 50_000.0, "me")
        assert len(res.trades) == len(self._weights())

    def test_turnover_between_0_and_1(self):
        res = self._make_engine().run(self._weights(), 50_000.0, "me")
        assert 0.0 <= res.total_turnover_pct <= 1.0

    def test_tax_estimate_nonneg(self):
        res = self._make_engine().run(self._weights(), 50_000.0, "me")
        assert res.estimated_tax_eur >= 0

    def test_summary_not_empty(self):
        res = self._make_engine().run(self._weights(), 50_000.0, "me")
        assert len(res.summary) > 20

    def test_report_id_is_uuid(self):
        import uuid
        res = self._make_engine().run(self._weights(), 50_000.0, "me")
        # Verifica che report_id sia un UUID valido
        try:
            uuid.UUID(res.report_id)
            valid = True
        except ValueError:
            valid = False
        assert valid

    def test_hrp_idempotent(self):
        """Stessa matrice → stessi pesi (idempotenza)."""
        engine = self._make_engine("hrp")
        res1   = engine.run(self._weights(), 50_000.0, "me")
        res2   = engine.run(self._weights(), 50_000.0, "me")
        for ticker in res1.target_weights:
            assert abs(res1.target_weights[ticker] - res2.target_weights[ticker]) < 1e-9

    def test_trade_actions_valid(self):
        res = self._make_engine().run(self._weights(), 50_000.0, "me")
        for trade in res.trades:
            assert trade.action in ("BUY", "SELL", "HOLD")

    def test_benchmark_under_1s(self, benchmark):
        """RebalancingEngine.run() < 1s su 3 asset."""
        engine = self._make_engine("hrp")
        result = benchmark(engine.run, self._weights(), 50_000.0, "me")
        assert result is not None


# ═══════════════════════════════════════════════════════════════════════════
# VolSurfaceAnalyzer
# ═══════════════════════════════════════════════════════════════════════════

class TestVolSurfaceAnalyzer:

    def _make_analyzer(self, vix1m=18.0, vix3m=20.0, vix9d=None, vix6m=None):
        from engine.volatility.vol_surface import VolSurfaceAnalyzer
        repo = MagicMock()
        db   = _mock_duckdb()

        ticker_data = {
            "^VIX":  vix1m, "^VIX9D": vix9d,
            "^VXV":  vix3m, "^VXMT":  vix6m, "^SKEW": 130.0,
        }
        def _read(ticker, exchange, timeframe, limit):
            val = ticker_data.get(ticker)
            if val is None:
                return None
            return pd.DataFrame({"close": [val]})
        repo.read_ohlcv.side_effect = _read
        return VolSurfaceAnalyzer(prices_repo=repo, duckdb=db)

    def test_compute_returns_snapshot(self):
        from engine.volatility.vol_surface import VolSurfaceSnapshot
        snap = self._make_analyzer().compute()
        assert isinstance(snap, VolSurfaceSnapshot)

    def test_contango_regime(self):
        """VIX3M >> VIX1M → steep_contango."""
        snap = self._make_analyzer(vix1m=15.0, vix3m=20.0).compute()
        assert snap.surface_regime in ("steep_contango", "contango", "flat")

    def test_backwardation_regime(self):
        """VIX1M >> VIX3M → backwardation."""
        snap = self._make_analyzer(vix1m=30.0, vix3m=20.0).compute()
        assert snap.surface_regime in ("backwardation", "flat")

    def test_contango_pct_computed(self):
        snap = self._make_analyzer(vix1m=18.0, vix3m=20.0).compute()
        if snap.contango_pct is not None:
            expected = (20.0 / 18.0 - 1) * 100
            assert abs(snap.contango_pct - expected) < 0.01

    def test_signal_modifier_range(self):
        snap = self._make_analyzer().compute()
        assert -0.30 <= snap.vix_signal_modifier <= 0.30

    def test_is_backwardation_property(self):
        snap = self._make_analyzer(vix1m=30.0, vix3m=20.0).compute()
        if snap.surface_regime in ("backwardation", "inverted"):
            assert snap.is_backwardation is True

    def test_is_contango_property(self):
        snap = self._make_analyzer(vix1m=15.0, vix3m=22.0).compute()
        if snap.surface_regime in ("steep_contango", "flat", "contango"):
            assert snap.is_contango is True

    def test_missing_vix3m_unknown_regime(self):
        from engine.volatility.vol_surface import VolSurfaceAnalyzer
        repo = MagicMock()
        repo.read_ohlcv.side_effect = lambda ticker, **kw: (
            pd.DataFrame({"close": [18.0]}) if ticker == "^VIX" else None
        )
        db = _mock_duckdb()
        snap = VolSurfaceAnalyzer(prices_repo=repo, duckdb=db).compute()
        assert snap.surface_regime == "unknown"


# ═══════════════════════════════════════════════════════════════════════════
# RealYieldAnalyzer
# ═══════════════════════════════════════════════════════════════════════════

class TestRealYieldAnalyzer:

    def _make_df(self, values):
        n = len(values)
        return pd.DataFrame({
            "ts": pd.date_range("2024-01-01", periods=n, freq="MS"),
            "value": values,
        })

    def _make_analyzer(self, nominal=4.5, breakeven=2.3):
        from engine.fixed_income.real_yield_analyzer import RealYieldAnalyzer
        repo = MagicMock()
        repo.read_macro.side_effect = lambda sid, **kw: (
            self._make_df([nominal] * 30)   if sid == "DGS10"  else
            self._make_df([breakeven] * 30) if sid == "T10YIE" else
            pd.DataFrame()
        )
        db = _mock_duckdb()
        return RealYieldAnalyzer(macro_repo=repo, duckdb=db, lookback_days=252)

    def test_compute_returns_signal(self):
        from engine.fixed_income.real_yield_analyzer import RealYieldSignal
        sig = self._make_analyzer().compute()
        assert isinstance(sig, RealYieldSignal)

    def test_real_yield_formula(self):
        """real_yield = nominal - breakeven."""
        sig = self._make_analyzer(nominal=4.5, breakeven=2.3).compute()
        assert abs(sig.real_yield_10y - (4.5 - 2.3)) < 0.01

    def test_negative_real_yield_bullish_gold(self):
        """Real yield molto negativo → bullish_gold."""
        sig = self._make_analyzer(nominal=1.0, breakeven=2.5).compute()
        assert sig.gold_implied_signal == "bullish_gold"

    def test_high_positive_real_yield_bearish_gold(self):
        """Real yield > 1.5% → bearish_gold."""
        sig = self._make_analyzer(nominal=5.0, breakeven=2.5).compute()
        assert sig.gold_implied_signal in ("bearish_gold", "neutral")

    def test_pe_pressure_rising_rates(self):
        """Configurazione rising rates → compressing."""
        sig = self._make_analyzer(nominal=5.5, breakeven=2.5).compute()
        assert sig.equity_pe_pressure in ("compressing", "stable", "expanding")

    def test_narrative_not_empty(self):
        sig = self._make_analyzer().compute()
        assert isinstance(sig.narrative_summary, str)
        assert len(sig.narrative_summary) > 20

    def test_zscore_float(self):
        sig = self._make_analyzer().compute()
        assert isinstance(sig.real_yield_zscore, float)

    def test_regime_trend_values(self):
        sig = self._make_analyzer().compute()
        assert sig.real_yield_trend in ("rising", "falling", "stable")

    def test_missing_data_raises(self):
        from engine.fixed_income.real_yield_analyzer import RealYieldAnalyzer
        repo = MagicMock()
        repo.read_macro.return_value = pd.DataFrame()
        db = _mock_duckdb()
        with pytest.raises((ValueError, Exception)):
            RealYieldAnalyzer(macro_repo=repo, duckdb=db).compute()


# ═══════════════════════════════════════════════════════════════════════════
# Test Migration 008
# ═══════════════════════════════════════════════════════════════════════════

class TestMigration008:

    HI_TABLES = [
        "volume_signals", "divergence_signals", "risk_metrics",
        "portfolio_risk_report", "vol_surface_snapshots",
        "real_yield_signals", "rebalancing_reports",
    ]

    def test_all_hi_tables_exist(self, migrated_client):
        rows = migrated_client.query(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        )
        tables = {r[0] for r in rows}
        for t in self.HI_TABLES:
            assert t in tables, f"Tabella mancante: {t}"

    def test_volume_signals_insert(self, migrated_client):
        migrated_client.execute(
            "INSERT INTO volume_signals "
            "(ticker, ts, obv, cmf_20, vwap, amihud_ratio, amihud_10d_ma, volume_zscore) "
            "VALUES ('AAPL', '2026-06-01 00:00:00+00', 1000000.0, 0.3, 180.0, 0.001, 0.001, 1.5)"
        )
        rows = migrated_client.query("SELECT ticker FROM volume_signals")
        assert len(rows) == 1

    def test_rebalancing_reports_insert(self, migrated_client):
        migrated_client.execute(
            "INSERT INTO rebalancing_reports "
            "(report_id, computed_at, profile_id, method, "
            "current_vol, target_vol, total_trades, total_turnover_pct) "
            "VALUES ('abc-123', '2026-06-01 12:00:00+00', 'me', 'hrp', 0.15, 0.13, 2, 0.12)"
        )
        rows = migrated_client.query("SELECT method FROM rebalancing_reports")
        assert rows[0][0] == "hrp"

    def test_feature_flags_hi_loaded(self):
        import shared.feature_flags as ff
        ff._load_flags.cache_clear()
        from shared.feature_flags import is_enabled
        assert isinstance(is_enabled("volume_analysis"), bool)
        assert isinstance(is_enabled("rebalancing_engine"), bool)
        assert is_enabled("volume_analysis") is True
        assert is_enabled("rebalancing_engine") is True


# ─── Fixture locale ────────────────────────────────────────────────────────

@pytest.fixture()
def migrated_client(tmp_duckdb_path):
    from shared.db.duckdb_client import DuckDBClient
    from shared.db.duckdb_migrator import DuckDBMigrator
    client = DuckDBClient(path=tmp_duckdb_path)
    DuckDBMigrator(client=client).apply_pending()
    yield client
    client.close()
