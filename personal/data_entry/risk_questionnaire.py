"""Questionario rischio esteso per profilo investitore (Rule 41).

Risolve "il profilo investitore ha solo 3 domande" della v6.
Il questionario calcola un punteggio rischio (0-100) basato su 12 domande
distribuite su 4 dimensioni:

  1. CAPACITA' (financial capacity to take risk)        -> 30 punti max
  2. TOLLERANZA EMOTIVA (psychological risk tolerance)  -> 30 punti max
  3. ORIZZONTE TEMPORALE                                -> 20 punti max
  4. CONOSCENZA E ESPERIENZA                            -> 20 punti max

Punteggio finale -> mappa a profilo {CONSERVATIVE | MODERATE | AGGRESSIVE | VERY_AGGRESSIVE}.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from personal.data_entry.user_data_store import UserDataStore, get_default_store

__version__ = "7.1.0"

__all__ = [
    "QUESTIONS",
    "Question",
    "RiskProfile",
    "RiskProfileResult",
    "compute_risk_profile",
    "load_saved_profile",
    "save_profile",
]

PROFILE_TYPE = "risk_profile"


class RiskProfile(str, Enum):
    """Macro-categorie di profilo rischio (output del questionario)."""

    CONSERVATIVE = "CONSERVATIVE"
    MODERATE = "MODERATE"
    AGGRESSIVE = "AGGRESSIVE"
    VERY_AGGRESSIVE = "VERY_AGGRESSIVE"


@dataclass(frozen=True, slots=True)
class Question:
    """Singola domanda del questionario."""

    qid: str
    dimension: str         # "capacity" | "tolerance" | "horizon" | "knowledge"
    text: str
    options: list[tuple[str, int]]  # (testo_opzione, punteggio)
    explanation: str = ""           # tooltip educativo


# ───────────────────────────────────────────────── catalogo domande
QUESTIONS: list[Question] = [
    # ====================== CAPACITA' (max 30 pt) ======================
    Question(
        qid="cap_income_stability",
        dimension="capacity",
        text="Quanto e' stabile la tua principale fonte di reddito?",
        options=[
            ("Molto instabile (autonomo senza contratti / commissioni)", 1),
            ("Variabile (commissioni + base, freelance con clienti ricorrenti)", 3),
            ("Stabile (stipendio mensile, contratto a termine)", 6),
            ("Molto stabile (contratto indeterminato, dipendente pubblico)", 8),
        ],
        explanation="Reddito stabile = puoi sopportare drawdown senza dover liquidare in perdita.",
    ),
    Question(
        qid="cap_emergency_fund",
        dimension="capacity",
        text="Quanti mesi di spese hai accantonati come fondo di emergenza?",
        options=[
            ("Meno di 1 mese", 0),
            ("1-3 mesi", 3),
            ("3-6 mesi", 6),
            ("Piu' di 6 mesi", 8),
        ],
        explanation=(
            "Il fondo di emergenza assorbe shock improvvisi (perdita lavoro, "
            "spese mediche) senza forzarti a vendere investimenti ai minimi."
        ),
    ),
    Question(
        qid="cap_loss_recoverability",
        dimension="capacity",
        text=(
            "Se il tuo portafoglio perdesse il 30% domani, quanti anni "
            "ti servirebbero per recuperare quella perdita SOLO con i risparmi "
            "(senza tener conto di rendimenti futuri)?"
        ),
        options=[
            ("Piu' di 10 anni", 1),
            ("5-10 anni", 4),
            ("2-5 anni", 7),
            ("Meno di 2 anni", 10),
        ],
        explanation=(
            "Misura la tua 'capacita' di assorbire una perdita. "
            "Chi ricostruisce velocemente puo' permettersi piu' rischio."
        ),
    ),
    Question(
        qid="cap_dependents",
        dimension="capacity",
        text="Quante persone dipendono economicamente da te?",
        options=[
            ("4 o piu'", 1),
            ("2-3", 2),
            ("1", 3),
            ("Nessuna (solo me stesso)", 4),
        ],
        explanation="Piu' persone dipendono da te, minore margine di rischio.",
    ),

    # ====================== TOLLERANZA EMOTIVA (max 30 pt) ======================
    Question(
        qid="tol_2008_reaction",
        dimension="tolerance",
        text=(
            "Immagina di aver investito €100.000. Dopo 6 mesi il portafoglio "
            "vale €70.000 (-30%, scenario tipo 2008). Cosa faresti?"
        ),
        options=[
            ("Venderei tutto: non sopporto altre perdite", 0),
            ("Venderei una parte per limitare i danni", 3),
            ("Manterrei la posizione, aspetterei la ripresa", 7),
            ("Comprerei altro: occasione di lungo periodo", 10),
        ],
        explanation=(
            "Il vero rischio non e' la volatilita': e' vendere ai minimi per "
            "panico. Le tue scelte teoriche raramente coincidono con quelle reali "
            "sotto stress, ma e' un buon proxy."
        ),
    ),
    Question(
        qid="tol_volatility",
        dimension="tolerance",
        text=(
            "Quale di questi tre portafogli sceglieresti per i prossimi 10 anni? "
            "(in base al peggior risultato annuale possibile)"
        ),
        options=[
            ("A: rendimento atteso 4%, peggior anno -8%", 1),
            ("B: rendimento atteso 6%, peggior anno -18%", 4),
            ("C: rendimento atteso 8%, peggior anno -32%", 8),
            ("D: rendimento atteso 10%, peggior anno -45%", 10),
        ],
        explanation=(
            "Il rendimento atteso e' inseparabile dal massimo drawdown. "
            "Scegliere D vuol dire poter vedere il portafoglio quasi dimezzarsi "
            "in un anno cattivo."
        ),
    ),
    Question(
        qid="tol_news_check",
        dimension="tolerance",
        text="Ogni quanto controlli il valore dei tuoi investimenti?",
        options=[
            ("Piu' volte al giorno", 1),
            ("Una volta al giorno", 3),
            ("Una volta a settimana", 7),
            ("Una volta al mese o meno", 10),
        ],
        explanation=(
            "Controllo ossessivo correla con decisioni emotive. Chi investe "
            "lungo periodo guarda raramente e gestisce meglio lo stress."
        ),
    ),

    # ====================== ORIZZONTE TEMPORALE (max 20 pt) ======================
    Question(
        qid="hor_when_use",
        dimension="horizon",
        text=(
            "Tra quanto tempo prevedi di utilizzare la maggior parte di questi soldi?"
        ),
        options=[
            ("Entro 1 anno", 1),
            ("1-3 anni", 3),
            ("3-7 anni", 6),
            ("7-15 anni", 8),
            ("Oltre 15 anni", 10),
        ],
        explanation=(
            "Equity ha senso solo se puoi tenere almeno 7-10 anni. Sotto i 3 "
            "anni la volatilita' rischia di costringerti a vendere in perdita."
        ),
    ),
    Question(
        qid="hor_age_bracket",
        dimension="horizon",
        text="In che fascia di eta' ti trovi?",
        options=[
            ("Oltre 65 anni", 2),
            ("55-65 anni", 4),
            ("40-55 anni", 6),
            ("25-40 anni", 8),
            ("Sotto i 25 anni", 10),
        ],
        explanation=(
            "Eta' = orizzonte residuo statistico. Piu' giovane = piu' tempo "
            "per recuperare drawdown e beneficiare del compound interest."
        ),
    ),

    # ====================== CONOSCENZA (max 20 pt) ======================
    Question(
        qid="know_experience",
        dimension="knowledge",
        text="Da quanti anni investi attivamente?",
        options=[
            ("Mai investito prima", 0),
            ("Meno di 1 anno", 2),
            ("1-3 anni", 4),
            ("3-7 anni", 6),
            ("Oltre 7 anni", 8),
        ],
    ),
    Question(
        qid="know_instruments",
        dimension="knowledge",
        text="Con quali strumenti hai operato direttamente in passato?",
        options=[
            ("Solo conti deposito / titoli di stato", 2),
            ("Anche fondi comuni / ETF azionari", 4),
            ("Anche azioni singole / obbligazioni corporate", 6),
            ("Anche derivati (futures, opzioni) o crypto", 8),
        ],
        explanation="Strumenti complessi richiedono comprensione dei rischi specifici.",
    ),
    Question(
        qid="know_concepts",
        dimension="knowledge",
        text=(
            "Quanti di questi concetti sapresti spiegare a un amico? "
            "(Sharpe ratio, Drawdown, Diversificazione, Beta)"
        ),
        options=[
            ("Nessuno", 0),
            ("1 o 2", 1),
            ("3", 2),
            ("Tutti e 4", 4),
        ],
    ),
]

# Punteggi massimi per dimensione (devono coincidere con la somma delle option max)
_DIMENSION_MAX = {
    "capacity": 30,
    "tolerance": 30,
    "horizon": 20,
    "knowledge": 20,
}


@dataclass(frozen=True, slots=True)
class RiskProfileResult:
    """Esito del questionario rischio."""

    total_score: int                # 0-100
    dimension_scores: dict[str, int]  # capacity, tolerance, horizon, knowledge
    profile: RiskProfile
    suggested_max_drawdown_pct: float
    suggested_equity_pct: float    # quota equity raccomandata
    answers: dict[str, str]         # qid -> testo opzione scelta


def compute_risk_profile(answers: dict[str, int]) -> RiskProfileResult:
    """Calcola il profilo rischio dato un dict {qid: punteggio}.

    Args:
        answers: mapping da qid alla opzione scelta (punteggio numerico).
    """
    by_question = {q.qid: q for q in QUESTIONS}
    dimension_scores: dict[str, int] = {d: 0 for d in _DIMENSION_MAX}
    answer_texts: dict[str, str] = {}

    for qid, score in answers.items():
        if qid not in by_question:
            continue
        q = by_question[qid]
        dimension_scores[q.dimension] += score
        # Recupera testo dell'opzione corrispondente
        for opt_text, opt_score in q.options:
            if opt_score == score:
                answer_texts[qid] = opt_text
                break

    total = sum(dimension_scores.values())

    # Mapping punteggio -> profilo
    if total < 35:
        profile = RiskProfile.CONSERVATIVE
        suggested_dd = 0.10
        suggested_eq = 0.20
    elif total < 55:
        profile = RiskProfile.MODERATE
        suggested_dd = 0.20
        suggested_eq = 0.50
    elif total < 75:
        profile = RiskProfile.AGGRESSIVE
        suggested_dd = 0.35
        suggested_eq = 0.75
    else:
        profile = RiskProfile.VERY_AGGRESSIVE
        suggested_dd = 0.50
        suggested_eq = 0.90

    return RiskProfileResult(
        total_score=total,
        dimension_scores=dimension_scores,
        profile=profile,
        suggested_max_drawdown_pct=suggested_dd,
        suggested_equity_pct=suggested_eq,
        answers=answer_texts,
    )


# ─────────────────────────────────────────── persistence
_PROFILE_ID = "current"


def save_profile(
    result: RiskProfileResult,
    raw_answers: dict[str, int],
    store: UserDataStore | None = None,
) -> None:
    """Salva il risultato del questionario."""
    s = store or get_default_store()
    payload: dict[str, Any] = {
        "total_score": result.total_score,
        "dimension_scores": result.dimension_scores,
        "profile": result.profile.value,
        "suggested_max_drawdown_pct": result.suggested_max_drawdown_pct,
        "suggested_equity_pct": result.suggested_equity_pct,
        "raw_answers": raw_answers,
        "answer_texts": result.answers,
        "completed_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    s.upsert(PROFILE_TYPE, _PROFILE_ID, payload)


def load_saved_profile(
    store: UserDataStore | None = None,
) -> RiskProfileResult | None:
    """Carica l'ultimo risultato salvato."""
    s = store or get_default_store()
    rec = s.get(PROFILE_TYPE, _PROFILE_ID)
    if rec is None:
        return None
    p = rec.payload
    try:
        return RiskProfileResult(
            total_score=int(p["total_score"]),
            dimension_scores={k: int(v) for k, v in p["dimension_scores"].items()},
            profile=RiskProfile(p["profile"]),
            suggested_max_drawdown_pct=float(p["suggested_max_drawdown_pct"]),
            suggested_equity_pct=float(p["suggested_equity_pct"]),
            answers=p.get("answer_texts", {}),
        )
    except (KeyError, ValueError, TypeError):
        return None


