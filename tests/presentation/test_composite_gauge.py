"""Tests per composite_gauge — build_composite_gauge_figure, build_breakdown_bar_figure,
score_to_action, score_to_color.

Roadmap v3.0 — Settimana 8.

Tutti i test sono offline: no Streamlit, no DuckDB. Testano la logica
di costruzione dei Plotly Figure usando mock del DesignTokens.

REGOLA 20: verifica che i colori usati nel gauge provengano SEMPRE da
DesignTokens e mai da valori hardcoded.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from presentation.ui.components.composite_gauge import (
    _BUY_THRESHOLD,
    _REDUCE_THRESHOLD,
    build_breakdown_bar_figure,
    build_composite_gauge_figure,
    score_to_action,
    score_to_color,
)


# ─── Mock DesignTokens ────────────────────────────────────────────────────────

def _make_tokens() -> MagicMock:
    """Crea un mock DesignTokens con valori di test coerenti."""
    tokens = MagicMock()
    tokens.colors.positive        = "#10B981"
    tokens.colors.negative        = "#EF4444"
    tokens.colors.warning         = "#F59E0B"
    tokens.colors.neutral         = "#6B7280"
    tokens.colors.text_primary    = "#F9FAFB"
    tokens.colors.text_secondary  = "#9CA3AF"
    tokens.plotly.template        = "plotly_dark"
    tokens.plotly.paper_bgcolor   = "rgba(0,0,0,0)"
    tokens.plotly.plot_bgcolor    = "rgba(0,0,0,0)"
    tokens.plotly.grid_color      = "#374151"
    tokens.plotly.font_color      = "#F9FAFB"
    tokens.plotly.font_family     = "Inter, sans-serif"
    return tokens


# ─── Test: score_to_action ────────────────────────────────────────────────────

class TestScoreToAction:
    """Tests per la mappatura score → azione."""

    def test_positive_above_threshold_is_buy(self) -> None:
        assert score_to_action(_BUY_THRESHOLD + 0.01) == "BUY"

    def test_negative_below_threshold_is_reduce(self) -> None:
        assert score_to_action(_REDUCE_THRESHOLD - 0.01) == "REDUCE"

    def test_neutral_is_hold(self) -> None:
        assert score_to_action(0.0) == "HOLD"

    def test_exactly_at_buy_threshold_is_buy(self) -> None:
        assert score_to_action(_BUY_THRESHOLD) == "BUY"

    def test_exactly_at_reduce_threshold_is_reduce(self) -> None:
        assert score_to_action(_REDUCE_THRESHOLD) == "REDUCE"

    def test_all_valid_actions_are_expected(self) -> None:
        """Tutti i possibili output sono uno dei 3 valori attesi."""
        for score in [-1.0, -0.5, -0.3, 0.0, 0.3, 0.5, 1.0]:
            action = score_to_action(score)
            assert action in ("BUY", "HOLD", "REDUCE"), f"Score {score} → '{action}'"


# ─── Test: score_to_color ─────────────────────────────────────────────────────

class TestScoreToColor:
    """Tests per la mappatura score → colore (REGOLA 20)."""

    def setup_method(self) -> None:
        self.tokens = _make_tokens()

    def test_positive_score_returns_positive_token(self) -> None:
        """Score positivo → tokens.colors.positive."""
        color = score_to_color(0.5, self.tokens)
        assert color == self.tokens.colors.positive

    def test_negative_score_returns_negative_token(self) -> None:
        """Score negativo → tokens.colors.negative."""
        color = score_to_color(-0.5, self.tokens)
        assert color == self.tokens.colors.negative

    def test_neutral_score_returns_warning_token(self) -> None:
        """Score neutro → tokens.colors.warning."""
        color = score_to_color(0.0, self.tokens)
        assert color == self.tokens.colors.warning

    def test_color_is_never_hardcoded_string(self) -> None:
        """Verifica che il colore sia sempre un token, non una stringa hardcoded.

        Cambiamo i valori dei token e verifichiamo che il risultato cambi.
        Se il colore fosse hardcoded, il test fallirebbe.
        """
        original_positive = self.tokens.colors.positive
        self.tokens.colors.positive = "#AABBCC"  # tipo: ignore
        color = score_to_color(0.5, self.tokens)
        assert color == "#AABBCC"
        # Ripristina
        self.tokens.colors.positive = original_positive

    def test_score_exactly_at_boundaries(self) -> None:
        """Score esattamente alle soglie — nessuna eccezione."""
        score_to_color(_BUY_THRESHOLD, self.tokens)
        score_to_color(_REDUCE_THRESHOLD, self.tokens)


# ─── Test: build_composite_gauge_figure ──────────────────────────────────────

class TestBuildCompositeGaugeFigure:
    """Tests per build_composite_gauge_figure()."""

    def setup_method(self) -> None:
        self.tokens = _make_tokens()

    def test_returns_plotly_figure(self) -> None:
        """La funzione ritorna un Plotly Figure."""
        import plotly.graph_objects as go
        fig = build_composite_gauge_figure(0.5, self.tokens)
        assert isinstance(fig, go.Figure)

    def test_figure_has_one_trace(self) -> None:
        """Il gauge deve avere esattamente 1 trace (Indicator)."""
        import plotly.graph_objects as go
        fig = build_composite_gauge_figure(0.4, self.tokens)
        assert len(fig.data) == 1
        assert isinstance(fig.data[0], go.Indicator)

    def test_score_value_in_figure(self) -> None:
        """Il valore del gauge è lo score passato."""
        score = 0.42
        fig = build_composite_gauge_figure(score, self.tokens)
        assert fig.data[0].value == pytest.approx(score)

    def test_score_clamped_to_minus_one_plus_one(self) -> None:
        """Score fuori range viene clampato silenziosamente."""
        fig_high = build_composite_gauge_figure(2.0, self.tokens)
        fig_low  = build_composite_gauge_figure(-2.0, self.tokens)
        assert fig_high.data[0].value == pytest.approx(1.0)
        assert fig_low.data[0].value  == pytest.approx(-1.0)

    def test_custom_title_applied(self) -> None:
        """Il titolo personalizzato è presente nella figura."""
        fig = build_composite_gauge_figure(0.0, self.tokens, title="Test Title")
        assert "Test Title" in str(fig.data[0].title)

    def test_custom_height_applied(self) -> None:
        """L'altezza personalizzata è presente nel layout."""
        fig = build_composite_gauge_figure(0.0, self.tokens, height=350)
        assert fig.layout.height == 350

    def test_paper_bgcolor_from_tokens(self) -> None:
        """paper_bgcolor proviene da tokens.plotly.paper_bgcolor (Regola 20)."""
        fig = build_composite_gauge_figure(0.0, self.tokens)
        assert fig.layout.paper_bgcolor == self.tokens.plotly.paper_bgcolor

    def test_negative_score_gauge_range_correct(self) -> None:
        """Il gauge ha range [-1, 1] — verificato sugli axis.

        ANTI-REGRESSIONE: Plotly ritorna tuple (non lista) per gauge.axis.range.
        Usare list() per confronto type-agnostic.
        """
        fig = build_composite_gauge_figure(-0.5, self.tokens)
        gauge = fig.data[0].gauge
        assert list(gauge.axis.range) == [-1.0, 1.0]

    def test_gauge_has_three_color_steps(self) -> None:
        """Le zone colorate nel gauge sono 3 (negativa, neutra, positiva)."""
        fig = build_composite_gauge_figure(0.0, self.tokens)
        assert len(fig.data[0].gauge.steps) == 3


# ─── Test: build_breakdown_bar_figure ────────────────────────────────────────

class TestBuildBreakdownBarFigure:
    """Tests per build_breakdown_bar_figure()."""

    def setup_method(self) -> None:
        self.tokens = _make_tokens()
        self.breakdown = {
            "vix": 0.35,
            "macro": -0.10,
            "yield_curve": 0.20,
            "credit": 0.05,
            "pattern": 0.40,
        }

    def test_returns_plotly_figure(self) -> None:
        import plotly.graph_objects as go
        fig = build_breakdown_bar_figure(self.breakdown, self.tokens)
        assert isinstance(fig, go.Figure)

    def test_figure_has_bar_trace(self) -> None:
        """Il chart ha almeno una Bar trace."""
        import plotly.graph_objects as go
        fig = build_breakdown_bar_figure(self.breakdown, self.tokens)
        assert any(isinstance(t, go.Bar) for t in fig.data)

    def test_correct_number_of_bars(self) -> None:
        """Numero di barre = numero di componenti nel breakdown."""
        fig = build_breakdown_bar_figure(self.breakdown, self.tokens)
        bar = next(t for t in fig.data if hasattr(t, "x"))
        assert len(bar.x) == len(self.breakdown)

    def test_empty_breakdown_returns_figure_with_annotation(self) -> None:
        """Breakdown vuoto → figura valida con annotation, nessuna barra."""
        fig = build_breakdown_bar_figure({}, self.tokens)
        assert len(fig.data) == 0
        assert len(fig.layout.annotations) > 0

    def test_paper_bgcolor_from_tokens(self) -> None:
        """Colore sfondo da tokens (Regola 20)."""
        fig = build_breakdown_bar_figure(self.breakdown, self.tokens)
        assert fig.layout.paper_bgcolor == self.tokens.plotly.paper_bgcolor

    def test_values_are_bar_x_axis(self) -> None:
        """I valori del breakdown sono sull'asse X (barre orizzontali)."""
        fig = build_breakdown_bar_figure({"a": 0.5, "b": -0.3}, self.tokens)
        bar = fig.data[0]
        assert 0.5 in list(bar.x)
        assert -0.3 in list(bar.x)

    def test_custom_height_applied(self) -> None:
        fig = build_breakdown_bar_figure(self.breakdown, self.tokens, height=300)
        assert fig.layout.height == 300

    def test_xaxis_includes_zero_range(self) -> None:
        """L'asse X copre sempre il range [-1, 1] circa."""
        fig = build_breakdown_bar_figure(self.breakdown, self.tokens)
        xrange = list(fig.layout.xaxis.range)
        assert xrange[0] < 0
        assert xrange[1] > 0
