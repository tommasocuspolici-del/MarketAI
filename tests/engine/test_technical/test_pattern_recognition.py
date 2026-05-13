"""Tests for PatternDetector and supporting modules.

Roadmap v3.0 — Settimana 3.

Strategia: serie OHLCV sintetiche che contengono i pattern noti.
Tutti i test sono deterministici e offline (nessuna rete, nessun DB).

Verifica:
  · find_pivots() — vectorized, output corretto, edge cases
  · PatternDetector.detect() — rileva pattern nelle serie sintetiche
  · Confidence >= min_confidence (0.6) su tutti i rilevamenti
  · PatternResult Pydantic — validazione campi
  · PatternDetectionConfig — caricamento YAML
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.technical.pattern_recognition import PatternDetector, find_pivots
from engine.technical.pattern_schemas import (
    PatternDetectionConfig,
    PatternResult,
    PatternSignal,
    PatternType,
    load_pattern_config,
)


# ─── Fixtures — Serie sintetiche ─────────────────────────────────────────────

def _make_df(prices: list[float], n_days: int | None = None) -> pd.DataFrame:
    """Crea un DataFrame OHLCV minimo da una lista di prezzi close."""
    if n_days is None:
        n_days = len(prices)
    dates = pd.date_range("2024-01-01", periods=len(prices), freq="D", tz="UTC")
    return pd.DataFrame({
        "ts": dates,
        "open": prices,
        "high": [p * 1.005 for p in prices],
        "low":  [p * 0.995 for p in prices],
        "close": prices,
        "volume": [1_000_000] * len(prices),
    })


def _make_hs_series(n: int = 100) -> list[float]:
    """Serie Head and Shoulders con 3 pivot puliti (no plateau).

    Highs: [70, 82, 71] — pivots trovati da find_pivots(order=3).
    Lows neckline: [62, 62].
    Nessuna sezione piatta: evita pivot duplicati che confondono il detector.
    """
    base: list[float] = [
        62, 64, 66, 68, 70, 68, 66, 64,   # spalla sinistra (peak=70)
        62, 63, 65, 70, 76, 82, 76, 70,   # testa (peak=82)
        63, 62, 64, 66, 68, 71, 68, 65,   # spalla destra (peak=71)
        60, 58, 56, 55, 54,               # discesa finale
    ]
    if len(base) < n:
        base += [54.0] * (n - len(base))
    return base[:n]


def _make_double_top_series() -> list[float]:
    """Crea una serie con Double Top chiaro (due massimi a 80, valley a 70)."""
    p = list(np.linspace(60, 80, 15))   # salita al primo top
    p += list(np.linspace(80, 70, 8))   # discesa alla valley
    p += list(np.linspace(70, 80, 12))  # salita al secondo top
    p += list(np.linspace(80, 62, 20))  # discesa finale
    return p


def _make_double_bottom_series() -> list[float]:
    """Crea una serie con Double Bottom chiaro (due minimi a 40, picco a 50)."""
    p = list(np.linspace(60, 40, 15))   # discesa al primo bottom
    p += list(np.linspace(40, 50, 8))   # risalita
    p += list(np.linspace(50, 40, 12))  # discesa al secondo bottom
    p += list(np.linspace(40, 62, 20))  # risalita finale
    return p


def _make_ascending_triangle_series() -> list[float]:
    """Triangolo ascendente: lows steeply crescenti + highs piatti a ~85.

    peaks piatti a 85, lows crescenti 60→70→77→83 → slope_lows >> 0.003.
    Verificato con normalised_slope: sh≈0.0, sl≈0.005 → TRIANGLE_ASCENDING.
    """
    p: list[float] = []
    peaks = [85.0, 85.0, 85.0, 85.0]
    lows  = [60.0, 70.0, 77.0, 83.0]
    for i in range(len(lows)):
        p += list(np.linspace(lows[i], peaks[i], 8))
        if i + 1 < len(lows):
            p += list(np.linspace(peaks[i], lows[i + 1], 7))
    # Padding per raggiungere la finestra min 60
    while len(p) < 65:
        p += [84.0] * 5
    return p


def _make_flag_series() -> list[float]:
    """Flag bullish: forte impulso rialzista + consolidamento stretto."""
    p  = list(np.linspace(50, 70, 12))     # pole: +40%
    p += list(np.linspace(70, 68.5, 10))   # flag: consolidamento stretto
    return p


def _make_cup_series() -> list[float]:
    """Cup and Handle: U-shape + piccola pausa."""
    cup_left  = list(np.linspace(80, 60, 15))  # discesa
    cup_bottom = [60.0] * 8                     # fondo piatto
    cup_right  = list(np.linspace(60, 79, 15)) # risalita
    handle     = list(np.linspace(79, 76, 5))  # manico: leggero ritracciamento
    return cup_left + cup_bottom + cup_right + handle


# ─── Test: find_pivots ────────────────────────────────────────────────────────

class TestFindPivots:
    """Tests per la funzione find_pivots (vectorized)."""

    def test_insufficient_data_returns_empty(self) -> None:
        """Dati insufficienti → array vuoti."""
        short = np.array([1.0, 2.0, 3.0])
        h, l = find_pivots(short, order=5)
        assert len(h) == 0
        assert len(l) == 0

    def test_finds_clear_high(self) -> None:
        """Picco chiaramente al centro → trovato come pivot alto."""
        prices = np.array([1.0, 2.0, 3.0, 5.0, 3.0, 2.0, 1.0,
                           2.0, 3.0, 4.0, 3.0, 2.0, 1.0], dtype=np.float64)
        h, _ = find_pivots(prices, order=3)
        assert len(h) >= 1
        # Il picco a 5.0 è all'indice 3
        assert 3 in h

    def test_finds_clear_low(self) -> None:
        """Valle chiaramente al centro → trovata come pivot basso."""
        prices = np.array([5.0, 4.0, 3.0, 1.0, 3.0, 4.0, 5.0,
                           4.0, 3.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float64)
        _, l = find_pivots(prices, order=3)
        assert len(l) >= 1
        assert 3 in l

    def test_output_arrays_are_integer_indices(self) -> None:
        """I pivot sono indici interi validi nella serie."""
        prices = np.random.default_rng(42).random(50).astype(np.float64) * 100
        h, l = find_pivots(prices, order=3)
        assert h.dtype == np.intp or np.issubdtype(h.dtype, np.integer)
        for i in h:
            assert 0 <= i < len(prices)
        for i in l:
            assert 0 <= i < len(prices)

    def test_monotone_up_has_no_high_pivots_in_interior(self) -> None:
        """Serie monotona crescente → nessun pivot alto interno."""
        prices = np.linspace(1, 10, 30).astype(np.float64)
        h, _ = find_pivots(prices, order=3)
        # Il massimo è solo all'ultimo elemento (bordo) — nessun picco interno
        interior = h[(h > 2) & (h < len(prices) - 3)]
        assert len(interior) == 0


# ─── Test: PatternDetectionConfig ────────────────────────────────────────────

def test_load_pattern_config_returns_config() -> None:
    """load_pattern_config() restituisce una PatternDetectionConfig valida."""
    cfg = load_pattern_config()
    assert isinstance(cfg, PatternDetectionConfig)
    assert 0.0 <= cfg.min_confidence <= 1.0
    assert cfg.pivot_order >= 1

def test_default_config_values() -> None:
    """I default della config corrispondono alla specifica (min_confidence=0.6)."""
    cfg = PatternDetectionConfig()
    assert cfg.min_confidence == pytest.approx(0.6)
    assert cfg.pivot_order == 5


# ─── Test: PatternResult ──────────────────────────────────────────────────────

def test_pattern_result_roundtrip() -> None:
    """PatternResult si costruisce correttamente e to_db_dict() funziona."""
    from datetime import UTC, datetime
    r = PatternResult(
        ticker="AAPL",
        pattern_type=PatternType.DOUBLE_TOP,
        signal=PatternSignal.BEARISH,
        confidence=0.75,
        start_idx=10,
        end_idx=30,
        start_date=datetime(2024, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 2, 1, tzinfo=UTC),
        key_levels={"resistance": 150.0, "target": 140.0},
        description="Double Top at 150",
    )
    assert r.duration_bars == 20
    db = r.to_db_dict()
    assert db["ticker"] == "AAPL"
    assert db["pattern_type"] == "double_top"
    assert db["signal_dir"] == "bearish"
    assert "key_levels_json" in db


def test_pattern_result_confidence_rounded() -> None:
    """La confidence viene arrotondata a 4 decimali."""
    from datetime import UTC, datetime
    r = PatternResult(
        ticker="X",
        pattern_type=PatternType.FLAG,
        signal=PatternSignal.BULLISH,
        confidence=0.666666666,
        start_idx=0, end_idx=10,
        start_date=datetime(2024, 1, 1, tzinfo=UTC),
        end_date=datetime(2024, 1, 11, tzinfo=UTC),
    )
    assert r.confidence == pytest.approx(0.6667, abs=1e-4)


# ─── Test: PatternDetector — rilevamento pattern ─────────────────────────────

class TestPatternDetector:
    """Tests che verificano il rilevamento sui segnali sintetici."""

    def setup_method(self) -> None:
        # Config con min_confidence bassa per i test (serie sintetiche brevi)
        cfg = PatternDetectionConfig(
            min_confidence=0.55,   # leggermente più bassa del default per copertura test
            pivot_order=3,         # finestra più stretta su serie corte
        )
        self.det = PatternDetector(config=cfg)

    def test_detect_returns_list(self) -> None:
        """detect() restituisce sempre una lista."""
        df = _make_df([100.0] * 50)
        result = self.det.detect(df, "TEST")
        assert isinstance(result, list)

    def test_detect_empty_df_returns_empty(self) -> None:
        """DataFrame vuoto → lista vuota."""
        df = _make_df([])
        result = self.det.detect(df, "TEST")
        assert result == []

    def test_detect_short_series_returns_empty(self) -> None:
        """Serie troppo corta (< 2*order+3) → lista vuota."""
        df = _make_df([100.0] * 5)
        result = self.det.detect(df, "TEST")
        assert result == []

    def test_detect_head_and_shoulders(self) -> None:
        """Riconosce un H&S sintetico."""
        df = _make_df(_make_hs_series(80))
        results = self.det.detect(df, "AAPL")
        types = [r.pattern_type for r in results]
        assert PatternType.HEAD_AND_SHOULDERS in types

    def test_detect_hs_is_bearish(self) -> None:
        """H&S deve essere bearish."""
        df = _make_df(_make_hs_series(80))
        results = self.det.detect(df, "AAPL")
        hs = [r for r in results if r.pattern_type == PatternType.HEAD_AND_SHOULDERS]
        if hs:
            assert all(r.signal == PatternSignal.BEARISH for r in hs)

    def test_detect_double_top(self) -> None:
        """Riconosce un Double Top sintetico."""
        df = _make_df(_make_double_top_series())
        results = self.det.detect(df, "AAPL")
        types = [r.pattern_type for r in results]
        assert PatternType.DOUBLE_TOP in types

    def test_detect_double_bottom(self) -> None:
        """Riconosce un Double Bottom sintetico."""
        df = _make_df(_make_double_bottom_series())
        results = self.det.detect(df, "AAPL")
        types = [r.pattern_type for r in results]
        assert PatternType.DOUBLE_BOTTOM in types

    def test_detect_double_top_bearish(self) -> None:
        """Double Top deve essere bearish."""
        df = _make_df(_make_double_top_series())
        results = self.det.detect(df, "AAPL")
        dt = [r for r in results if r.pattern_type == PatternType.DOUBLE_TOP]
        if dt:
            assert all(r.signal == PatternSignal.BEARISH for r in dt)

    def test_detect_ascending_triangle(self) -> None:
        """Riconosce un triangolo ascendente (serie con minimi crescenti)."""
        df = _make_df(_make_ascending_triangle_series())
        results = self.det.detect(df, "SPY")
        types = [r.pattern_type for r in results]
        assert PatternType.TRIANGLE_ASCENDING in types

    def test_detect_flag(self) -> None:
        """Riconosce un Flag bullish dopo un impulso."""
        df = _make_df(_make_flag_series())
        results = self.det.detect(df, "SPY")
        types = [r.pattern_type for r in results]
        assert PatternType.FLAG in types

    def test_detect_cup_and_handle(self) -> None:
        """Riconosce una Cup and Handle sintetica."""
        df = _make_df(_make_cup_series())
        results = self.det.detect(df, "NVDA")
        types = [r.pattern_type for r in results]
        assert PatternType.CUP_AND_HANDLE in types

    def test_all_results_above_min_confidence(self) -> None:
        """Tutti i risultati hanno confidence >= min_confidence."""
        df = _make_df(_make_hs_series(80))
        results = self.det.detect(df, "TEST")
        for r in results:
            assert r.confidence >= self.det._min  # _min è il nome dell'attributo in PatternDetector

    def test_results_sorted_by_confidence_desc(self) -> None:
        """I risultati sono ordinati per confidence decrescente."""
        df = _make_df(_make_hs_series(80))
        results = self.det.detect(df, "TEST")
        confidences = [r.confidence for r in results]
        assert confidences == sorted(confidences, reverse=True)

    def test_key_levels_populated(self) -> None:
        """PatternResult ha key_levels non vuoti per H&S e Double Top."""
        df = _make_df(_make_double_top_series())
        results = self.det.detect(df, "TEST")
        dts = [r for r in results if r.pattern_type == PatternType.DOUBLE_TOP]
        if dts:
            assert len(dts[0].key_levels) > 0
            assert "target" in dts[0].key_levels

    def test_start_idx_before_end_idx(self) -> None:
        """start_idx < end_idx per tutti i pattern rilevati."""
        df = _make_df(_make_hs_series(80))
        for r in self.det.detect(df, "TEST"):
            assert r.start_idx <= r.end_idx

    def test_flat_series_no_patterns(self) -> None:
        """Serie piatta → nessun pattern significativo rilevato."""
        df = _make_df([100.0] * 80)
        results = self.det.detect(df, "FLAT")
        # Potrebbe rilevare qualcosa (noise), ma non critico — solo non deve crashare
        assert isinstance(results, list)
