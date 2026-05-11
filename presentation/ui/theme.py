"""Design tokens loader — typed access to ``config/ui_theme.yaml`` (Rule 20).

Components NEVER hardcode colors/sizes. They reference TOKENS via this
module: ``TOKENS.colors.positive`` instead of literal ``"#10B981"``.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from shared.exceptions import ConfigurationError

__version__ = "6.0.0"

__all__ = [
    "Borders",
    "Colors",
    "DesignTokens",
    "Formats",
    "Layout",
    "PlotlyTokens",
    "Spacing",
    "Typography",
    "hex_to_rgba",
    "load_design_tokens",
]

_DEFAULT_PATH = Path("config/ui_theme.yaml")


def hex_to_rgba(hex_color: str, alpha: float = 1.0) -> str:
    """Convert ``#RRGGBB`` hex to ``rgba(r, g, b, a)`` string.

    Plotly fillcolor only accepts named colors, hex (no alpha), rgb/rgba.
    This helper produces an rgba() string with explicit alpha.

    Args:
        hex_color: Hex color, with or without leading '#'.
        alpha: Alpha in [0, 1].
    """
    s = hex_color.lstrip("#")
    if len(s) != 6:
        raise ValueError(f"expected 6-char hex color, got {hex_color!r}")
    r = int(s[0:2], 16)
    g = int(s[2:4], 16)
    b = int(s[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha:.3f})"


@dataclass(frozen=True, slots=True)
class Colors:
    """Color palette tokens."""

    bg_primary: str
    bg_secondary: str
    bg_card: str
    bg_overlay: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent_primary: str
    accent_secondary: str
    positive: str
    negative: str
    warning: str
    neutral: str
    health_operational: str
    health_degraded: str
    health_down: str
    regime_bull: str
    regime_transition: str
    regime_bear: str
    regime_stress: str
    quality_excellent: str
    quality_good: str
    quality_fair: str
    quality_poor: str

    def for_pnl(self, value: float) -> str:
        """Color helper: positive/negative based on value sign."""
        if value > 0:
            return self.positive
        if value < 0:
            return self.negative
        return self.neutral

    def for_quality_score(self, score: float) -> str:
        """Color helper: quality bucket based on score in [0, 1]."""
        if score >= 0.9:
            return self.quality_excellent
        if score >= 0.7:
            return self.quality_good
        if score >= 0.5:
            return self.quality_fair
        return self.quality_poor

    def for_regime(self, regime: str) -> str:
        """Color helper: market regime."""
        regime_lower = regime.lower()
        mapping = {
            "bull": self.regime_bull,
            "transition": self.regime_transition,
            "bear": self.regime_bear,
            "stress": self.regime_stress,
        }
        return mapping.get(regime_lower, self.neutral)


@dataclass(frozen=True, slots=True)
class Typography:
    font_family_base: str
    font_family_mono: str
    font_size_xs: str
    font_size_sm: str
    font_size_base: str
    font_size_lg: str
    font_size_xl: str
    font_size_2xl: str
    font_size_3xl: str
    font_weight_normal: int
    font_weight_medium: int
    font_weight_semibold: int
    font_weight_bold: int


@dataclass(frozen=True, slots=True)
class Spacing:
    unit_xs: str
    unit_sm: str
    unit_md: str
    unit_lg: str
    unit_xl: str
    unit_2xl: str


@dataclass(frozen=True, slots=True)
class Borders:
    radius_sm: str
    radius_md: str
    radius_lg: str
    radius_xl: str
    width_thin: str
    width_medium: str
    width_thick: str


@dataclass(frozen=True, slots=True)
class PlotlyTokens:
    template: str
    paper_bgcolor: str
    plot_bgcolor: str
    grid_color: str
    font_color: str
    font_family: str
    height_sm: int
    height_md: int
    height_lg: int


@dataclass(frozen=True, slots=True)
class Layout:
    page_max_width: str
    sidebar_width: str
    card_padding: str
    cols_kpi_row: int
    cols_main_split: list[int]


@dataclass(frozen=True, slots=True)
class Formats:
    currency_eur: str
    currency_usd: str
    percent: str
    percent_signed: str
    number_decimal: str
    number_int: str
    basis_points: str


@dataclass(frozen=True, slots=True)
class DesignTokens:
    """Aggregate of all design tokens (Rule 20: single source of truth)."""

    colors: Colors
    typography: Typography
    spacing: Spacing
    borders: Borders
    plotly: PlotlyTokens
    layout: Layout
    formats: Formats


@lru_cache(maxsize=1)
def load_design_tokens(path: Path | None = None) -> DesignTokens:
    """Load and freeze design tokens from YAML.

    Cached: tokens are loaded once per process. To reload (e.g. in tests),
    call ``load_design_tokens.cache_clear()``.
    """
    config_path = path or _DEFAULT_PATH
    if not config_path.exists():
        raise ConfigurationError(
            f"Design tokens config not found: {config_path}. "
            f"Required for Rule 20 (no hardcoded UI values)."
        )

    raw: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
    return DesignTokens(
        colors=Colors(**raw["colors"]),
        typography=Typography(**raw["typography"]),
        spacing=Spacing(**raw["spacing"]),
        borders=Borders(**raw["borders"]),
        plotly=PlotlyTokens(**raw["plotly"]),
        layout=Layout(**raw["layout"]),
        formats=Formats(**raw["formats"]),
    )
