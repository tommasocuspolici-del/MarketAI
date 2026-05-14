# ruff: noqa: N999
"""P4 — Net Worth (v7.1).

Risolve "non posso modificare il valore del portafoglio" della v6.
Asset e passivita' editabili e persistenti.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from personal.data_entry.networth_editor import (
    delete_asset,
    delete_liability,
    list_assets,
    list_liabilities,
    net_worth_summary,
    save_asset,
    save_liability,
)
from personal.data_entry.networth_forms import (
    render_asset_form,
    render_liability_form,
)
from presentation.ui.components.metric_card import (
    MetricSpec,
    render_metric_row,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.0"

__all__ = ["body_net_worth"]


def _render_assets_tab(tokens, st_module) -> None:  # pragma: no cover
    """Tab di gestione asset."""
    st = st_module
    render_section_header("🏦 Asset")
    assets = list_assets()
    if not assets:
        st.info(
            "Nessun asset registrato. Aggiungi il tuo primo asset (conto, "
            "investimento, immobile, ...) per iniziare a costruire il patrimonio."
        )
    else:
        rows = [
            {
                "Nome": a.name,
                "Tipo": a.asset_type.value,
                "Valore (€)": f"{a.value:,.2f}",
                "Liquido": "✅" if a.is_liquid else "❌",
                "Aggiornato il": a.valuation_date.isoformat(),
                "Note": a.notes[:60],
            }
            for a in assets
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)

        labels = [f"{a.name} ({a.asset_type.value})" for a in assets]
        selected = st.selectbox(
            "Seleziona asset da modificare/eliminare",
            options=["—"] + labels,
            key="asset_selector",
        )
        if selected != "—":
            idx = labels.index(selected)
            asset = assets[idx]
            cols = st.columns([3, 1])
            with cols[0]:
                edited = render_asset_form(asset, key=f"edit_asset_{asset.asset_id}")
                if edited is not None:
                    save_asset(edited)
                    st.success(f"✅ Asset '{edited.name}' aggiornato.")
                    st.rerun()
            with cols[1]:
                if st.button(
                    "🗑️ Elimina",
                    key=f"del_asset_{asset.asset_id}",
                    type="secondary",
                ):
                    st.session_state[f"confirm_del_asset_{asset.asset_id}"] = True
                if st.session_state.get(f"confirm_del_asset_{asset.asset_id}"):
                    st.warning("Sicuro?")
                    if st.button("Conferma", key=f"yes_del_asset_{asset.asset_id}"):
                        delete_asset(asset.asset_id)
                        del st.session_state[f"confirm_del_asset_{asset.asset_id}"]
                        st.rerun()

    st.divider()
    render_section_header("➕ Aggiungi nuovo asset")
    new_asset = render_asset_form(key="new_asset_form")
    if new_asset is not None:
        save_asset(new_asset)
        st.success(f"✅ Asset '{new_asset.name}' aggiunto.")
        st.rerun()


def _render_liabilities_tab(tokens, st_module) -> None:  # pragma: no cover
    """Tab di gestione passivita'."""
    st = st_module
    render_section_header("💳 Passivita'")
    liabilities = list_liabilities()
    if not liabilities:
        st.info("Nessuna passivita' registrata. Se hai mutuo, prestiti o carte di credito, aggiungili qui.")
    else:
        rows = [
            {
                "Nome": l.name,
                "Tipo": l.liability_type.value,
                "Debito residuo (€)": f"{l.outstanding_amount:,.2f}",
                "Rata mensile": f"{l.monthly_payment:,.2f}" if l.monthly_payment else "—",
                "TAEG/TAN": f"{l.interest_rate_pct:.2f}%" if l.interest_rate_pct else "—",
                "Scadenza": l.end_date.isoformat() if l.end_date else "—",
            }
            for l in liabilities
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)

        labels = [f"{l.name} ({l.liability_type.value})" for l in liabilities]
        selected = st.selectbox(
            "Seleziona passivita' da modificare/eliminare",
            options=["—"] + labels,
            key="liab_selector",
        )
        if selected != "—":
            idx = labels.index(selected)
            liab = liabilities[idx]
            cols = st.columns([3, 1])
            with cols[0]:
                edited = render_liability_form(liab, key=f"edit_liab_{liab.liability_id}")
                if edited is not None:
                    save_liability(edited)
                    st.success(f"✅ Passivita' '{edited.name}' aggiornata.")
                    st.rerun()
            with cols[1]:
                if st.button("🗑️ Elimina", key=f"del_liab_{liab.liability_id}"):
                    st.session_state[f"confirm_del_liab_{liab.liability_id}"] = True
                if st.session_state.get(f"confirm_del_liab_{liab.liability_id}"):
                    st.warning("Sicuro?")
                    if st.button("Conferma", key=f"yes_del_liab_{liab.liability_id}"):
                        delete_liability(liab.liability_id)
                        del st.session_state[f"confirm_del_liab_{liab.liability_id}"]
                        st.rerun()

    st.divider()
    render_section_header("➕ Aggiungi nuova passivita'")
    new_liab = render_liability_form(key="new_liab_form")
    if new_liab is not None:
        save_liability(new_liab)
        st.success(f"✅ Passivita' '{new_liab.name}' aggiunta.")
        st.rerun()


def body_net_worth(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit-rendered
    """Body Streamlit della pagina P4 v7.1."""
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    summary = net_worth_summary()
    render_section_header(
        "💎 Patrimonio Netto",
        "Calcolato come Asset Totali − Passivita' Totali (modifica i dati nei tab sotto)",
    )

    metrics = [
        MetricSpec(
            term="Net Worth",
            value=summary["net_worth"],
            format_spec=",.0f",
            unit_override="€",
        ),
        MetricSpec(
            term="Asset Totali",
            value=summary["total_assets"],
            format_spec=",.0f",
            unit_override="€",
        ),
        MetricSpec(
            term="Passivita' Totali",
            value=summary["total_liabilities"],
            format_spec=",.0f",
            unit_override="€",
        ),
        MetricSpec(
            term="Liquidita'",
            value=summary["liquid_assets"],
            format_spec=",.0f",
            unit_override="€",
        ),
    ]
    render_metric_row(tokens, metrics)

    if summary["total_assets"] == 0 and summary["total_liabilities"] == 0:
        st.info(
            "👋 **Nessun dato presente**. Inizia aggiungendo i tuoi asset "
            "(conti, investimenti, immobili) e le passivita' (mutuo, prestiti). "
            "Il patrimonio netto sara' calcolato automaticamente."
        )

    tab_assets, tab_liabilities = st.tabs(["🏦 Asset", "💳 Passivita'"])
    with tab_assets:
        _render_assets_tab(tokens, st)
    with tab_liabilities:
        _render_liabilities_tab(tokens, st)


if __name__ == "__main__":  # pragma: no cover
    render_page("Net Worth", "📈", body_net_worth)
