# ruff: noqa: N999
"""P1 — Overview Patrimonio (v7.1.2 hotfix).

Risolve "P1 mostra 124.500EUR hardcoded" segnalato in ULTERIORI_ERRORI.txt.
Ora la pagina legge dal patrimonio reale dell'utente:

  - Patrimonio totale e liquidita' da ``networth_editor.net_worth_summary``.
  - Tasso risparmio del mese corrente da ``CashFlowEngine``.
  - Top 3 obiettivi da ``GoalManager`` (filtrati per profilo corrente).

Comportamento "stato vuoto":
  Se l'utente non ha ancora inserito asset/liabilities/goals/cashflow,
  la pagina mostra messaggi educativi che indirizzano alle pagine P3/P4/P5
  per la data entry. Niente piu' valori inventati.
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from personal.cashflow import CashFlowEngine
from personal.data_entry.networth_editor import net_worth_summary
from personal.goals import Goal, GoalManager, GoalStatus
from presentation.ui.components.goal_tracker import render_goals_list
from presentation.ui.components.kpi_card import render_kpi_row
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.2"

__all__ = ["body_overview_patrimonio"]

# Profilo "corrente" — convenzione single-user dell'app.
_CURRENT_PROFILE_ID = "current"


def _get_ytd_savings_rate(
    engine: CashFlowEngine, profile_id: str
) -> float | None:
    """Calcola tasso di risparmio YTD: (income - expense) / income.

    Returns None se non ci sono entrate registrate (evita div/0).
    """
    today = date.today()
    total_income = 0.0
    total_expense = 0.0
    for month in range(1, today.month + 1):
        try:
            summary = engine.monthly_summary(profile_id, today.year, month)
        except Exception:  # noqa: BLE001 -- log + fallback graceful
            continue
        total_income += summary.get("income", 0.0)
        total_expense += summary.get("expense", 0.0)
    if total_income <= 0.0:
        return None
    return max(0.0, (total_income - total_expense) / total_income)


def _safe_load_top_goals(profile_id: str, max_n: int = 3) -> list[Goal]:
    """Carica top N obiettivi attivi del profilo. Lista vuota se DB non pronto."""
    try:
        manager = GoalManager()
        goals = manager.list_for_profile(
            profile_id=profile_id, status=GoalStatus.ACTIVE
        )
    except Exception:  # noqa: BLE001 -- DB potrebbe non essere inizializzato
        return []
    # list_for_profile ordina gia' per priority DESC, target_date ASC
    return goals[:max_n]


def body_overview_patrimonio(
    tokens: DesignTokens,
) -> None:  # pragma: no cover -- Streamlit
    try:
        import streamlit as st
    except ImportError:
        return

    # ── 1. Patrimonio (asset - passivita) ─────────────────────────────────
    summary = net_worth_summary()
    has_networth_data = (
        summary["total_assets"] > 0 or summary["total_liabilities"] > 0
    )

    # ── 2. Cash flow / risparmio ─────────────────────────────────────────
    engine = CashFlowEngine()
    savings_rate = _get_ytd_savings_rate(engine, _CURRENT_PROFILE_ID)
    has_cashflow_data = savings_rate is not None

    render_section_header(
        "💎 Patrimonio Globale",
        "Riepilogo basato sui dati che hai inserito (modifica in P3, P4, P5)",
    )

    # KPI: '—' per campi senza dati, niente valori inventati.
    kpis: list[dict[str, object]] = [
        {
            "label": "Patrimonio Totale",
            "value": (
                float(summary["net_worth"]) if has_networth_data else "—"
            ),
            "fmt": "currency_eur",
        },
        {
            "label": "Liquidità",
            "value": (
                float(summary["liquid_assets"]) if has_networth_data else "—"
            ),
            "fmt": "currency_eur",
        },
        {
            "label": "Tasso Risparmio YTD",
            "value": float(savings_rate) if has_cashflow_data else "—",
            "fmt": "percent",
        },
        {
            "label": "Asset Liquidi/Tot.",
            "value": (
                float(summary["liquid_assets"]) / float(summary["total_assets"])
                if has_networth_data and summary["total_assets"] > 0
                else "—"
            ),
            "fmt": "percent",
        },
    ]
    render_kpi_row(tokens, kpis)

    # ── 3. Stato vuoto: messaggio educativo, nessun dato inventato ─────────
    if not has_networth_data:
        st.info(
            "👋 **Inizia da qui:** non hai ancora registrato asset o passivita'. "
            "Vai alla pagina **💰 Net Worth** per aggiungere conti, investimenti, "
            "immobili e mutui — il patrimonio totale verra' calcolato automaticamente."
        )

    if not has_cashflow_data:
        st.info(
            "💸 **Cash flow vuoto:** registra entrate e uscite nella pagina "
            "**💸 Cash Flow** per ottenere il tasso di risparmio reale."
        )

    # ── 4. Top obiettivi ───────────────────────────────────────────────────
    render_section_header("🎯 Top 3 Obiettivi")
    goals = _safe_load_top_goals(_CURRENT_PROFILE_ID, max_n=3)
    if goals:
        render_goals_list(tokens, goals)
    else:
        st.info(
            "🎯 **Nessun obiettivo attivo:** definisci i tuoi obiettivi SMART "
            "(casa, auto, pensione...) nella pagina **🎯 Obiettivi SMART** per "
            "vedere il progresso qui."
        )


if __name__ == "__main__":  # pragma: no cover
    render_page("Overview Patrimonio", "💼", body_overview_patrimonio)
