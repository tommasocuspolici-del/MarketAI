# ruff: noqa: N999
"""P5 — Obiettivi SMART (v7.1).

Risolve "non posso modificare gli obiettivi" della v6.
Ogni obiettivo e' persistito su UserDataStore (entity_type="goal") e
modificabile / eliminabile dall'utente.
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from personal.data_entry.goal_form import (
    ContributionFrequency,
    ContributionKind,
    GoalCategory,
    GoalInput,
    GoalPriority,
    add_contribution,
    delete_goal,
    list_contributions,
    list_goals,
    render_goal_form,
    save_goal,
)
from presentation.ui.components import EmptyState
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.2.0"

__all__ = ["body_goals"]


_PRIORITY_BADGES = {
    GoalPriority.HIGH: "🔴",
    GoalPriority.MEDIUM: "🟡",
    GoalPriority.LOW: "🟢",
}

_CATEGORY_ICONS = {
    GoalCategory.EMERGENCY: "🆘",
    GoalCategory.PURCHASE: "🏠",
    GoalCategory.RETIREMENT: "👴",
    GoalCategory.EDUCATION: "🎓",
    GoalCategory.TRAVEL: "✈️",
    GoalCategory.OTHER: "📌",
}


# v7.2 (B7): map labels per UI auto-contributo (un solo posto, no magic strings)
_FREQ_LABELS: dict[ContributionFrequency, str] = {
    ContributionFrequency.NONE: "❌ Disabilitato",
    ContributionFrequency.WEEKLY: "📅 Settimanale",
    ContributionFrequency.MONTHLY: "📆 Mensile",
}


def _render_goal_operations(  # pragma: no cover -- Streamlit-rendered
    st_module, goal: GoalInput
) -> None:
    """v7.2 (B7): Pannello deposito / prelievo / auto-contributo / storico.

    4 tab nello stesso expander:
      - Deposito una tantum
      - Prelievo una tantum (max = current_amount)
      - Auto-contributo (settimanale/mensile)
      - Storico operazioni
    """
    st = st_module
    with st.expander(
        "💰 Aggiungi / Rimuovi fondi · Auto-contributo",
        expanded=False,
    ):
        tab_dep, tab_wit, tab_auto, tab_hist = st.tabs(
            ["➕ Deposito", "➖ Prelievo", "🔄 Auto-contributo", "📋 Storico"]
        )

        # ── Deposito una tantum ──────────────────────────────────────────
        with tab_dep:
            with st.form(f"dep_form_{goal.goal_id}", clear_on_submit=True):
                amount_dep = st.number_input(
                    "Importo da aggiungere (€)",
                    min_value=0.01,
                    step=50.0,
                    format="%.2f",
                    key=f"dep_amount_{goal.goal_id}",
                )
                note_dep = st.text_input(
                    "Nota (opzionale)",
                    key=f"dep_note_{goal.goal_id}",
                    placeholder="Es. tredicesima dicembre",
                )
                if st.form_submit_button("➕ Deposita", type="primary"):
                    try:
                        updated = add_contribution(
                            goal.goal_id,
                            float(amount_dep),
                            ContributionKind.DEPOSIT,
                            note=note_dep,
                        )
                        st.success(
                            f"✅ +€{amount_dep:,.2f} → "
                            f"nuovo saldo: €{updated.current_amount:,.2f}"
                        )
                        st.rerun()
                    except ValueError as exc:
                        st.error(f"❌ {exc}")

        # ── Prelievo una tantum ─────────────────────────────────────────
        with tab_wit:
            max_wit = max(0.0, goal.current_amount)
            if max_wit <= 0:
                st.info(
                    "Il saldo dell'obiettivo è 0: non c'è nulla da prelevare."
                )
            else:
                with st.form(f"wit_form_{goal.goal_id}", clear_on_submit=True):
                    amount_wit = st.number_input(
                        "Importo da rimuovere (€)",
                        min_value=0.01,
                        max_value=float(max_wit),
                        step=50.0,
                        format="%.2f",
                        key=f"wit_amount_{goal.goal_id}",
                        help=f"Saldo disponibile: €{max_wit:,.2f}",
                    )
                    note_wit = st.text_input(
                        "Nota (opzionale)",
                        key=f"wit_note_{goal.goal_id}",
                    )
                    if st.form_submit_button("➖ Preleva"):
                        try:
                            updated = add_contribution(
                                goal.goal_id,
                                float(amount_wit),
                                ContributionKind.WITHDRAWAL,
                                note=note_wit,
                            )
                            st.success(
                                f"✅ −€{amount_wit:,.2f} → "
                                f"nuovo saldo: €{updated.current_amount:,.2f}"
                            )
                            st.rerun()
                        except ValueError as exc:
                            st.error(f"❌ {exc}")

        # ── Auto-contributo periodico ────────────────────────────────────
        with tab_auto:
            freq_opts = list(ContributionFrequency)
            current_freq = goal.auto_contribution_frequency
            try:
                idx = freq_opts.index(current_freq)
            except ValueError:
                idx = 0
            freq = st.selectbox(
                "Frequenza",
                options=freq_opts,
                format_func=lambda f: _FREQ_LABELS[f],
                index=idx,
                key=f"auto_freq_{goal.goal_id}",
            )
            auto_amount = st.number_input(
                "Importo per periodo (€)",
                min_value=0.0,
                step=10.0,
                format="%.2f",
                value=float(goal.auto_contribution_amount),
                key=f"auto_amount_{goal.goal_id}",
                disabled=(freq == ContributionFrequency.NONE),
                help="Lo scheduler eseguira' questa contribuzione "
                "automaticamente alla cadenza scelta.",
            )
            if st.button(
                "💾 Salva auto-contributo", key=f"auto_save_{goal.goal_id}"
            ):
                # Se freq=NONE, azzera anche l'importo per pulizia
                effective_amount = (
                    auto_amount if freq != ContributionFrequency.NONE else 0.0
                )
                updated = goal.model_copy(
                    update={
                        "auto_contribution_amount": effective_amount,
                        "auto_contribution_frequency": freq,
                    }
                )
                save_goal(updated)
                if freq != ContributionFrequency.NONE:
                    st.success(
                        f"✅ Auto-contributo {_FREQ_LABELS[freq]} "
                        f"di €{effective_amount:,.2f} configurato."
                    )
                else:
                    st.info("Auto-contributo disabilitato.")
                st.rerun()

        # ── Storico operazioni ──────────────────────────────────────────
        with tab_hist:
            contribs = list_contributions(goal.goal_id)
            if not contribs:
                st.info("Nessuna operazione registrata.")
            else:
                # Display amount con segno: WITHDRAWAL e' negativo
                rows: list[dict[str, str]] = []
                for c in contribs:
                    if c.kind == ContributionKind.WITHDRAWAL:
                        signed = f"-€{c.amount:,.2f}"
                    else:
                        signed = f"+€{c.amount:,.2f}"
                    rows.append(
                        {
                            "Data": c.executed_at.strftime("%Y-%m-%d %H:%M"),
                            "Tipo": c.kind.value,
                            "Importo": signed,
                            "Nota": c.note or "—",
                        }
                    )
                st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_goal_card(st_module, goal: GoalInput) -> None:  # pragma: no cover
    """Renderizza una card-goal con progress + azioni edit/delete."""
    st = st_module
    container = st.container(border=True)
    with container:
        cols = st.columns([4, 1, 1])
        with cols[0]:
            icon = _CATEGORY_ICONS[goal.category]
            badge = _PRIORITY_BADGES[goal.priority]
            st.markdown(f"### {icon} {goal.name} {badge}")
            st.caption(f"Categoria: {goal.category.value} · Priorita': {goal.priority.value}")
            progress = goal.progress_pct
            st.progress(
                progress,
                text=f"{progress * 100:.0f}% · €{goal.current_amount:,.0f} di €{goal.target_amount:,.0f}",
            )
            if goal.target_date <= date.today():
                if progress >= 1.0:
                    st.success("✅ Obiettivo completato!")
                else:
                    st.error(
                        f"⏰ Scaduto il {goal.target_date.isoformat()}. "
                        f"Mancano €{goal.remaining_amount:,.0f}."
                    )
            else:
                months = goal.months_to_target
                monthly = goal.required_monthly_savings()
                st.caption(
                    f"⏳ Mancano **{months} mesi** · Risparmio richiesto: "
                    f"**€{monthly:,.0f}/mese** · "
                    f"Scadenza: {goal.target_date.isoformat()}"
                )
            if goal.notes:
                st.caption(f"📝 {goal.notes}")

        with cols[1]:
            if st.button("✏️ Modifica", key=f"edit_{goal.goal_id}"):
                st.session_state[f"editing_goal_{goal.goal_id}"] = True

        with cols[2]:
            if st.button("🗑️ Elimina", key=f"del_{goal.goal_id}"):
                st.session_state[f"confirm_del_goal_{goal.goal_id}"] = True

    # Form modifica inline
    if st.session_state.get(f"editing_goal_{goal.goal_id}"):
        with st.expander("Modifica obiettivo", expanded=True):
            edited = render_goal_form(goal, key=f"form_{goal.goal_id}")
            if edited is not None:
                save_goal(edited)
                del st.session_state[f"editing_goal_{goal.goal_id}"]
                st.success(f"✅ Obiettivo '{edited.name}' aggiornato.")
                st.rerun()
            if st.button("Annulla", key=f"cancel_{goal.goal_id}"):
                del st.session_state[f"editing_goal_{goal.goal_id}"]
                st.rerun()

    # Conferma eliminazione
    if st.session_state.get(f"confirm_del_goal_{goal.goal_id}"):
        st.warning(f"Confermi l'eliminazione di '{goal.name}'? Operazione non annullabile.")
        cdel, ccancel = st.columns([1, 5])
        with cdel:
            if st.button("Conferma", key=f"confirm_yes_{goal.goal_id}", type="primary"):
                delete_goal(goal.goal_id)
                del st.session_state[f"confirm_del_goal_{goal.goal_id}"]
                st.rerun()
        with ccancel:
            if st.button("Annulla", key=f"confirm_no_{goal.goal_id}"):
                del st.session_state[f"confirm_del_goal_{goal.goal_id}"]
                st.rerun()

    # v7.2 (B7): pannello operazioni (deposito/prelievo/auto/storico)
    _render_goal_operations(st, goal)


def body_goals(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit-rendered
    """Body Streamlit della pagina P5 v7.1."""
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="p5_refresh"):
            st.cache_data.clear()
            st.rerun()

    render_section_header(
        "🎯 I tuoi obiettivi SMART",
        "Specific · Measurable · Achievable · Relevant · Time-bound",
    )

    goals = list_goals()
    if not goals:
        st.info(
            "Nessun obiettivo definito. Crea il tuo primo obiettivo qui sotto. "
            "Un obiettivo SMART include: nome, importo target, data target, priorita'."
        )
    else:
        for goal in goals:
            _render_goal_card(st, goal)

    st.divider()
    render_section_header("➕ Aggiungi nuovo obiettivo")
    new_goal = render_goal_form(key="new_goal_form")
    if new_goal is not None:
        save_goal(new_goal)
        st.success(f"✅ Obiettivo '{new_goal.name}' creato.")
        st.rerun()


if __name__ == "__main__":  # pragma: no cover
    render_page("Goals", "🎯", body_goals)
