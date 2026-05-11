"""UI Streamlit del questionario rischio (split di risk_questionnaire.py).

Separato per rispettare Rule 2 (max 400 righe per file).
"""
from __future__ import annotations

from personal.data_entry.risk_questionnaire import (
    QUESTIONS,
    RiskProfileResult,
    compute_risk_profile,
)

__version__ = "7.1.0"

__all__ = ["render_risk_questionnaire"]


def render_risk_questionnaire(
    *,
    key: str = "risk_q",
) -> tuple[RiskProfileResult, dict[str, int]] | None:  # pragma: no cover -- Streamlit
    """Renderizza il questionario completo.

    Returns:
        (RiskProfileResult, raw_answers) se l'utente conferma, None altrimenti.
    """
    try:
        import streamlit as st
    except ImportError:
        return None

    st.markdown(
        "Rispondi a tutte le domande per ottenere un profilo di rischio "
        "completo. Le domande coprono **4 dimensioni**: capacita' "
        "finanziaria, tolleranza emotiva, orizzonte temporale e conoscenza. "
        "Il punteggio totale (0-100) determina il profilo."
    )

    dim_titles = {
        "capacity": "💰 1. Capacita' finanziaria di sostenere il rischio",
        "tolerance": "🧘 2. Tolleranza emotiva alle perdite",
        "horizon": "⏳ 3. Orizzonte temporale",
        "knowledge": "📚 4. Conoscenza ed esperienza",
    }

    answers: dict[str, int] = {}
    for dim, dim_title in dim_titles.items():
        st.markdown(f"### {dim_title}")
        questions_in_dim = [q for q in QUESTIONS if q.dimension == dim]
        for q in questions_in_dim:
            option_labels = [opt[0] for opt in q.options]
            option_scores = [opt[1] for opt in q.options]
            choice_idx = st.radio(
                q.text,
                options=range(len(option_labels)),
                format_func=lambda i, lbls=option_labels: lbls[i],
                key=f"{key}_{q.qid}",
                index=None,
            )
            if q.explanation:
                st.caption(f"ⓘ {q.explanation}")
            if choice_idx is not None:
                answers[q.qid] = option_scores[choice_idx]

    answered = len(answers)
    total = len(QUESTIONS)
    st.progress(answered / total, text=f"{answered} su {total} risposte")

    if answered < total:
        st.info("Rispondi a tutte le domande per calcolare il profilo.")
        return None

    if st.button("📊 Calcola il mio profilo", type="primary", key=f"{key}_submit"):
        result = compute_risk_profile(answers)
        return result, answers
    return None
