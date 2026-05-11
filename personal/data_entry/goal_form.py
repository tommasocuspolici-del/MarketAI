"""Form di creazione/modifica obiettivi SMART (Rule 41).

Risolve "non posso modificare gli obiettivi" della v6.
Persiste gli obiettivi su UserDataStore con entity_type="goal".

v7.2 (fix B7): aggiunti GoalContribution (storico operazioni: deposito,
prelievo, auto-contributo) + auto-contribuzione periodica (settimanale/
mensile) configurabile per ogni goal. Vedi BUGFIX_PRIORITARIO.md sezione B7.

NB: ``GoalContribution``, ``ContributionKind``, ``add_contribution``,
``list_contributions`` vivono in ``goal_contributions.py`` (Rule 2,
max 400 righe per file). Sono ri-esportati da qui per backward compat.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from personal.data_entry.goal_contributions import (
    CONTRIBUTION_TYPE,
    ContributionKind,
    GoalContribution,
    add_contribution,
    list_contributions,
)
from personal.data_entry.user_data_store import (
    UserDataStore,
    get_default_store,
    new_id,
)

__version__ = "7.2.0"

__all__ = [
    "CONTRIBUTION_TYPE",
    "ContributionFrequency",
    "ContributionKind",
    "GoalCategory",
    "GoalContribution",
    "GoalInput",
    "GoalPriority",
    "add_contribution",
    "delete_goal",
    "list_contributions",
    "list_goals",
    "render_goal_form",
    "save_goal",
]

ENTITY_TYPE = "goal"


class GoalPriority(str, Enum):
    """Priorita' di un obiettivo."""

    HIGH = "ALTA"
    MEDIUM = "MEDIA"
    LOW = "BASSA"


class GoalCategory(str, Enum):
    """Tipologia di obiettivo (tassonomia educativa)."""

    EMERGENCY = "FONDO_EMERGENZA"
    PURCHASE = "ACQUISTO"
    RETIREMENT = "PENSIONE"
    EDUCATION = "ISTRUZIONE"
    TRAVEL = "VIAGGIO"
    OTHER = "ALTRO"


# v7.2 (B7): frequenze auto-contributo
class ContributionFrequency(str, Enum):
    """Frequenza di auto-contributo periodico (eseguito da scheduler)."""

    NONE = "NESSUNO"
    WEEKLY = "SETTIMANALE"
    MONTHLY = "MENSILE"


class GoalInput(BaseModel):
    """Schema obiettivo SMART."""

    model_config = ConfigDict(str_strip_whitespace=True)

    goal_id: str = Field(default_factory=new_id)
    name: str = Field(min_length=1, max_length=120)
    category: GoalCategory = GoalCategory.OTHER
    target_amount: float = Field(gt=0)
    current_amount: float = Field(default=0.0, ge=0)
    currency: str = "EUR"
    target_date: date
    priority: GoalPriority = GoalPriority.MEDIUM
    notes: str = ""

    # v7.2 (B7): auto-contributo periodico (gestito da scheduler).
    # Default = nessun auto-contributo. Se freq != NONE e amount > 0,
    # lo scheduler eseguira' add_contribution(AUTO) alla cadenza configurata.
    auto_contribution_amount: float = Field(default=0.0, ge=0)
    auto_contribution_frequency: ContributionFrequency = ContributionFrequency.NONE

    @field_validator("currency")
    @classmethod
    def _ccy_upper(cls, v: str) -> str:
        return v.strip().upper()

    @property
    def progress_pct(self) -> float:
        """Percentuale di completamento (0-1)."""
        if self.target_amount <= 0:
            return 0.0
        return min(1.0, self.current_amount / self.target_amount)

    @property
    def remaining_amount(self) -> float:
        """Importo ancora da raccogliere."""
        return max(0.0, self.target_amount - self.current_amount)

    @property
    def months_to_target(self) -> int:
        """Mesi residui fino a target_date."""
        today = date.today()
        if self.target_date <= today:
            return 0
        delta = self.target_date - today
        return max(1, delta.days // 30)

    def required_monthly_savings(self) -> float:
        """Risparmio mensile necessario per centrare l'obiettivo a oggi."""
        if self.months_to_target <= 0:
            return self.remaining_amount
        return self.remaining_amount / self.months_to_target

    def to_payload(self) -> dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "name": self.name,
            "category": self.category.value,
            "target_amount": self.target_amount,
            "current_amount": self.current_amount,
            "currency": self.currency,
            "target_date": self.target_date.isoformat(),
            "priority": self.priority.value,
            "notes": self.notes,
            # v7.2 (B7): persisti auto-contributo
            "auto_contribution_amount": self.auto_contribution_amount,
            "auto_contribution_frequency": self.auto_contribution_frequency.value,
            "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "GoalInput":
        data = dict(payload)
        if isinstance(data.get("target_date"), str):
            data["target_date"] = date.fromisoformat(data["target_date"])
        # v7.2 (B7): backward compat — goal pre-v7.2 non avevano questi campi
        data.setdefault("auto_contribution_amount", 0.0)
        data.setdefault(
            "auto_contribution_frequency", ContributionFrequency.NONE.value
        )
        return cls.model_validate(data)


# ────────────────────────────────────────────── persistence
def list_goals(store: UserDataStore | None = None) -> list[GoalInput]:
    """Tutti gli obiettivi salvati, ordinati per priorita' poi target_date."""
    s = store or get_default_store()
    out: list[GoalInput] = []
    for r in s.list_by_type(ENTITY_TYPE):
        try:
            out.append(GoalInput.from_payload(r.payload))
        except (ValueError, KeyError, TypeError):
            continue
    priority_order = {
        GoalPriority.HIGH: 0,
        GoalPriority.MEDIUM: 1,
        GoalPriority.LOW: 2,
    }
    out.sort(key=lambda g: (priority_order[g.priority], g.target_date))
    return out


def save_goal(goal: GoalInput, store: UserDataStore | None = None) -> None:
    """Salva o aggiorna un goal."""
    s = store or get_default_store()
    s.upsert(ENTITY_TYPE, goal.goal_id, goal.to_payload())


def delete_goal(goal_id: str, store: UserDataStore | None = None) -> bool:
    """Cancella un goal."""
    s = store or get_default_store()
    return s.delete(ENTITY_TYPE, goal_id)


# ─────────────────────────────────────────────────── contributions (v7.2 B7)
# v7.2: GoalContribution + add_contribution + list_contributions sono stati
# spostati in personal/data_entry/goal_contributions.py per rispettare
# Rule 2 (max 400 righe per file). Sono ri-esportati in cima a questo
# modulo (vedi import) → API public invariata.


# ────────────────────────────────────────────── streamlit form
def render_goal_form(
    existing: GoalInput | None = None,
    *,
    key: str = "goal_form",
) -> GoalInput | None:  # pragma: no cover -- Streamlit-rendered
    """Renderizza il form di creazione/modifica obiettivo."""
    try:
        import streamlit as st
    except ImportError:
        return None

    is_edit = existing is not None
    title = "✏️ Modifica obiettivo" if is_edit else "🎯 Nuovo obiettivo"
    st.subheader(title)

    with st.form(key=key, clear_on_submit=not is_edit):
        col1, col2 = st.columns(2)

        with col1:
            name = st.text_input(
                "Nome obiettivo *",
                value=existing.name if existing else "",
                placeholder="Es. Acconto casa, Vacanza Giappone, Fondo emergenza",
                key=f"{key}_name",
            )

            categories = list(GoalCategory)
            category_labels = {
                GoalCategory.EMERGENCY: "🆘 Fondo emergenza",
                GoalCategory.PURCHASE: "🏠 Acquisto importante",
                GoalCategory.RETIREMENT: "👴 Pensione / FIRE",
                GoalCategory.EDUCATION: "🎓 Istruzione",
                GoalCategory.TRAVEL: "✈️ Viaggio",
                GoalCategory.OTHER: "📌 Altro",
            }
            category = st.selectbox(
                "Categoria *",
                options=categories,
                format_func=lambda c: category_labels[c],
                index=categories.index(existing.category) if existing else 0,
                key=f"{key}_category",
            )

            target_amount = st.number_input(
                "Importo target (€) *",
                min_value=1.0,
                value=float(existing.target_amount) if existing else 10_000.0,
                step=100.0,
                format="%.2f",
                help="Quanto vuoi accumulare per raggiungere l'obiettivo.",
                key=f"{key}_target",
            )

            current_amount = st.number_input(
                "Importo gia' accumulato (€)",
                min_value=0.0,
                value=float(existing.current_amount) if existing else 0.0,
                step=100.0,
                format="%.2f",
                key=f"{key}_current",
            )

        with col2:
            target_date_val = st.date_input(
                "Data target *",
                value=existing.target_date
                if existing
                else date.today().replace(year=date.today().year + 1),
                min_value=date.today(),
                key=f"{key}_target_date",
            )

            priorities = list(GoalPriority)
            priority_labels = {
                GoalPriority.HIGH: "🔴 ALTA",
                GoalPriority.MEDIUM: "🟡 MEDIA",
                GoalPriority.LOW: "🟢 BASSA",
            }
            priority = st.selectbox(
                "Priorita' *",
                options=priorities,
                format_func=lambda p: priority_labels[p],
                index=priorities.index(existing.priority) if existing else 1,
                key=f"{key}_priority",
            )

            currency = st.selectbox(
                "Valuta",
                options=["EUR", "USD", "GBP", "CHF"],
                index=["EUR", "USD", "GBP", "CHF"].index(existing.currency)
                if existing
                else 0,
                key=f"{key}_currency",
            )

        notes = st.text_area(
            "Note",
            value=existing.notes if existing else "",
            placeholder="Es. 'Da raggiungere prima della laurea'",
            max_chars=500,
            key=f"{key}_notes",
        )

        # Stima risparmio mensile in tempo reale
        if target_amount > 0:
            today = date.today()
            target_date_safe = (
                target_date_val
                if isinstance(target_date_val, date)
                else today
            )
            months = max(1, (target_date_safe - today).days // 30)
            remaining = max(0.0, target_amount - current_amount)
            monthly = remaining / months if months > 0 else remaining
            st.info(
                f"💡 Per centrare l'obiettivo dovresti accumulare circa "
                f"**€{monthly:,.0f} al mese** per i prossimi **{months}** mesi."
            )

        submitted = st.form_submit_button(
            "💾 Salva modifiche" if is_edit else "➕ Crea obiettivo",
            type="primary",
        )

    if not submitted:
        return None

    if not name:
        st.error("❌ Il nome dell'obiettivo e' obbligatorio.")
        return None

    if current_amount > target_amount:
        st.warning(
            "⚠️ L'importo gia' accumulato supera il target. "
            "L'obiettivo sara' segnato come completato."
        )

    try:
        goal = GoalInput(
            goal_id=existing.goal_id if existing else new_id(),
            name=name,
            category=category,
            target_amount=target_amount,
            current_amount=current_amount,
            currency=currency,
            target_date=target_date_val
            if isinstance(target_date_val, date)
            else date.today(),
            priority=priority,
            notes=notes,
        )
    except ValueError as exc:
        st.error(f"❌ Errore di validazione: {exc}")
        return None

    return goal
