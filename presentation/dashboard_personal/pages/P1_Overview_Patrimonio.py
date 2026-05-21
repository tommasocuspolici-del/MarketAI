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

import streamlit as st

from personal.cashflow import CashFlowEngine
from personal.data_entry.networth_editor import net_worth_summary
from personal.goals import Goal, GoalManager, GoalStatus
from presentation.ui.cache_policy import CACHE_TTL
from presentation.ui.components import EmptyState
from presentation.ui.components.goal_tracker import render_goals_list
from presentation.ui.components.kpi_card import render_kpi_row
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "8.2.0"

__all__ = ["body_overview_patrimonio"]

# Profilo "corrente" — convenzione single-user dell'app.
_CURRENT_PROFILE_ID = "current"


def _load_networth_summary() -> dict:
    """Carica riepilogo patrimonio. Ritorna dict con zeri se DB non disponibile."""
    try:
        return net_worth_summary()
    except Exception:
        return {"total_assets": 0.0, "total_liabilities": 0.0, "net_worth": 0.0,
                "liquid_assets": 0.0, "n_assets": 0, "n_liabilities": 0}


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


@st.cache_data(ttl=CACHE_TTL.PORTFOLIO_TOTALS)
def _safe_load_top_goals(profile_id: str, max_n: int = 3) -> list[Goal]:  # pragma: no cover
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
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="p1_refresh"):
            st.cache_data.clear()
            st.rerun()

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
        EmptyState(
            "Nessun asset o passività registrata",
            hint="Vai alla pagina 💰 Net Worth per aggiungere conti, investimenti e mutui.",
            severity="info",
        ).render()

    if not has_cashflow_data:
        EmptyState(
            "Cash flow vuoto",
            hint="Registra entrate e uscite nella pagina 💸 Cash Flow per ottenere il tasso di risparmio reale.",
            severity="info",
        ).render()

    # ── 4. Top obiettivi ───────────────────────────────────────────────────
    render_section_header("🎯 Top 3 Obiettivi")
    goals = _safe_load_top_goals(_CURRENT_PROFILE_ID, max_n=3)
    if goals:
        render_goals_list(tokens, goals)
    else:
        EmptyState(
            "Nessun obiettivo attivo",
            hint="Definisci obiettivi SMART (casa, pensione...) nella pagina 🎯 Obiettivi SMART.",
            severity="info",
        ).render()


if __name__ == "__main__":  # pragma: no cover
    render_page("Overview Patrimonio", "💼", body_overview_patrimonio)
