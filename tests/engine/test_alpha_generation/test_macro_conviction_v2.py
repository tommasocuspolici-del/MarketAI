"""Test suite — Roadmap Unificata Settimana 3: MacroConviction.

Coverage target: ≥ 85% su engine/alpha_generation/
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

from engine.alpha_generation.schemas import (
    ClaimsRegime, CreditStressLevel, CurveRegime,
    MacroConvictionResult, ClaimsInflationOutput,
    YieldCurveOutput, CreditStressOutput,
)
from engine.alpha_generation.claims_cross_analyzer import ClaimsInflationCrossAnalyzer
from engine.alpha_generation.yield_curve_analyzer import YieldCurveAnalyzer
from engine.alpha_generation.credit_stress_analyzer import CreditStressAnalyzer
from engine.alpha_generation.macro_conviction import (
    MacroConvictionCalculator,
    _inflation_to_score,
    _weighted_aggregate,
)


# ─── Helpers per creare DataFrame di test ────────────────────────────────────

def _make_df(values: list[float], freq: str = "W") -> pd.DataFrame:
    """DataFrame con colonne ts + value per i test."""
    n = len(values)
    dates = pd.date_range("2024-01-01", periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"ts": dates, "value": values})


def _make_icsa(latest: float, n: int = 60, yoy_pct: float = 0.0) -> pd.DataFrame:
    """DataFrame ICSA con 60 osservazioni e variazione YoY specificata."""
    prev_year = latest / (1 + yoy_pct) if (1 + yoy_pct) != 0 else latest
    vals = np.linspace(prev_year, latest, n)
    return _make_df(vals.tolist())


def _make_cpi(yoy: float, n: int = 24) -> pd.DataFrame:
    return _make_df([yoy] * n, freq="MS")


def _make_spread(val: float, n: int = 12) -> pd.DataFrame:
    return _make_df([val] * n, freq="D")


# ═══════════════════════════════════════════════════════════════════════════
# ClaimsInflationCrossAnalyzer
# ═══════════════════════════════════════════════════════════════════════════

class TestClaimsInflationCrossAnalyzer:

    def setup_method(self):
        self.analyzer = ClaimsInflationCrossAnalyzer()

    def test_goldilocks_regime(self):
        """Claims basse + CPI < 3.5% → GOLDILOCKS."""
        out = self.analyzer.analyze(
            icsa_df=_make_icsa(220_000, n=60, yoy_pct=-0.02),
            cpi_df=_make_cpi(2.5),
        )
        assert out.regime == ClaimsRegime.GOLDILOCKS
        assert out.goldilocks_signal is True
        assert out.regime_score > 0

    def test_stagflation_regime(self):
        """Claims YoY > 10% + CPI > 3% → STAGFLATION."""
        out = self.analyzer.analyze(
            icsa_df=_make_icsa(380_000, n=60, yoy_pct=0.15),
            cpi_df=_make_cpi(4.2),
        )
        assert out.regime == ClaimsRegime.STAGFLATION
        assert out.stagflation_signal is True
        assert out.regime_score == pytest.approx(-1.0)

    def test_overheating_regime(self):
        """Claims < 250k + CPI > 4% → OVERHEATING."""
        out = self.analyzer.analyze(
            icsa_df=_make_icsa(230_000, n=60, yoy_pct=-0.05),
            cpi_df=_make_cpi(4.8),
        )
        assert out.regime == ClaimsRegime.OVERHEATING
        assert out.overheating_signal is True
        assert out.regime_score < 0

    def test_recession_regime(self):
        """Claims YoY > 20% + CPI < 2.5% → RECESSION."""
        out = self.analyzer.analyze(
            icsa_df=_make_icsa(450_000, n=60, yoy_pct=0.25),
            cpi_df=_make_cpi(1.8),
        )
        assert out.regime == ClaimsRegime.RECESSION
        assert out.recession_watch is True
        assert out.regime_score < 0

    def test_neutral_regime(self):
        """Claims moderate + CPI moderato → NEUTRAL."""
        out = self.analyzer.analyze(
            icsa_df=_make_icsa(310_000, n=60, yoy_pct=0.03),
            cpi_df=_make_cpi(2.8),
        )
        assert out.regime == ClaimsRegime.NEUTRAL
        assert out.stagflation_signal is False
        assert out.goldilocks_signal is False

    def test_insufficient_data_returns_neutral(self):
        """Con < 4 osservazioni ICSA → NEUTRAL senza crash."""
        out = self.analyzer.analyze(
            icsa_df=_make_icsa(250_000, n=2),
            cpi_df=_make_cpi(3.0),
        )
        assert out.regime == ClaimsRegime.NEUTRAL

    def test_empty_cpi_does_not_crash(self):
        """DataFrame CPI vuoto → analisi robusta."""
        out = self.analyzer.analyze(
            icsa_df=_make_icsa(220_000, n=60),
            cpi_df=pd.DataFrame(),
        )
        assert out.cpi_yoy is None
        assert isinstance(out.regime, ClaimsRegime)

    def test_score_always_in_range(self):
        """regime_score deve sempre essere in [-1, +1]."""
        for yoy_pct in [-0.3, 0.0, 0.15, 0.40]:
            for cpi in [0.5, 2.0, 3.5, 6.0]:
                out = self.analyzer.analyze(
                    icsa_df=_make_icsa(300_000, n=60, yoy_pct=yoy_pct),
                    cpi_df=_make_cpi(cpi),
                )
                assert -1.0 <= out.regime_score <= 1.0, \
                    f"Score {out.regime_score} out of range for yoy={yoy_pct} cpi={cpi}"

    def test_goldilocks_high_score_on_low_cpi(self):
        """Goldilocks con CPI < 2.5% → score più alto (0.8)."""
        out = self.analyzer.analyze(
            icsa_df=_make_icsa(210_000, n=60, yoy_pct=-0.05),
            cpi_df=_make_cpi(2.2),
        )
        assert out.regime == ClaimsRegime.GOLDILOCKS
        assert out.regime_score >= 0.7

    def test_ccsa_optional_parameter(self):
        """CCSA opzionale non causa errori."""
        out = self.analyzer.analyze(
            icsa_df=_make_icsa(220_000, n=60),
            cpi_df=_make_cpi(2.5),
            ccsa_df=_make_icsa(1_800_000, n=60),
        )
        assert out.regime is not None

    def test_output_fields_complete(self):
        """Output ha tutti i campi richiesti dalla Roadmap."""
        out = self.analyzer.analyze(
            icsa_df=_make_icsa(250_000, n=60),
            cpi_df=_make_cpi(2.8),
        )
        assert isinstance(out, ClaimsInflationOutput)
        assert hasattr(out, "icsa_4wk_ma")
        assert hasattr(out, "icsa_yoy_pct")
        assert hasattr(out, "cpi_yoy")
        assert out.icsa_4wk_ma > 0


# ═══════════════════════════════════════════════════════════════════════════
# YieldCurveAnalyzer
# ═══════════════════════════════════════════════════════════════════════════

class TestYieldCurveAnalyzer:

    def setup_method(self):
        self.analyzer = YieldCurveAnalyzer()

    def test_estrella_mishkin_math(self):
        """Verifica formula Estrella-Mishkin con valori noti."""
        # Con spread = 0: P = Φ(-0.6022) ≈ 0.274
        prob = YieldCurveAnalyzer.recession_probability(0.0)
        assert prob is not None
        assert abs(prob - 0.274) < 0.01

    def test_estrella_mishkin_deep_inversion(self):
        """Spread molto negativo → P(recessione) molto alta."""
        prob = YieldCurveAnalyzer.recession_probability(-2.0)
        assert prob is not None
        assert prob > 0.60  # Estrella-Mishkin: spread=-2 → Φ(-0.6022+(-0.5517×-2))≈0.69

    def test_estrella_mishkin_steep_curve(self):
        """Spread molto positivo → P(recessione) bassa."""
        prob = YieldCurveAnalyzer.recession_probability(2.5)
        assert prob is not None
        assert prob < 0.10

    def test_estrella_mishkin_none_on_missing(self):
        """None in input → None in output."""
        prob = YieldCurveAnalyzer.recession_probability(None)
        assert prob is None

    def test_inverted_curve_regime(self):
        """Spread 10Y-2Y < -0.5 → INVERTED."""
        out = self.analyzer.analyze(
            dgs10_df=_make_spread(4.0),
            dgs2_df=_make_spread(4.8),
            t10y2y_df=_make_spread(-0.8),
        )
        assert out.curve_regime == CurveRegime.INVERTED
        assert out.inversion_detected is True
        assert out.regime_score < 0

    def test_flat_curve_regime(self):
        """Spread 10Y-2Y tra -0.5 e 0 → FLAT."""
        out = self.analyzer.analyze(
            dgs10_df=_make_spread(4.5),
            dgs2_df=_make_spread(4.7),
            t10y2y_df=_make_spread(-0.2),
        )
        assert out.curve_regime == CurveRegime.FLAT

    def test_normal_curve_regime(self):
        """Spread 0-1.5 → NORMAL."""
        out = self.analyzer.analyze(
            dgs10_df=_make_spread(4.5),
            dgs2_df=_make_spread(4.0),
            t10y2y_df=_make_spread(0.5),
        )
        assert out.curve_regime == CurveRegime.NORMAL

    def test_steep_curve_regime(self):
        """Spread > 1.5 → STEEP."""
        out = self.analyzer.analyze(
            dgs10_df=_make_spread(5.0),
            dgs2_df=_make_spread(3.0),
            t10y2y_df=_make_spread(2.0),
        )
        assert out.curve_regime == CurveRegime.STEEP
        assert out.regime_score > 0

    def test_score_always_in_range(self):
        """regime_score sempre in [-1, +1]."""
        for spread in [-2.0, -0.8, -0.2, 0.5, 1.0, 2.5]:
            out = self.analyzer.analyze(
                dgs10_df=_make_spread(4.0),
                dgs2_df=_make_spread(4.0 - spread),
                t10y2y_df=_make_spread(spread),
                t10y3m_df=_make_spread(spread - 0.5),
            )
            assert -1.0 <= out.regime_score <= 1.0, \
                f"Score {out.regime_score} OOB for spread={spread}"

    def test_calculates_spread_from_raw_series(self):
        """Se t10y2y_df è None, calcola spread da DGS10 - DGS2."""
        out = self.analyzer.analyze(
            dgs10_df=_make_spread(4.5),
            dgs2_df=_make_spread(4.8),
        )
        assert out.spread_10y_2y is not None
        assert abs(out.spread_10y_2y - (-0.3)) < 0.01

    def test_empty_dataframes_do_not_crash(self):
        """DataFrame vuoti → output robusto senza crash."""
        out = self.analyzer.analyze(
            dgs10_df=pd.DataFrame(),
            dgs2_df=pd.DataFrame(),
        )
        assert isinstance(out, YieldCurveOutput)
        assert out.spread_10y_2y is None

    def test_inversion_detected_flag(self):
        """inversion_detected True solo quando spread_10y_2y < 0."""
        out_inv = self.analyzer.analyze(
            dgs10_df=_make_spread(4.0),
            dgs2_df=_make_spread(4.0),
            t10y2y_df=_make_spread(-0.1),
        )
        out_pos = self.analyzer.analyze(
            dgs10_df=_make_spread(4.5),
            dgs2_df=_make_spread(4.0),
            t10y2y_df=_make_spread(0.5),
        )
        assert out_inv.inversion_detected is True
        assert out_pos.inversion_detected is False


# ═══════════════════════════════════════════════════════════════════════════
# CreditStressAnalyzer
# ═══════════════════════════════════════════════════════════════════════════

class TestCreditStressAnalyzer:

    def setup_method(self):
        self.analyzer = CreditStressAnalyzer()

    def test_low_stress_level(self):
        """HY OAS < 350 → LOW."""
        out = self.analyzer.analyze(hy_oas_df=_make_spread(300.0))
        assert out.stress_level == CreditStressLevel.LOW
        assert out.stress_score > 0

    def test_moderate_stress_level(self):
        """350 ≤ HY OAS < 500 → MODERATE."""
        out = self.analyzer.analyze(hy_oas_df=_make_spread(420.0))
        assert out.stress_level == CreditStressLevel.MODERATE
        assert out.stress_score == pytest.approx(0.0)

    def test_elevated_stress_level(self):
        """500 ≤ HY OAS < 700 → ELEVATED."""
        out = self.analyzer.analyze(hy_oas_df=_make_spread(600.0))
        assert out.stress_level == CreditStressLevel.ELEVATED
        assert out.stress_score < 0

    def test_crisis_stress_level(self):
        """HY OAS ≥ 700 → CRISIS."""
        out = self.analyzer.analyze(hy_oas_df=_make_spread(850.0))
        assert out.stress_level == CreditStressLevel.CRISIS
        assert out.stress_score == pytest.approx(-1.0)

    def test_all_four_stress_levels(self):
        """Tutti e 4 i livelli di stress verificati."""
        for oas, expected in [(300, CreditStressLevel.LOW), (420, CreditStressLevel.MODERATE),
                               (600, CreditStressLevel.ELEVATED), (850, CreditStressLevel.CRISIS)]:
            out = self.analyzer.analyze(hy_oas_df=_make_spread(float(oas)))
            assert out.stress_level == expected

    def test_ted_override_elevated(self):
        """TED spread > 50 bps forza livello minimo ELEVATED."""
        # HY OAS basso ma TED elevato → override
        out = self.analyzer.analyze(
            hy_oas_df=_make_spread(300.0),
            ted_df=_make_spread(75.0),
        )
        assert out.stress_level in (CreditStressLevel.ELEVATED, CreditStressLevel.CRISIS)

    def test_nfci_override(self):
        """NFCI > 1.0 forza livello ELEVATED+."""
        out = self.analyzer.analyze(
            hy_oas_df=_make_spread(300.0),
            nfci_df=_make_spread(1.5),
        )
        assert out.stress_level in (CreditStressLevel.ELEVATED, CreditStressLevel.CRISIS)

    def test_hy_ig_ratio_computed(self):
        """hy_ig_ratio = HY OAS / IG OAS."""
        out = self.analyzer.analyze(
            hy_oas_df=_make_spread(450.0),
            ig_oas_df=_make_spread(100.0),
        )
        assert out.hy_ig_ratio is not None
        assert abs(out.hy_ig_ratio - 4.5) < 0.01

    def test_empty_hy_oas_returns_moderate(self):
        """HY OAS vuoto → fallback MODERATE conservativo."""
        out = self.analyzer.analyze(hy_oas_df=pd.DataFrame())
        assert out.stress_level == CreditStressLevel.MODERATE

    def test_score_always_in_range(self):
        """stress_score sempre in [-1, +1]."""
        for oas in [200, 350, 500, 700, 1200]:
            out = self.analyzer.analyze(hy_oas_df=_make_spread(float(oas)))
            assert -1.0 <= out.stress_score <= 1.0

    def test_output_fields_present(self):
        """Output ha tutti i campi richiesti."""
        out = self.analyzer.analyze(
            hy_oas_df=_make_spread(400.0),
            ig_oas_df=_make_spread(100.0),
            ted_df=_make_spread(20.0),
            nfci_df=_make_spread(-0.3),
        )
        assert isinstance(out, CreditStressOutput)
        assert out.hy_oas is not None
        assert out.ig_oas is not None
        assert out.ted_spread is not None
        assert out.nfci is not None


# ═══════════════════════════════════════════════════════════════════════════
# MacroConvictionCalculator
# ═══════════════════════════════════════════════════════════════════════════

def _build_mock_repo(series_map: dict[str, list[float]]) -> MagicMock:
    """Crea un MacroRepository mock con read_macro() configurato."""
    repo = MagicMock()

    def _read_macro(series_id: str, start=None, end=None) -> pd.DataFrame:
        vals = series_map.get(series_id, [])
        if not vals:
            return pd.DataFrame()
        n = len(vals)
        dates = pd.date_range("2024-01-01", periods=n, freq="MS", tz="UTC")
        return pd.DataFrame({"ts": dates, "value": vals})

    repo.read_macro.side_effect = _read_macro
    return repo


def _build_full_repo() -> MagicMock:
    """Mock repository con tutte le 15 serie in condizioni 'goldilocks'."""
    return _build_mock_repo({
        # Labour
        "ICSA":   [220_000] * 60,
        "CCSA":   [1_750_000] * 60,
        "PAYEMS": [150_000, 160_000, 170_000, 175_000],
        # Inflation
        "CPIAUCSL": [2.3] * 24,
        "CPILFESL": [2.1] * 24,
        "T10YIE":   [2.2] * 24,
        # Rates
        "DGS10":    [4.5] * 24,
        "DGS2":     [4.0] * 24,
        "DGS3MO":   [4.2] * 24,
        "T10Y3M":   [0.3] * 24,
        "FEDFUNDS": [5.25] * 24,
        # Credit
        "BAMLH0A0HYM2": [350.0] * 24,
        "BAMLC0A0CM":   [100.0] * 24,
        "TEDRATE":      [20.0] * 24,
        "NFCI":         [-0.3] * 24,
        # Growth
        "INDPRO":  list(range(95, 113, 1)),
    })


class TestMacroConvictionCalculator:

    def test_compute_returns_result(self):
        """compute() ritorna MacroConvictionResult valido."""
        calc = MacroConvictionCalculator(macro_repo=_build_full_repo())
        result = calc.compute()
        assert isinstance(result, MacroConvictionResult)

    def test_macro_score_in_range(self):
        """macro_score sempre in [-1, +1]."""
        calc = MacroConvictionCalculator(macro_repo=_build_full_repo())
        result = calc.compute()
        assert -1.0 <= result.macro_score <= 1.0

    def test_goldilocks_positive_score(self):
        """Condizioni Goldilocks → macro_score > 0."""
        calc = MacroConvictionCalculator(macro_repo=_build_full_repo())
        result = calc.compute()
        assert result.macro_score > 0, f"Atteso > 0, ottenuto {result.macro_score}"

    def test_stagflation_negative_score(self):
        """Stagflazione → macro_score < 0."""
        repo = _build_mock_repo({
            "ICSA":   [200_000] + [380_000] * 59,   # claims in forte salita
            "CCSA":   [2_500_000] * 60,
            "PAYEMS": [200_000, 190_000, 185_000, 180_000],
            "CPIAUCSL": [5.2] * 24,
            "CPILFESL": [4.8] * 24,
            "T10YIE":   [3.2] * 24,
            "DGS10": [5.5] * 24,
            "DGS2":  [5.8] * 24,
            "T10Y2Y": [-0.3] * 24,
            "T10Y3M": [-0.5] * 24,
            "BAMLH0A0HYM2": [700.0] * 24,
            "TEDRATE": [80.0] * 24,
            "NFCI": [1.2] * 24,
            "INDPRO": list(range(110, 92, -1)),
        })
        calc = MacroConvictionCalculator(macro_repo=repo)
        result = calc.compute()
        assert result.macro_score < 0, f"Atteso < 0, ottenuto {result.macro_score}"

    def test_series_available_count(self):
        """series_available conta correttamente le serie presenti."""
        calc = MacroConvictionCalculator(macro_repo=_build_full_repo())
        result = calc.compute()
        assert result.series_available >= 10

    def test_empty_db_returns_low_confidence(self):
        """DB vuoto → confidence LOW."""
        repo = _build_mock_repo({})
        calc = MacroConvictionCalculator(macro_repo=repo)
        result = calc.compute()
        assert result.confidence == "LOW"
        assert result.series_available == 0

    def test_partial_db_medium_confidence(self):
        """6-9 serie → confidence MEDIUM."""
        repo = _build_mock_repo({
            "ICSA": [220_000] * 60,
            "CPIAUCSL": [2.3] * 24,
            "DGS10": [4.5] * 24,
            "DGS2": [4.0] * 24,
            "BAMLH0A0HYM2": [350.0] * 24,
            "INDPRO": list(range(95, 115)),
            "T10Y3M": [0.3] * 24,
        })
        calc = MacroConvictionCalculator(macro_repo=repo)
        result = calc.compute()
        assert result.confidence in ("MEDIUM", "HIGH")

    def test_full_db_high_confidence(self):
        """≥ 10 serie → confidence HIGH."""
        calc = MacroConvictionCalculator(macro_repo=_build_full_repo())
        result = calc.compute()
        assert result.confidence == "HIGH"

    def test_sub_outputs_populated(self):
        """claims_output, yield_output, credit_output sempre presenti."""
        calc = MacroConvictionCalculator(macro_repo=_build_full_repo())
        result = calc.compute()
        assert isinstance(result.claims_output, ClaimsInflationOutput)
        assert isinstance(result.yield_output, YieldCurveOutput)
        assert isinstance(result.credit_output, CreditStressOutput)

    def test_category_scores_in_range(self):
        """Tutti i 5 category scores in [-1, +1]."""
        calc = MacroConvictionCalculator(macro_repo=_build_full_repo())
        result = calc.compute()
        for attr in ["labour_score", "inflation_score", "rates_score",
                     "credit_score", "growth_score"]:
            val = getattr(result, attr)
            assert -1.0 <= val <= 1.0, f"{attr} = {val} OOB"

    def test_weight_breakdown_sums_to_one(self):
        """I pesi effettivi sommano a 1.0."""
        calc = MacroConvictionCalculator(macro_repo=_build_full_repo())
        result = calc.compute()
        total = sum(result.weight_breakdown.values())
        assert abs(total - 1.0) < 1e-6

    def test_computed_at_is_utc(self):
        """computed_at è timezone-aware UTC."""
        calc = MacroConvictionCalculator(macro_repo=_build_full_repo())
        result = calc.compute()
        assert result.computed_at.tzinfo is not None


# ═══════════════════════════════════════════════════════════════════════════
# Test funzioni pure
# ═══════════════════════════════════════════════════════════════════════════

class TestPureFunctions:

    def test_inflation_to_score_deflation(self):
        assert _inflation_to_score(0.2) == pytest.approx(-0.4)

    def test_inflation_to_score_sub_target(self):
        assert _inflation_to_score(1.0) == pytest.approx(-0.1)

    def test_inflation_to_score_on_target(self):
        assert _inflation_to_score(2.0) == pytest.approx(0.4)

    def test_inflation_to_score_above_target(self):
        assert _inflation_to_score(3.0) == pytest.approx(-0.2)

    def test_inflation_to_score_high(self):
        assert _inflation_to_score(4.0) == pytest.approx(-0.6)

    def test_inflation_to_score_very_high(self):
        assert _inflation_to_score(6.0) == pytest.approx(-1.0)

    def test_weighted_aggregate_equal_scores(self):
        """Score uguali → macro_score uguale a quei valori."""
        scores = {"labour": 0.5, "inflation": 0.5, "rates": 0.5, "credit": 0.5, "growth": 0.5}
        result, weights = _weighted_aggregate(scores)
        assert abs(result - 0.5) < 1e-6

    def test_weighted_aggregate_mixed_scores(self):
        """Score misti → media pesata corretta."""
        scores = {"labour": 1.0, "inflation": -1.0, "rates": 0.0, "credit": 0.0, "growth": 0.0}
        result, weights = _weighted_aggregate(scores)
        # labour (0.25) * 1 + inflation (0.20) * -1 = 0.05 / 1.0 = 0.05
        assert abs(result - 0.05) < 1e-4

    def test_weighted_aggregate_empty(self):
        """Scores vuoto → 0.0 senza crash."""
        result, _ = _weighted_aggregate({})
        assert result == 0.0


# ═══════════════════════════════════════════════════════════════════════════
# Benchmark
# ═══════════════════════════════════════════════════════════════════════════

class TestBenchmark:

    def test_compute_under_300ms(self, benchmark):
        """compute() con 15 serie deve completare in < 300ms."""
        calc = MacroConvictionCalculator(macro_repo=_build_full_repo())
        result = benchmark(calc.compute)
        assert -1.0 <= result.macro_score <= 1.0

    def test_claims_analyzer_under_10ms(self, benchmark):
        """ClaimsInflationCrossAnalyzer.analyze() < 10ms."""
        analyzer = ClaimsInflationCrossAnalyzer()
        icsa_df = _make_icsa(220_000, n=60)
        cpi_df  = _make_cpi(2.5)
        result = benchmark(analyzer.analyze, icsa_df=icsa_df, cpi_df=cpi_df)
        assert isinstance(result, ClaimsInflationOutput)
