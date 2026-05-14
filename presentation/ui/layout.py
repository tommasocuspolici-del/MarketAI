"""Layout helpers — page configuration + section wrappers.

Provides a single ``setup_page()`` entry that:
  · Configures Streamlit page (title, icon, layout)
  · Applies custom CSS from ``DESIGN_TOKENS``
  · Optionally renders the auth gate (Rule 32)
  · Optionally renders the health status bar in the sidebar
"""
from __future__ import annotations

from presentation.ui.theme import DesignTokens, load_design_tokens

__version__ = "6.0.0"

__all__ = ["build_custom_css", "setup_page"]


def build_custom_css(tokens: DesignTokens) -> str:
    """Build the global Streamlit CSS string from DESIGN_TOKENS.

    Pure function — no Streamlit dependency, easy to unit-test.
    """
    c = tokens.colors
    t = tokens.typography
    layout = tokens.layout
    return f"""
    <style>
    /* Body background */
    .stApp {{
        background-color: {c.bg_primary};
        color: {c.text_primary};
        font-family: {t.font_family_base};
    }}

    /* Sidebar */
    section[data-testid="stSidebar"] {{
        background-color: {c.bg_secondary};
        width: {layout.sidebar_width};
    }}

    /* KPI cards (custom class used by KpiCard component) */
    .market-ai-kpi-card {{
        background-color: {c.bg_card};
        padding: {tokens.spacing.unit_md};
        border-radius: {tokens.borders.radius_md};
        border: {tokens.borders.width_thin} solid {c.bg_overlay};
    }}

    .market-ai-kpi-label {{
        color: {c.text_secondary};
        font-size: {t.font_size_sm};
        font-weight: {t.font_weight_medium};
    }}

    .market-ai-kpi-value {{
        color: {c.text_primary};
        font-size: {t.font_size_2xl};
        font-weight: {t.font_weight_bold};
        font-family: {t.font_family_mono};
    }}

    /* Quality badge */
    .market-ai-quality-badge {{
        display: inline-block;
        padding: {tokens.spacing.unit_xs} {tokens.spacing.unit_sm};
        border-radius: {tokens.borders.radius_sm};
        font-size: {t.font_size_xs};
        font-weight: {t.font_weight_semibold};
    }}

    /* Health status bar */
    .market-ai-health-bar {{
        padding: {tokens.spacing.unit_sm};
        border-radius: {tokens.borders.radius_sm};
        font-size: {t.font_size_sm};
        text-align: center;
    }}
    </style>
    """


def setup_page(
    title: str,
    icon: str = "📊",
    require_auth_gate: bool = True,
) -> DesignTokens:  # pragma: no cover
    """Apply the standard page setup. Returns DESIGN_TOKENS for the caller.

    Standard order on every dashboard page:
      1. ``setup_page("E1 Market Overview")`` — config + CSS + auth gate
      2. Component rendering using the returned ``tokens``

    Args:
        title: Page title for browser tab + h1.
        icon: Emoji or path used as page icon.
        require_auth_gate: If True (default), enforces ``require_auth()``
            (Rule 32). Set False only for the public landing page (none in v6).

    Returns:
        The DesignTokens singleton — components reference this only.
    """
    tokens = load_design_tokens()

    # Streamlit is optional at import time (CI/tests don't have it).
    # When not available, this function is a no-op past tokens.
    try:  # pragma: no cover
        import streamlit as st
    except ImportError:
        return tokens

    st.set_page_config(
        page_title=f"Market AI · {title}",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(build_custom_css(tokens), unsafe_allow_html=True)

    # Auth gate — Rule 32
    if require_auth_gate:
        from presentation.ui.auth import require_auth
        require_auth()

    # Page title
    st.markdown(f"# {icon} {title}")
    return tokens


def render_section_header(title: str, subtitle: str | None = None) -> None:  # pragma: no cover
    """Render a section header (h2 + optional caption).

    No-op outside Streamlit.
    """
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    st.markdown(f"## {title}")
    if subtitle:
        st.caption(subtitle)
