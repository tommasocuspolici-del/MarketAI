"""RiskProfileBridge: collega risk questionnaire (P6 UI) -> InvestorProfile (Rule 22).

Risolve il gap segnalato in ULTERIORI_ERRORI.txt: dopo aver compilato il
questionario in P6, i dati venivano salvati in ``UserDataStore``
(JSON-su-SQLite di tipo ``risk_profile``) ma NON venivano mai propagati a
``InvestorProfile`` (tabella SQLite ``investor_profiles``), che e' la
SINGOLA fonte di verita' usata da:

  - ``SuitabilityChecker`` (Rule 22)
  - ``WealthSimulator`` (Monte Carlo)
  - ``PortfolioAllocator``
  - tutti i suggerimenti del personal layer

Senza questo bridge, il profilo restava puramente cosmetico.

Mapping:

  RiskQuestionnaire dimension      ->  InvestorProfile field
  ------------------------------------------------------------
  RiskProfile enum                 ->  RiskTolerance enum (1:1)
  suggested_max_drawdown_pct       ->  max_drawdown_pct
  dimension_scores['horizon']      ->  investment_horizon + horizon_years
  dimension_scores['capacity']     ->  liquidity_reserve_months (proxy)
  dimension_scores['knowledge']    ->  financial_knowledge (1-5)

I valori sono convertiti via funzioni esplicite ``_horizon_from_score``
ecc. — niente magia. Le scelte di mapping sono tracciate nei docstring
per audit.
"""
from __future__ import annotations

from personal.data_entry.risk_questionnaire import (
    RiskProfile,
    RiskProfileResult,
)
from personal.investor_profile.profile_loader import (
    ProfileLoader,
    get_profile_loader,
)
from personal.investor_profile.profile_model import (
    InvestmentHorizon,
    InvestorProfile,
    RiskTolerance,
)
from shared.exceptions import ProfileNotFoundError
from shared.logger import get_logger

__version__ = "7.1.2"

__all__ = [
    "DEFAULT_PROFILE_ID",
    "DEFAULT_PROFILE_NAME",
    "questionnaire_to_investor_profile",
    "safe_load_investor_profile",
    "save_questionnaire_to_investor_profile",
]

log = get_logger(__name__)

# Convenzione single-user: usiamo lo stesso ID anche in risk_questionnaire e
# in app_unified.py. Cosi' P6 e SuitabilityChecker riferiscono stesso profilo.
DEFAULT_PROFILE_ID = "current"
DEFAULT_PROFILE_NAME = "Profilo Utente"


# ─── mapping helpers ────────────────────────────────────────────────────
def _risk_tolerance_from(profile: RiskProfile) -> RiskTolerance:
    """Mapping diretto 1:1 fra i due enum (stessi 4 livelli)."""
    return {
        RiskProfile.CONSERVATIVE: RiskTolerance.CONSERVATIVE,
        RiskProfile.MODERATE: RiskTolerance.MODERATE,
        RiskProfile.AGGRESSIVE: RiskTolerance.AGGRESSIVE,
        RiskProfile.VERY_AGGRESSIVE: RiskTolerance.VERY_AGGRESSIVE,
    }[profile]


def _horizon_from_score(horizon_score: int) -> tuple[InvestmentHorizon, int]:
    """Deriva InvestmentHorizon e horizon_years dal punteggio dimensione (0-20).

    Mapping derivato dai test del questionario (vedi risk_questionnaire.QUESTIONS):
      - score 0-5  -> SHORT  (1-2 anni)   -> 2 anni
      - score 6-10 -> MEDIUM (2-7 anni)   -> 5 anni
      - score 11-15 -> LONG  (7-15 anni)  -> 10 anni
      - score 16-20 -> VERY_LONG (>15)    -> 20 anni
    """
    if horizon_score <= 5:
        return InvestmentHorizon.SHORT, 2
    if horizon_score <= 10:
        return InvestmentHorizon.MEDIUM, 5
    if horizon_score <= 15:
        return InvestmentHorizon.LONG, 10
    return InvestmentHorizon.VERY_LONG, 20


def _liquidity_months_from_capacity(capacity_score: int) -> int:
    """Deriva mesi di riserva liquida dal punteggio capacity (0-30).

    Approssimazione lineare:
      - score 0-7   -> 0 mesi  (capacita' molto bassa: niente cuscino liquido)
      - score 8-14  -> 3 mesi
      - score 15-21 -> 6 mesi
      - score 22-30 -> 12 mesi
    """
    if capacity_score <= 7:
        return 0
    if capacity_score <= 14:
        return 3
    if capacity_score <= 21:
        return 6
    return 12


def _knowledge_level_from_score(knowledge_score: int) -> int:
    """Deriva livello conoscenza 1-5 dal punteggio dimensione (0-20).

    Mapping in 5 buckets uniformi.
    """
    if knowledge_score <= 4:
        return 1
    if knowledge_score <= 8:
        return 2
    if knowledge_score <= 12:
        return 3
    if knowledge_score <= 16:
        return 4
    return 5


def _allowed_asset_classes_for(profile: RiskProfile) -> list[str]:
    """Asset class consentite in base al profilo.

    Convenzione progressiva: piu' aggressivo -> piu' classi sbloccate.
    Cash sempre presente come riserva.
    """
    if profile == RiskProfile.CONSERVATIVE:
        return ["bonds", "etf", "cash"]
    if profile == RiskProfile.MODERATE:
        return ["equity", "bonds", "etf", "cash"]
    if profile == RiskProfile.AGGRESSIVE:
        return ["equity", "bonds", "etf", "cash", "commodities"]
    return ["equity", "bonds", "etf", "cash", "commodities", "crypto"]


# ─── public api ────────────────────────────────────────────────────────────
def questionnaire_to_investor_profile(
    result: RiskProfileResult,
    *,
    profile_id: str = DEFAULT_PROFILE_ID,
    name: str = DEFAULT_PROFILE_NAME,
    base_currency: str = "EUR",
) -> InvestorProfile:
    """Converte un :class:`RiskProfileResult` in :class:`InvestorProfile`.

    Funzione PURA (no I/O): facilmente testabile in isolamento.

    Args:
        result: Risultato del questionario.
        profile_id: ID del profilo SQLite (default 'current').
        name: Nome leggibile del profilo.
        base_currency: Valuta base per i calcoli (default 'EUR').

    Returns:
        :class:`InvestorProfile` pronto per essere salvato in SQLite.
    """
    horizon_score = int(result.dimension_scores.get("horizon", 0))
    capacity_score = int(result.dimension_scores.get("capacity", 0))
    knowledge_score = int(result.dimension_scores.get("knowledge", 0))

    horizon_enum, horizon_years = _horizon_from_score(horizon_score)

    return InvestorProfile(
        profile_id=profile_id,
        name=name,
        risk_tolerance=_risk_tolerance_from(result.profile),
        max_drawdown_pct=float(result.suggested_max_drawdown_pct),
        investment_horizon=horizon_enum,
        horizon_years=horizon_years,
        liquidity_reserve_months=_liquidity_months_from_capacity(capacity_score),
        financial_knowledge=_knowledge_level_from_score(knowledge_score),
        allowed_asset_classes=_allowed_asset_classes_for(result.profile),
        excluded_sectors=[],
        excluded_countries=[],
        base_currency=base_currency,
    )


def save_questionnaire_to_investor_profile(
    result: RiskProfileResult,
    *,
    profile_id: str = DEFAULT_PROFILE_ID,
    name: str = DEFAULT_PROFILE_NAME,
    base_currency: str = "EUR",
    loader: ProfileLoader | None = None,
) -> InvestorProfile:
    """Converte E salva su SQLite (tabella ``investor_profiles``).

    Side-effect: chiama ``ProfileLoader.save()``. Se la tabella non esiste,
    SQLAlchemy generera' un errore — significa che le migration non sono
    state applicate.

    Args:
        result: Risultato del questionario.
        profile_id: ID del profilo SQLite (default 'current').
        name: Nome leggibile.
        base_currency: Valuta base.
        loader: ProfileLoader iniettabile per test. Default singleton.

    Returns:
        Il profilo persistito (utile per chaining).
    """
    profile = questionnaire_to_investor_profile(
        result,
        profile_id=profile_id,
        name=name,
        base_currency=base_currency,
    )
    persistor = loader or get_profile_loader()
    persistor.save(profile)
    log.info(
        "investor_profile.saved_from_questionnaire",
        profile_id=profile.profile_id,
        risk_tolerance=profile.risk_tolerance.value,
        max_drawdown_pct=profile.max_drawdown_pct,
        horizon_years=profile.horizon_years,
    )
    return profile


def safe_load_investor_profile(
    profile_id: str = DEFAULT_PROFILE_ID,
    loader: ProfileLoader | None = None,
) -> InvestorProfile | None:
    """Carica InvestorProfile o None se non esiste / DB non pronto.

    Helper di comodo per pagine UI che vogliono fare lookup senza eccezioni.
    """
    persistor = loader or get_profile_loader()
    try:
        return persistor.load(profile_id)
    except ProfileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001 -- DB non inizializzato, file mancante, ecc.
        log.warning(
            "investor_profile.load_failed",
            profile_id=profile_id,
            error=str(exc),
        )
        return None
