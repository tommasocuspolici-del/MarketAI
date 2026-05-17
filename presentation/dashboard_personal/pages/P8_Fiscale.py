# ruff: noqa: N999
"""P8 — Fiscale (plus/minusvalenze IT + tax-loss harvesting)."""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from personal.tax import (
    ITAssetClass,
    TaxableEvent,
    TaxCalculator,
    TaxRegime,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "6.0.0"

__all__ = ["body_fiscale"]


def body_fiscale(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit-rendered body
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st
    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="p8_refresh"):
            st.cache_data.clear()
            st.rerun()
    render_section_header("Calcolo Plus/Minusvalenze — Regime IT (26%)")
    fiscal_year = st.number_input("Anno fiscale", value=2025, min_value=2020, max_value=2030)
    if st.button("Calcola tasse anno corrente"):
        events = [
            TaxableEvent(ticker="AAPL", asset_class=ITAssetClass.EQUITY,
                         gain=1500, currency="EUR", realized_at=date(int(fiscal_year), 3, 15)),
            TaxableEvent(ticker="GOOGL", asset_class=ITAssetClass.EQUITY,
                         gain=-400, currency="EUR", realized_at=date(int(fiscal_year), 6, 22)),
            TaxableEvent(ticker="BTP", asset_class=ITAssetClass.GOVT_BOND_IT,
                         gain=200, currency="EUR", realized_at=date(int(fiscal_year), 9, 10)),
        ]
        calc = TaxCalculator(regime=TaxRegime.ITALY)
        report = calc.compute_annual_report(
            profile_id="me", fiscal_year=int(fiscal_year), events=events,
        )
        cols = st.columns(4)
        cols[0].metric("Plusvalenze", f"€{report.total_gain:,.2f}")
        cols[1].metric("Minusvalenze", f"€{report.total_loss:,.2f}")
        cols[2].metric("Imposta dovuta", f"€{report.tax_owed:,.2f}")
        cols[3].metric("Carry-forward", f"€{report.remaining_carry_forward:,.2f}")
    render_section_header("Tax-Loss Harvesting Suggestions")
    st.info("💡 2 posizioni in perdita > €500 candidate per realizzo a fine anno.")


if __name__ == "__main__":   # pragma: no cover
    render_page("Fiscale", "💸", body_fiscale)
