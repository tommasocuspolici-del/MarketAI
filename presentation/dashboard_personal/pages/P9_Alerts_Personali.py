# ruff: noqa: N999
"""P9 — Alerts Personali (v7.2 fix B8).

Risolve "DataFrame completamente hardcoded" segnalato in
BUGFIX_PRIORITARIO.md sezione B8: la versione precedente mostrava 3 alert
fittizi statici e le soglie configurabili non venivano persistite.

Ora la pagina:
  - Esegue ``run_rules()`` ad ogni apertura per generare alert nuovi.
  - Mostra gli alert da UserDataStore (ordinati dal piu' recente).
  - Pulsante "Segna come letto" per ogni alert non letto.
  - Form per configurare soglie patrimonio (min/target) — persistite via
    ``save_thresholds()``.
  - Filtro "Solo non letti".
  - Stato vuoto "✅ Nessun alert: tutto in ordine".
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from personal.alerts import (
    AlertKind,
    AlertSeverity,
    PersonalAlert,
    list_alerts,
    load_thresholds,
    mark_read,
    run_rules,
    save_thresholds,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.2.0"

__all__ = ["body_alerts_personali"]

# Mapping severita' → emoji (no magic strings nei body — Regola 7).
_SEVERITY_ICONS: dict[AlertSeverity, str] = {
    AlertSeverity.INFO: "🟢",
    AlertSeverity.WARNING: "🟡",
    AlertSeverity.CRITICAL: "🔴",
}

# Mapping kind → label leggibile (Italian).
_KIND_LABELS: dict[AlertKind, str] = {
    AlertKind.GOAL_AT_RISK: "Goal a rischio",
    AlertKind.GOAL_ACHIEVED: "Goal completato",
    AlertKind.REBALANCING_NEEDED: "Ribilanciamento",
    AlertKind.WEALTH_BELOW_MIN: "Soglia patrimonio (min)",
    AlertKind.WEALTH_ABOVE_TARGET: "Obiettivo patrimonio",
    AlertKind.NEGATIVE_CASHFLOW: "Cashflow negativo",
}


def _render_alert_card(  # pragma: no cover -- Streamlit-rendered
    st_module, alert: PersonalAlert
) -> None:
    """Renderizza un singolo alert in card border."""
    st = st_module
    icon = _SEVERITY_ICONS.get(alert.severity, "⚪")
    label = _KIND_LABELS.get(alert.kind, alert.kind.value)

    with st.container(border=True):
        cols = st.columns([10, 1])
        with cols[0]:
            # Stilizziamo "letto" con un'opacita' visiva (caption invece di markdown bold)
            if alert.is_read:
                st.caption(f"{icon} {alert.title}  ·  _{label}_  ·  ✓ letto")
                st.caption(alert.detail)
            else:
                st.markdown(f"**{icon} {alert.title}**")
                st.caption(f"_{label}_")
                st.markdown(alert.detail)
            st.caption(f"🕐 {alert.triggered_at.strftime('%Y-%m-%d %H:%M')}")
        with cols[1]:
            if not alert.is_read:
                if st.button(
                    "✓",
                    key=f"read_{alert.alert_id}",
                    help="Segna come letto",
                ):
                    mark_read(alert.alert_id)
                    st.rerun()


def body_alerts_personali(
    tokens: DesignTokens,
) -> None:  # pragma: no cover -- Streamlit
    try:
        import streamlit as st
    except ImportError:
        return

    # Rigenera alert ogni apertura pagina (idempotente entro 24h grazie a dedup)
    new_alerts = run_rules()

    render_section_header(
        "🔔 Alert Personali",
        "Notifiche generate da regole reali su goal, patrimonio, cashflow",
    )

    # Toolbar: filtri e refresh
    cols_top = st.columns([2, 2, 2])
    with cols_top[0]:
        unread_only = st.toggle("Solo non letti", value=False, key="p9_unread_only")
    with cols_top[1]:
        if new_alerts:
            st.caption(f"🆕 {len(new_alerts)} nuovi alert in questa sessione")
    with cols_top[2]:
        if st.button("🔄 Rigenera", key="p9_rerun"):
            st.rerun()

    alerts = list_alerts(unread_only=unread_only)

    if not alerts:
        if unread_only:
            st.success("✅ Nessun alert non letto. Tutti gestiti!")
        else:
            st.success(
                "✅ Nessun alert attivo. Tutto in ordine!\n\n"
                "Suggerimento: configura le **soglie patrimonio** qui sotto "
                "per ricevere allerte quando il Net Worth scende sotto un valore "
                "minimo o supera l'obiettivo."
            )
    else:
        for alert in alerts:
            _render_alert_card(st, alert)

    # ── Configurazione soglie patrimonio ────────────────────────────────
    st.divider()
    render_section_header(
        "⚙️ Soglie Patrimonio Configurabili",
        "Definisci i livelli di Net Worth che attivano allerte",
    )

    thresholds = load_thresholds()
    with st.form("p9_thresholds_form"):
        c1, c2 = st.columns(2)
        with c1:
            min_thr = st.number_input(
                "Soglia minima allerta (€)",
                value=float(thresholds["min_alert"]),
                step=1_000.0,
                min_value=0.0,
                format="%.2f",
                help=(
                    "Se il Net Worth scende sotto questo valore, viene generato "
                    "un alert CRITICAL. Imposta a 0 per disattivare."
                ),
            )
        with c2:
            tgt_thr = st.number_input(
                "Soglia obiettivo (€)",
                value=float(thresholds["target_alert"]),
                step=10_000.0,
                min_value=0.0,
                format="%.2f",
                help=(
                    "Quando il Net Worth supera questo valore, ricevi una "
                    "notifica INFO 🎉. Imposta a 0 per disattivare."
                ),
            )
        if st.form_submit_button("💾 Salva soglie", type="primary"):
            try:
                save_thresholds(min_thr, tgt_thr)
                st.success("✅ Soglie salvate. Le nuove regole verranno valutate al prossimo refresh.")
                # Pulisci cache se presente
                if hasattr(st, "cache_data"):
                    st.cache_data.clear()
                st.rerun()
            except ValueError as exc:
                st.error(f"❌ {exc}")

    st.caption(
        "📌 Deduplication: lo stesso tipo di alert non viene generato due volte "
        "in 24h (per goal_id specifico, se applicabile)."
    )


if __name__ == "__main__":  # pragma: no cover
    render_page("Alerts Personali", "🔔", body_alerts_personali)
