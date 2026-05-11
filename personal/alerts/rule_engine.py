"""Rule engine per alert personali — v7.2 (fix B8).

Genera alert basati su regole reali (goal a rischio, soglie patrimonio,
cashflow negativo) e li persiste su UserDataStore. Sostituisce il
contenuto completamente hardcoded di P9_Alerts_Personali.py v6.

Regole implementate:
  R1. **Goal a rischio**: required_monthly_savings > soglia E progresso < 80%.
  R2. **Goal completato**: current_amount >= target_amount.
  R3. **Patrimonio sotto soglia minima**: net_worth < min_alert (configurabile).
  R4. **Patrimonio sopra soglia obiettivo**: net_worth >= target_alert.
  R5. **Cashflow mensile negativo**: spese > entrate nel mese corrente.

Deduplication 24h: lo stesso ``AlertKind`` non viene generato due volte
nella stessa finestra temporale. Eccezione: ``GOAL_AT_RISK`` puo' coesistere
per goal diversi (chiave dedup = kind + goal_id).

NOTE su threshold:
  Le soglie patrimonio sono persistite come record singolo
  ``entity_type="personal_alert_threshold"`` ``entity_id="wealth_thresholds"``
  con payload ``{"min_alert": float, "target_alert": float}``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from personal.alerts.alert_model import (
    ALERT_TYPE,
    THRESHOLD_TYPE,
    AlertKind,
    AlertSeverity,
    PersonalAlert,
)
from personal.cashflow import CashFlowEngine
from personal.data_entry.goal_form import list_goals
from personal.data_entry.networth_editor import net_worth_summary
from personal.data_entry.user_data_store import (
    UserDataStore,
    get_default_store,
)
from shared.logger import get_logger

__version__ = "7.2.0"

__all__ = [
    "list_alerts",
    "load_thresholds",
    "mark_read",
    "run_rules",
    "save_thresholds",
]

log = get_logger(__name__)

# Costanti regole (Rule 7: nominate, no magic numbers).
# _DEDUP_WINDOW_H: in 24h non rigeneriamo lo stesso AlertKind (per goal_id se applicabile).
# _GOAL_AT_RISK_MONTHLY_THRESHOLD: se richiesti >€1000/mese per centrare il goal,
#                                  consideriamo "a rischio" — soglia educativa,
#                                  rivedibile.
# _GOAL_AT_RISK_PROGRESS_MAX: se gia' all'80% di completamento, no alert
#                             (anche €1500/mese per finire e' ok se manca poco).
_DEDUP_WINDOW_H: int = 24
_GOAL_AT_RISK_MONTHLY_THRESHOLD: float = 1000.0
_GOAL_AT_RISK_PROGRESS_MAX: float = 0.80
# ID singleton del record soglie patrimonio
_WEALTH_THRESHOLDS_KEY = "wealth_thresholds"
# Threshold di default (piu' bassi di un patrimonio realistico → effetto:
# nessun alert generato finche' l'utente non configura le sue soglie).
_DEFAULT_MIN_ALERT: float = 0.0
_DEFAULT_TARGET_ALERT: float = 0.0
# Profilo single-user usato per query cashflow (coerente con altre pagine).
_CURRENT_PROFILE_ID = "current"


# ─────────────────────────────────────────────────── thresholds CRUD
def load_thresholds(store: UserDataStore | None = None) -> dict[str, float]:
    """Carica soglie patrimonio. Default = tutto a 0 (= nessun alert)."""
    s = store or get_default_store()
    rec = s.get(THRESHOLD_TYPE, _WEALTH_THRESHOLDS_KEY)
    if rec is None:
        return {
            "min_alert": _DEFAULT_MIN_ALERT,
            "target_alert": _DEFAULT_TARGET_ALERT,
        }
    payload = rec.payload
    return {
        "min_alert": float(payload.get("min_alert", _DEFAULT_MIN_ALERT)),
        "target_alert": float(payload.get("target_alert", _DEFAULT_TARGET_ALERT)),
    }


def save_thresholds(
    min_alert: float,
    target_alert: float,
    store: UserDataStore | None = None,
) -> None:
    """Persiste le soglie patrimonio configurate dall'utente in P9."""
    if min_alert < 0 or target_alert < 0:
        raise ValueError("Le soglie patrimonio devono essere >= 0")
    s = store or get_default_store()
    s.upsert(
        THRESHOLD_TYPE,
        _WEALTH_THRESHOLDS_KEY,
        {
            "min_alert": float(min_alert),
            "target_alert": float(target_alert),
        },
    )


# ─────────────────────────────────────────────────── alerts CRUD
def list_alerts(
    *,
    unread_only: bool = False,
    store: UserDataStore | None = None,
) -> list[PersonalAlert]:
    """Tutti gli alert dal piu' recente. Filtro opzionale unread."""
    s = store or get_default_store()
    out: list[PersonalAlert] = []
    for r in s.list_by_type(ALERT_TYPE):
        try:
            a = PersonalAlert.from_payload(r.payload)
        except (ValueError, KeyError, TypeError):
            continue
        if unread_only and a.is_read:
            continue
        out.append(a)
    out.sort(key=lambda a: a.triggered_at, reverse=True)
    return out


def mark_read(alert_id: str, store: UserDataStore | None = None) -> bool:
    """Segna alert come letto. Ritorna True se trovato."""
    s = store or get_default_store()
    rec = s.get(ALERT_TYPE, alert_id)
    if rec is None:
        return False
    payload = {**rec.payload, "is_read": True}
    s.upsert(ALERT_TYPE, alert_id, payload)
    return True


# ─────────────────────────────────────────────────── deduplication
def _recent_alert_dedup_keys(
    store: UserDataStore, hours: int = _DEDUP_WINDOW_H
) -> set[tuple[str, str | None]]:
    """Set di chiavi (kind, goal_id) generate nelle ultime N ore.

    Per kind GOAL_*, includiamo goal_id nella chiave -> un alert per goal puo'
    coesistere con uno di un altro goal nella stessa finestra. Per gli altri,
    goal_id=None (singleton per kind).
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    keys: set[tuple[str, str | None]] = set()
    for r in store.list_by_type(ALERT_TYPE):
        try:
            a = PersonalAlert.from_payload(r.payload)
        except (ValueError, KeyError, TypeError):
            continue
        if a.triggered_at >= cutoff:
            keys.add((a.kind.value, a.goal_id))
    return keys


# ─────────────────────────────────────────────────── rule executors
def _rule_goals(
    store: UserDataStore, recent: set[tuple[str, str | None]]
) -> list[PersonalAlert]:
    """Regole R1 (goal a rischio) e R2 (goal completato)."""
    out: list[PersonalAlert] = []
    goals = list_goals(store)
    for g in goals:
        # R2: completato (incluso se overshoot)
        if g.current_amount >= g.target_amount:
            key = (AlertKind.GOAL_ACHIEVED.value, g.goal_id)
            if key not in recent:
                out.append(
                    PersonalAlert(
                        kind=AlertKind.GOAL_ACHIEVED,
                        severity=AlertSeverity.INFO,
                        title=f"🎉 Goal '{g.name}' completato!",
                        detail=(
                            f"Hai raggiunto €{g.current_amount:,.0f} su "
                            f"€{g.target_amount:,.0f}."
                        ),
                        goal_id=g.goal_id,
                    )
                )
            continue  # se completato, non controlliamo "a rischio"

        # R1: a rischio
        if g.months_to_target <= 0:
            continue  # gia' scaduto, non utile generare allerta
        monthly_needed = g.required_monthly_savings()
        if (
            monthly_needed > _GOAL_AT_RISK_MONTHLY_THRESHOLD
            and g.progress_pct < _GOAL_AT_RISK_PROGRESS_MAX
        ):
            key = (AlertKind.GOAL_AT_RISK.value, g.goal_id)
            if key not in recent:
                out.append(
                    PersonalAlert(
                        kind=AlertKind.GOAL_AT_RISK,
                        severity=AlertSeverity.WARNING,
                        title=f"Goal '{g.name}' a rischio",
                        detail=(
                            f"Richiede €{monthly_needed:,.0f}/mese per "
                            f"{g.months_to_target} mesi. "
                            f"Progresso attuale: {g.progress_pct * 100:.0f}%."
                        ),
                        goal_id=g.goal_id,
                    )
                )
    return out


def _rule_wealth_thresholds(
    store: UserDataStore, recent: set[tuple[str, str | None]]
) -> list[PersonalAlert]:
    """Regole R3 (patrimonio sotto min) e R4 (patrimonio sopra target)."""
    out: list[PersonalAlert] = []
    try:
        summary = net_worth_summary(store=store)
    except Exception:  # noqa: BLE001 -- DB potrebbe non essere pronto
        return out
    nw = float(summary.get("net_worth", 0.0))
    thresholds = load_thresholds(store)
    min_thr = thresholds["min_alert"]
    tgt_thr = thresholds["target_alert"]

    if min_thr > 0 and nw < min_thr:
        key = (AlertKind.WEALTH_BELOW_MIN.value, None)
        if key not in recent:
            out.append(
                PersonalAlert(
                    kind=AlertKind.WEALTH_BELOW_MIN,
                    severity=AlertSeverity.CRITICAL,
                    title="⚠️ Patrimonio sotto soglia minima",
                    detail=(
                        f"Net Worth €{nw:,.0f} è sotto la soglia di "
                        f"allerta €{min_thr:,.0f}."
                    ),
                )
            )

    if tgt_thr > 0 and nw >= tgt_thr:
        key = (AlertKind.WEALTH_ABOVE_TARGET.value, None)
        if key not in recent:
            out.append(
                PersonalAlert(
                    kind=AlertKind.WEALTH_ABOVE_TARGET,
                    severity=AlertSeverity.INFO,
                    title="🎉 Patrimonio raggiunto soglia obiettivo!",
                    detail=(
                        f"Net Worth €{nw:,.0f} ha superato l'obiettivo "
                        f"€{tgt_thr:,.0f}."
                    ),
                )
            )
    return out


def _rule_negative_cashflow(
    store: UserDataStore, recent: set[tuple[str, str | None]]
) -> list[PersonalAlert]:
    """Regola R5: cashflow mese corrente negativo (spese > entrate)."""
    out: list[PersonalAlert] = []
    today = date.today()
    try:
        engine = CashFlowEngine()
        summary = engine.monthly_summary(_CURRENT_PROFILE_ID, today.year, today.month)
    except Exception:  # noqa: BLE001
        return out

    income = float(summary.get("income", 0.0))
    expense = float(summary.get("expense", 0.0))

    # Solo se ci sono dati: senza entrate ne' uscite registrate, no allerta
    if income <= 0 and expense <= 0:
        return out

    if expense > income:
        key = (AlertKind.NEGATIVE_CASHFLOW.value, None)
        if key not in recent:
            net = income - expense
            out.append(
                PersonalAlert(
                    kind=AlertKind.NEGATIVE_CASHFLOW,
                    severity=AlertSeverity.WARNING,
                    title=f"💸 Cashflow negativo per {today.strftime('%B %Y')}",
                    detail=(
                        f"Entrate €{income:,.0f}, uscite €{expense:,.0f}. "
                        f"Saldo netto: −€{abs(net):,.0f}. "
                        "Verifica le spese ricorrenti in P3."
                    ),
                )
            )
    return out


# ─────────────────────────────────────────────────── public api
def run_rules(store: UserDataStore | None = None) -> list[PersonalAlert]:
    """Esegue tutte le regole, persiste i nuovi alert, ritorna la lista.

    Idempotente entro la finestra di dedup (24h): chiamare 10 volte di
    seguito non genera 10 alert duplicati. Se invocata 25h dopo, gli
    stessi alert vengono rigenerati (intenzionale: lo stato persiste).
    """
    s = store or get_default_store()
    recent = _recent_alert_dedup_keys(s)

    new_alerts: list[PersonalAlert] = []
    new_alerts.extend(_rule_goals(s, recent))
    new_alerts.extend(_rule_wealth_thresholds(s, recent))
    new_alerts.extend(_rule_negative_cashflow(s, recent))

    for a in new_alerts:
        s.upsert(ALERT_TYPE, a.alert_id, a.to_payload())
        log.info(
            "personal_alert.generated",
            kind=a.kind.value,
            severity=a.severity.value,
            goal_id=a.goal_id,
        )

    return new_alerts
