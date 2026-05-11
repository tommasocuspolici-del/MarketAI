"""Form Streamlit per asset e liabilities (split di networth_editor.py).

Separato per rispettare Rule 2 (max 400 righe per file).
La logica di persistenza e i modelli vivono in ``networth_editor.py``.
"""
from __future__ import annotations

from datetime import date

from personal.data_entry.networth_editor import (
    Asset,
    AssetType,
    Liability,
    LiabilityType,
    new_id,
)

__version__ = "7.1.0"

__all__ = ["render_asset_form", "render_liability_form"]


def render_asset_form(
    existing: Asset | None = None,
    *,
    key: str = "asset_form",
) -> Asset | None:  # pragma: no cover -- Streamlit-rendered
    """Renderizza il form asset (CRUD)."""
    try:
        import streamlit as st
    except ImportError:
        return None

    is_edit = existing is not None
    st.subheader("✏️ Modifica asset" if is_edit else "➕ Nuovo asset")

    with st.form(key=key, clear_on_submit=not is_edit):
        col1, col2 = st.columns(2)

        with col1:
            name = st.text_input(
                "Nome asset *",
                value=existing.name if existing else "",
                placeholder="Es. 'Conto BancaX', 'Casa Milano', 'Portafoglio eToro'",
                key=f"{key}_name",
            )

            asset_types = list(AssetType)
            type_labels = {
                AssetType.CHECKING: "💳 Conto corrente",
                AssetType.SAVINGS: "🏦 Conto deposito",
                AssetType.INVESTMENT: "📈 Portafoglio investimenti",
                AssetType.REAL_ESTATE: "🏠 Immobile",
                AssetType.CRYPTO: "₿ Crypto",
                AssetType.PENSION: "👴 Fondo pensione",
                AssetType.INSURANCE: "🛡️ Polizza vita / TFR",
                AssetType.OTHER: "📌 Altro",
            }
            asset_type = st.selectbox(
                "Tipologia *",
                options=asset_types,
                format_func=lambda t: type_labels[t],
                index=asset_types.index(existing.asset_type) if existing else 0,
                key=f"{key}_type",
            )

            value = st.number_input(
                "Valore corrente (€) *",
                min_value=0.01,
                value=float(existing.value) if existing else 1_000.0,
                step=100.0,
                format="%.2f",
                key=f"{key}_value",
            )

        with col2:
            currency = st.selectbox(
                "Valuta",
                options=["EUR", "USD", "GBP", "CHF"],
                index=["EUR", "USD", "GBP", "CHF"].index(existing.currency)
                if existing
                else 0,
                key=f"{key}_currency",
            )

            valuation_date_val = st.date_input(
                "Data valutazione",
                value=existing.valuation_date if existing else date.today(),
                max_value=date.today(),
                key=f"{key}_val_date",
            )

            is_liquid = st.checkbox(
                "Liquido (convertibile in cash entro 30gg)",
                value=existing.is_liquid if existing else True,
                help="Conti, ETF e azioni sono liquidi. "
                "Immobili e fondi pensione no.",
                key=f"{key}_liquid",
            )

        notes = st.text_area(
            "Note",
            value=existing.notes if existing else "",
            max_chars=500,
            key=f"{key}_notes",
        )

        submitted = st.form_submit_button(
            "💾 Salva" if is_edit else "➕ Aggiungi",
            type="primary",
        )

    if not submitted:
        return None
    if not name:
        st.error("❌ Il nome e' obbligatorio.")
        return None

    try:
        return Asset(
            asset_id=existing.asset_id if existing else new_id(),
            name=name,
            asset_type=asset_type,
            value=value,
            currency=currency,
            valuation_date=valuation_date_val
            if isinstance(valuation_date_val, date)
            else date.today(),
            is_liquid=is_liquid,
            notes=notes,
        )
    except ValueError as exc:
        st.error(f"❌ Errore di validazione: {exc}")
        return None


def render_liability_form(
    existing: Liability | None = None,
    *,
    key: str = "liability_form",
) -> Liability | None:  # pragma: no cover -- Streamlit-rendered
    """Renderizza il form passivita' (CRUD)."""
    try:
        import streamlit as st
    except ImportError:
        return None

    is_edit = existing is not None
    st.subheader("✏️ Modifica passivita'" if is_edit else "➕ Nuova passivita'")

    with st.form(key=key, clear_on_submit=not is_edit):
        col1, col2 = st.columns(2)

        with col1:
            name = st.text_input(
                "Nome *",
                value=existing.name if existing else "",
                placeholder="Es. Mutuo prima casa, Prestito auto",
                key=f"{key}_name",
            )

            types = list(LiabilityType)
            labels = {
                LiabilityType.MORTGAGE: "🏠 Mutuo",
                LiabilityType.LOAN: "💸 Prestito personale",
                LiabilityType.CREDIT_CARD: "💳 Carta di credito",
                LiabilityType.OTHER: "📌 Altro",
            }
            liability_type = st.selectbox(
                "Tipologia *",
                options=types,
                format_func=lambda t: labels[t],
                index=types.index(existing.liability_type) if existing else 0,
                key=f"{key}_type",
            )

            outstanding = st.number_input(
                "Debito residuo (€) *",
                min_value=0.01,
                value=float(existing.outstanding_amount) if existing else 10_000.0,
                step=100.0,
                format="%.2f",
                key=f"{key}_outstanding",
            )

        with col2:
            monthly = st.number_input(
                "Rata mensile (€)",
                min_value=0.0,
                value=float(existing.monthly_payment or 0.0)
                if existing
                else 0.0,
                step=10.0,
                format="%.2f",
                key=f"{key}_monthly",
            )

            interest = st.number_input(
                "TAEG / TAN (%)",
                min_value=0.0,
                max_value=30.0,
                value=float(existing.interest_rate_pct or 0.0)
                if existing
                else 0.0,
                step=0.1,
                format="%.2f",
                key=f"{key}_interest",
            )

            end_date_default = (
                existing.end_date if existing and existing.end_date else None
            )
            has_end = st.checkbox(
                "Ha una data di fine",
                value=end_date_default is not None,
                key=f"{key}_has_end",
            )
            end_date_val: date | None = None
            if has_end:
                end_date_val = st.date_input(
                    "Data scadenza",
                    value=end_date_default
                    if end_date_default
                    else date.today().replace(year=date.today().year + 5),
                    min_value=date.today(),
                    key=f"{key}_end",
                )

        notes = st.text_area(
            "Note",
            value=existing.notes if existing else "",
            max_chars=500,
            key=f"{key}_notes",
        )

        submitted = st.form_submit_button(
            "💾 Salva" if is_edit else "➕ Aggiungi",
            type="primary",
        )

    if not submitted:
        return None
    if not name:
        st.error("❌ Il nome e' obbligatorio.")
        return None

    try:
        return Liability(
            liability_id=existing.liability_id if existing else new_id(),
            name=name,
            liability_type=liability_type,
            outstanding_amount=outstanding,
            monthly_payment=monthly if monthly > 0 else None,
            end_date=end_date_val,
            interest_rate_pct=interest if interest > 0 else None,
            currency=existing.currency if existing else "EUR",
            notes=notes,
        )
    except ValueError as exc:
        st.error(f"❌ Errore di validazione: {exc}")
        return None
