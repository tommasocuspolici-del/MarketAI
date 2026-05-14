"""Profile card — visual summary of an InvestorProfile."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from personal.investor_profile import InvestorProfile
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["build_profile_card_html", "render_profile_card"]


def build_profile_card_html(
    tokens: DesignTokens, profile: InvestorProfile
) -> str:
    """Build HTML for an investor profile card (testable)."""
    c = tokens.colors
    risk_color = {
        "conservative":     c.accent_primary,
        "moderate":         c.accent_secondary,
        "aggressive":       c.warning,
        "very_aggressive":  c.negative,
    }.get(profile.risk_tolerance.value, c.neutral)

    asset_classes = ", ".join(profile.allowed_asset_classes)

    return (
        '<div class="market-ai-kpi-card">'
        f'<div class="market-ai-kpi-label">Investor Profile</div>'
        f'<div class="market-ai-kpi-value">{profile.name}</div>'
        f'<div style="margin-top: {tokens.spacing.unit_md};">'
        f'<span style="background-color: {risk_color}33; color: {risk_color}; '
        f'padding: {tokens.spacing.unit_xs} {tokens.spacing.unit_sm}; '
        f'border-radius: {tokens.borders.radius_sm}; '
        f'font-size: {tokens.typography.font_size_sm}; '
        f'font-weight: {tokens.typography.font_weight_semibold};">'
        f"{profile.risk_tolerance.value.upper()}"
        "</span>"
        "</div>"
        f'<div style="margin-top: {tokens.spacing.unit_sm}; '
        f'color: {c.text_secondary}; '
        f'font-size: {tokens.typography.font_size_sm};">'
        f"<div>Max DD: <strong>{profile.max_drawdown_pct:.0%}</strong></div>"
        f"<div>Horizon: <strong>{profile.horizon_years} yrs ("
        f"{profile.investment_horizon.value})</strong></div>"
        f"<div>Liquidity: <strong>{profile.liquidity_reserve_months} months</strong></div>"
        f"<div>Knowledge: <strong>{profile.financial_knowledge}/5</strong></div>"
        f"<div>Currency: <strong>{profile.base_currency}</strong></div>"
        f'<div style="margin-top: {tokens.spacing.unit_sm}; '
        f'color: {c.text_muted};">Asset classes: {asset_classes}</div>'
        "</div>"
        "</div>"
    )


def render_profile_card(
    tokens: DesignTokens, profile: InvestorProfile
) -> None:  # pragma: no cover
    """Render an investor profile card."""
    html = build_profile_card_html(tokens, profile)
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso
    import streamlit as st  # pragma: no cover
    st.markdown(html, unsafe_allow_html=True)
