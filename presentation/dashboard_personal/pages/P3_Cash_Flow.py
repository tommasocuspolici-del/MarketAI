# ruff: noqa: N999
"""P3 — Cash Flow (v7.1.3 hotfix B4).

Versione precedente (v7.1.2) mescolava entrate e uscite in un'unica tabella.
Questa versione (BUG_REPORT_v7.1.1.md sezione B4) introduce tab separati:

  📥 **Entrate**   — lista entrate del mese + form aggiunta entrata
  📤 **Uscite**    — lista uscite del mese + form aggiunta uscita
  📊 **Riepilogo** — totali, waterfall, trend 12 mesi

Tutti i dati provengono dal ``CashFlowEngine`` (SQLite tabella
``cash_flow_entries``). Niente piu' valori mock.

Stato vuoto: messaggi educativi nei tab senza dati.
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import streamlit as st

from personal.cashflow import CashFlowDirection, CashFlowEngine, CashFlowEntry
from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components.cash_flow_waterfall import (
    render_cash_flow_waterfall,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.3"

__all__ = ["body_cash_flow"]

_CURRENT_PROFILE_ID = "current"

# Categorie suggerite — l'utente puo' comunque digitare la propria.
_INCOME_CATEGORIES: tuple[str, ...] = (
    "Stipendio",
    "Bonus",
    "Affitto incassato",
    "Dividendi",
    "Vendita",
    "Rimborso",
    "Altro",
)
_EXPENSE_CATEGORIES: tuple[str, ...] = (
    "Affitto/Mutuo",
    "Spesa",
    "Trasporti",
    "Bollette",
    "Tempo Libero",
    "Salute",
    "Tasse",
    "Altro",
)


# ─── Helpers ────────────────────────────────────────────────────────────────
def _list_entries_for_month(
    engine: CashFlowEngine,
    direction: CashFlowDirection,
) -> list[CashFlowEntry]:
    """Lista entries del mese corrente filtrate per direzione."""
    today = date.today()
    start_month = date(today.year, today.month, 1)
    try:
        return engine.list_entries(
            profile_id=_CURRENT_PROFILE_ID,
            start_date=start_month,
            end_date=today,
            direction=direction,
        )
    except Exception:  # noqa: BLE001 -- tabella mancante / DB locked
        return []


@st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS)
def _entries_to_rows(entries: list[CashFlowEntry]) -> list[dict[str, object]]:  # pragma: no cover
    """Converte entries in lista di dict per st.dataframe."""
    return [
        {
            "Data": e.occurred_at.isoformat(),
            "Categoria": e.category,
            "Descrizione": e.description or "—",
            "Importo (€)": f"{e.amount:,.2f}",
            "Ricorrente": "✅" if e.is_recurring else "",
        }
        for e in entries
    ]


def _add_entry_form(  # pragma: no cover -- Streamlit
    st_module,
    engine: CashFlowEngine,
    *,
    direction: CashFlowDirection,
    key_prefix: str,
) -> None:
    """Form per aggiungere un movimento (entrata o uscita).

    direction e' fissato dal contesto (tab) — l'utente non puo' confondersi.
    """
    st = st_module
    is_income = direction == CashFlowDirection.IN
    label_action = "entrata" if is_income else "uscita"
    options = _INCOME_CATEGORIES if is_income else _EXPENSE_CATEGORIES

    with st.form(f"{key_prefix}_form", clear_on_submit=True):
        cols = st.columns([2, 2, 1])
        with cols[0]:
            category = st.selectbox(
                "Categoria",
                options=options,
                key=f"{key_prefix}_category",
            )
        with cols[1]:
            description = st.text_input(
                "Descrizione (opzionale)",
                placeholder=f"Dettaglio {label_action}",
                key=f"{key_prefix}_desc",
            )
        with cols[2]:
            amount = st.number_input(
                "Importo (€) *",
                min_value=0.01,
                step=10.0,
                format="%.2f",
                key=f"{key_prefix}_amount",
            )

        cols2 = st.columns([1, 1, 2])
        with cols2[0]:
            occurred_at = st.date_input(
                "Data",
                value=date.today(),
                key=f"{key_prefix}_date",
            )
        with cols2[1]:
            is_recurring = st.checkbox(
                "Ricorrente",
                value=False,
                key=f"{key_prefix}_recurring",
                help=f"Spunta se e' una {label_action} mensile fissa",
            )
        submitted = st.form_submit_button(
            f"➕ Aggiungi {label_action}",
            type="primary",
        )

    if not submitted:
        return
    if amount <= 0:
        st.error("❌ L'importo deve essere positivo.")
        return

    entry = CashFlowEntry(
        profile_id=_CURRENT_PROFILE_ID,
        occurred_at=occurred_at,
        direction=direction,
        category=str(category),
        amount=float(amount),
        description=description.strip() or None,
        is_recurring=bool(is_recurring),
    )
    try:
        engine.add_entry(entry)
    except Exception as exc:  # noqa: BLE001 -- tabella mancante o DB locked
        st.error(
            f"❌ Errore salvataggio: {exc}. "
            "Verifica che le migration SQLite siano applicate "
            "(`poetry run alembic upgrade head`)."
        )
        return
    st.success(f"✅ {label_action.capitalize()} aggiunta: €{amount:,.2f} ({category})")
    st.rerun()


def _delete_selector(  # pragma: no cover -- Streamlit
    st_module,
    engine: CashFlowEngine,
    entries: list[CashFlowEntry],
    key_prefix: str,
) -> None:
    """Selectbox + conferma per cancellare una entry."""
    st = st_module
    if not entries:
        return
    labels = [
        f"{e.occurred_at.isoformat()} · {e.category} · €{e.amount:,.2f}"
        for e in entries
    ]
    selected = st.selectbox(
        "Cancella un movimento",
        options=["—"] + labels,
        key=f"{key_prefix}_delete_select",
    )
    if selected != "—":
        idx = labels.index(selected)
        entry = entries[idx]
        if st.button(
            f"🗑️ Conferma cancellazione",
            key=f"{key_prefix}_del_{entry.entry_id}",
        ):
            engine.delete_entry(entry.entry_id)
            st.success("✅ Movimento cancellato.")
            st.rerun()


# ─── Tab content ───────────────────────────────────────────────────────────
def _render_tab_entries(  # pragma: no cover -- Streamlit
    st_module,
    engine: CashFlowEngine,
    *,
    direction: CashFlowDirection,
    key_prefix: str,
) -> None:
    """Tab generico per Entrate o Uscite."""
    st = st_module
    is_income = direction == CashFlowDirection.IN
    label_plural = "entrate" if is_income else "uscite"
    icon = "📥" if is_income else "📤"

    entries = _list_entries_for_month(engine, direction)
    today = date.today()

    if entries:
        total = sum(e.amount for e in entries)
        st.metric(
            f"Totale {label_plural} (mese {today.strftime('%B %Y')})",
            f"€{total:,.2f}",
        )
        st.dataframe(_entries_to_rows(entries), use_container_width=True, hide_index=True)
        _delete_selector(st, engine, entries, key_prefix=key_prefix)
    else:
        st.info(
            f"{icon} **Nessuna {label_plural[:-1]} questo mese.** "
            "Usa il form qui sotto per aggiungere la prima."
        )

    st.divider()
    st.write(f"**Aggiungi nuova {label_plural[:-1]}**")
    _add_entry_form(st, engine, direction=direction, key_prefix=key_prefix)


def _render_tab_summary(  # pragma: no cover -- Streamlit
    tokens: DesignTokens,
    st_module,
    engine: CashFlowEngine,
) -> None:
    """Tab riepilogo: totali mensili, waterfall, trend 12 mesi."""
    st = st_module
    today = date.today()
    try:
        summary = engine.monthly_summary(_CURRENT_PROFILE_ID, today.year, today.month)
    except Exception:  # noqa: BLE001
        summary = {"income": 0.0, "expense": 0.0, "net": 0.0}

    cols = st.columns(3)
    cols[0].metric("Entrate (mese)", f"€{summary['income']:,.2f}")
    cols[1].metric("Uscite (mese)", f"€{summary['expense']:,.2f}")
    cols[2].metric("Saldo netto", f"€{summary['net']:,.2f}")

    has_data = (summary["income"] + summary["expense"]) > 0
    if not has_data:
        st.info(
            "📊 **Riepilogo non disponibile:** registra almeno un'entrata "
            "o un'uscita nei tab dedicati per vedere waterfall e trend."
        )
        return

    # Waterfall del mese corrente per categoria
    income_entries = _list_entries_for_month(engine, CashFlowDirection.IN)
    expense_entries = _list_entries_for_month(engine, CashFlowDirection.OUT)
    by_cat: dict[str, float] = {}
    for e in income_entries:
        by_cat[e.category] = by_cat.get(e.category, 0.0) + e.amount
    for e in expense_entries:
        by_cat[e.category] = by_cat.get(e.category, 0.0) - e.amount
    sorted_items = sorted(by_cat.items(), key=lambda kv: -kv[1])
    categories = [c for c, _ in sorted_items] + ["Net"]
    amounts = [a for _, a in sorted_items] + [sum(by_cat.values())]

    render_section_header(
        f"📊 Waterfall · {today.strftime('%B %Y')}",
        "Movimenti aggregati per categoria del mese corrente",
    )
    render_cash_flow_waterfall(
        tokens,
        categories=categories,
        amounts=amounts,
        title=f"Cash Flow {today.strftime('%B %Y')}",
    )

    # Trend 12 mesi
    months: list[tuple[int, int]] = []
    for offset in range(11, -1, -1):
        month_total = today.month - offset
        year = today.year
        while month_total <= 0:
            month_total += 12
            year -= 1
        months.append((year, month_total))

    series: list[float] = []
    labels: list[str] = []
    for year, month in months:
        try:
            s = engine.monthly_summary(_CURRENT_PROFILE_ID, year, month)
            series.append(s["net"])
        except Exception:  # noqa: BLE001
            series.append(0.0)
        labels.append(f"{year}-{month:02d}")

    nonzero = sum(1 for v in series if v != 0.0)
    if nonzero >= 2:
        st.divider()
        render_section_header(
            "📈 Trend risparmio (12 mesi)",
            "Saldo netto per mese",
        )
        st.line_chart({"Saldo netto (€)": series})


# ─── Body ──────────────────────────────────────────────────────────────────
def body_cash_flow(
    tokens: DesignTokens,
) -> None:  # pragma: no cover -- Streamlit
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    engine = CashFlowEngine()

    render_section_header(
        "💸 Cash Flow",
        "Registra entrate e uscite separatamente · dati reali da SQLite",
    )

    tab_in, tab_out, tab_summary = st.tabs([
        "📥 Entrate",
        "📤 Uscite",
        "📊 Riepilogo",
    ])

    with tab_in:
        _render_tab_entries(
            st,
            engine,
            direction=CashFlowDirection.IN,
            key_prefix="p3_in",
        )

    with tab_out:
        _render_tab_entries(
            st,
            engine,
            direction=CashFlowDirection.OUT,
            key_prefix="p3_out",
        )

    with tab_summary:
        _render_tab_summary(tokens, st, engine)


if __name__ == "__main__":  # pragma: no cover
    render_page("Cash Flow", "💸", body_cash_flow)
