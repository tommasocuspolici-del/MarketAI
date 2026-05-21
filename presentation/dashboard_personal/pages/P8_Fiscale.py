# ruff: noqa: N999
"""P8 — Fiscale (plus/minusvalenze IT + tax-loss harvesting).

v7.0.0: Calcola eventi fiscali dalle posizioni reali nel DB (SQLite).
Fallback a messaggio "nessun evento" se non ci sono posizioni chiuse.
Aggiunge sezione tax-loss harvesting con posizioni in perdita reali.
"""
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

__version__ = "8.2.0"

__all__ = ["body_fiscale"]

_ASSET_CLASS_MAP: dict[str, ITAssetClass] = {
    "EQUITY":       ITAssetClass.EQUITY,
    "ETF":          ITAssetClass.ETF_EQUITY,
    "CRYPTO":       ITAssetClass.CRYPTO,
    "FOREX":        ITAssetClass.EQUITY,        # no regime specifico, tassato come EQUITY
    "GOVT_BOND_IT": ITAssetClass.GOVT_BOND_IT,
}


def _load_positions_as_events(fiscal_year: int) -> list[TaxableEvent]:
    """Legge le posizioni da SQLite e le trasforma in TaxableEvent.

    Usa avg_cost vs current_price (o yfinance) per stimare P/L non realizzato.
    Restituisce lista vuota se nessuna posizione è presente o DB non disponibile.
    """
    try:
        from personal.data_entry.etoro_importer import get_live_price_usd
        from personal.data_entry.position_form import list_positions
    except Exception:
        return []

    try:
        positions = list_positions()
    except Exception:
        return []
    if not positions:
        return []

    events: list[TaxableEvent] = []
    for pos in positions:
        ticker = pos.ticker
        try:
            live_price = get_live_price_usd(ticker)
        except Exception:
            live_price = pos.avg_cost

        if live_price is None or live_price <= 0:
            live_price = pos.avg_cost

        # Stima P/L in valuta della posizione (non convertita — approssimazione)
        if pos.direction == "LONG":
            gain_per_unit = live_price - pos.avg_cost
        else:
            gain_per_unit = pos.avg_cost - live_price
        total_gain = gain_per_unit * pos.quantity

        # Mappa asset class
        exc_upper = pos.exchange.upper()
        if "CRYPTO" in exc_upper:
            asset_class = ITAssetClass.CRYPTO
        elif "FOREX" in exc_upper:
            asset_class = ITAssetClass.EQUITY
        elif ticker.endswith(".MI") or ticker.startswith("BTP"):
            asset_class = ITAssetClass.GOVT_BOND_IT
        else:
            asset_class = ITAssetClass.EQUITY

        # Data realizzo: usa data apertura + 1y come proxy (posizione ancora aperta)
        realized_at = date(fiscal_year, 12, 31)
        if pos.open_date:
            open_yr = pos.open_date.year
            if open_yr == fiscal_year:
                realized_at = date(fiscal_year, pos.open_date.month, pos.open_date.day)

        events.append(
            TaxableEvent(
                ticker=ticker,
                asset_class=asset_class,
                gain=total_gain,
                currency=pos.currency,
                realized_at=realized_at,
            )
        )
    return events


def body_fiscale(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit-rendered body
    import streamlit as st

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="p8_refresh"):
            st.cache_data.clear()
            st.rerun()

    render_section_header("Calcolo Plus/Minusvalenze — Regime IT (26%)")
    fiscal_year = st.number_input("Anno fiscale", value=date.today().year, min_value=2020, max_value=2030)

    if st.button("Calcola tasse anno corrente"):
        with st.spinner("Recupero posizioni dal DB..."):
            try:
                events = _load_positions_as_events(int(fiscal_year))
            except Exception as exc:
                st.error(f"Errore caricamento posizioni: {exc}")
                events = []

        if not events:
            st.warning(
                "⚠️ Nessuna posizione trovata nel DB. "
                "Importa le posizioni dal tab **P2 Portafoglio eToro** o "
                "aggiungile manualmente prima di calcolare le tasse."
            )
        else:
            st.info(
                f"(i) Calcolo basato su **{len(events)} posizioni aperte** con P/L stimato "
                "al prezzo corrente. Per eventi di chiusura precisi, registra le vendite manualmente."
            )
            calc = TaxCalculator(regime=TaxRegime.ITALY)
            report = calc.compute_annual_report(
                profile_id="me", fiscal_year=int(fiscal_year), events=events,
            )
            cols = st.columns(4)
            cols[0].metric("Plusvalenze", f"€{report.total_gain:,.2f}")
            cols[1].metric("Minusvalenze", f"€{report.total_loss:,.2f}")
            cols[2].metric("Imposta dovuta", f"€{report.tax_owed:,.2f}")
            cols[3].metric("Carry-forward", f"€{report.remaining_carry_forward:,.2f}")

            # Dettaglio eventi
            with st.expander("📋 Dettaglio eventi per posizione", expanded=False):
                import pandas as pd
                df = pd.DataFrame([
                    {
                        "Ticker": e.ticker,
                        "Asset Class": e.asset_class.value if hasattr(e.asset_class, "value") else str(e.asset_class),
                        "P/L stimato": f"€{e.gain:,.2f}",
                        "Valuta": e.currency,
                        "Data": e.realized_at.isoformat(),
                    }
                    for e in events
                ])
                st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()
    render_section_header("Tax-Loss Harvesting Suggestions")

    @st.cache_data(ttl=300)
    def _tax_loss_candidates() -> list[dict]:
        from personal.data_entry.etoro_importer import get_live_price_usd
        from personal.data_entry.position_form import list_positions

        positions = list_positions()
        candidates = []
        for pos in positions:
            try:
                live_price = get_live_price_usd(pos.ticker) or pos.avg_cost
                if pos.direction == "LONG":
                    loss = (live_price - pos.avg_cost) * pos.quantity
                else:
                    loss = (pos.avg_cost - live_price) * pos.quantity
                if loss < -500:
                    candidates.append({
                        "Ticker": pos.ticker,
                        "P/L stimato": f"{loss:,.0f} {pos.currency}",
                        "Perdita": abs(loss),
                    })
            except Exception:
                pass
        candidates.sort(key=lambda x: x["Perdita"], reverse=True)
        return candidates

    try:
        candidates = _tax_loss_candidates()
        if candidates:
            st.success(
                f"💡 **{len(candidates)} posizioni** in perdita > €500 candidate per "
                "realizzo a fine anno (tax-loss harvesting):"
            )
            import pandas as pd
            df_c = pd.DataFrame([{"Ticker": c["Ticker"], "Perdita stimata": c["P/L stimato"]} for c in candidates])
            st.dataframe(df_c, use_container_width=True, hide_index=True)
        else:
            st.info("Nessuna posizione con perdita > €500. Nessuna opportunità di tax-loss harvesting.")
    except Exception as exc:
        st.info(f"Tax-loss harvesting non disponibile: {exc}")


if __name__ == "__main__":   # pragma: no cover
    render_page("Fiscale", "💸", body_fiscale)
