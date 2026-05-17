# ruff: noqa: N999
"""P6 — Profilo Investitore (v7.1).

Risolve "il profilo ha solo 3 domande" della v6.
Questionario esteso a 12 domande su 4 dimensioni: capacita' finanziaria,
tolleranza emotiva, orizzonte temporale, conoscenza ed esperienza.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from personal.data_entry.risk_questionnaire import (
    RiskProfile,
    RiskProfileResult,
    load_saved_profile,
    save_profile,
)
from personal.data_entry.risk_questionnaire_ui import render_risk_questionnaire
from personal.investor_profile import (
    DEFAULT_PROFILE_ID,
    DEFAULT_PROFILE_NAME,
    safe_load_investor_profile,
    save_questionnaire_to_investor_profile,
)
from presentation.ui.components.metric_card import (
    MetricSpec,
    render_metric_row,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page
from presentation.ui.session_keys import SK

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.2"

__all__ = ["body_profilo_investitore"]


_PROFILE_LABELS = {
    RiskProfile.CONSERVATIVE: "🛡️ CONSERVATIVO",
    RiskProfile.MODERATE: "⚖️ MODERATO",
    RiskProfile.AGGRESSIVE: "📈 AGGRESSIVO",
    RiskProfile.VERY_AGGRESSIVE: "🚀 MOLTO AGGRESSIVO",
}

_PROFILE_DESCRIPTIONS = {
    RiskProfile.CONSERVATIVE: (
        "Priorita' alla preservazione del capitale. "
        "Equity tipica: 10-30%. Drawdown massimo accettato: 10%. "
        "Adatto a chi e' vicino al pensionamento, ha bassa tolleranza emotiva, "
        "o ha bisogno del capitale entro 2-3 anni."
    ),
    RiskProfile.MODERATE: (
        "Equilibrio tra crescita e stabilita'. "
        "Equity tipica: 40-60%. Drawdown massimo accettato: 20%. "
        "Tipico per investitori con orizzonte 5-10 anni, "
        "tolleranza media alle oscillazioni di mercato."
    ),
    RiskProfile.AGGRESSIVE: (
        "Crescita prioritaria, accettazione di volatilita' significativa. "
        "Equity tipica: 70-85%. Drawdown massimo accettato: 35%. "
        "Adatto a investitori giovani con orizzonte > 10 anni e "
        "stabilita' lavorativa."
    ),
    RiskProfile.VERY_AGGRESSIVE: (
        "Massima crescita, accettazione di drawdown anche severi. "
        "Equity tipica: 90-100%, possibile leva o concentrazione. "
        "Drawdown massimo accettato: 50%+. Adatto SOLO a investitori con "
        "orizzonte > 15 anni, alta capacita' finanziaria, esperienza solida."
    ),
}


def _render_profile_summary(tokens, st_module, result: RiskProfileResult) -> None:  # pragma: no cover
    """Mostra il riepilogo del profilo corrente."""
    st = st_module
    render_section_header("📊 Profilo corrente")
    label = _PROFILE_LABELS[result.profile]
    desc = _PROFILE_DESCRIPTIONS[result.profile]

    st.markdown(f"### {label}")
    st.markdown(f"**Punteggio totale:** {result.total_score}/100")
    st.info(desc)

    # Decomposizione punteggi per dimensione
    st.markdown("**Punteggio per dimensione:**")
    metrics = [
        MetricSpec(
            term=f"Capacità",
            value=result.dimension_scores.get("capacity", 0),
            format_spec="d",
            unit_override="/30",
        ),
        MetricSpec(
            term=f"Tolleranza",
            value=result.dimension_scores.get("tolerance", 0),
            format_spec="d",
            unit_override="/30",
        ),
        MetricSpec(
            term=f"Orizzonte",
            value=result.dimension_scores.get("horizon", 0),
            format_spec="d",
            unit_override="/20",
        ),
        MetricSpec(
            term=f"Conoscenza",
            value=result.dimension_scores.get("knowledge", 0),
            format_spec="d",
            unit_override="/20",
        ),
    ]
    render_metric_row(tokens, metrics)

    st.divider()
    render_section_header("🎯 Allocazione raccomandata")
    cols = st.columns(2)
    with cols[0]:
        st.metric(
            "Quota equity suggerita",
            f"{result.suggested_equity_pct * 100:.0f}%",
        )
        st.caption(
            "Percentuale del portafoglio in azioni/ETF azionari. "
            "Il resto in obbligazioni, cash, alternativi."
        )
    with cols[1]:
        st.metric(
            "Drawdown massimo accettabile",
            f"{result.suggested_max_drawdown_pct * 100:.0f}%",
        )
        st.caption(
            "Massima caduta peak-to-trough che il portafoglio dovrebbe "
            "esperire considerato il tuo profilo."
        )


def body_profilo_investitore(tokens: DesignTokens) -> None:  # pragma: no cover
    """Body Streamlit della pagina P6 v7.1."""
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="p6_refresh"):
            st.cache_data.clear()
            st.rerun()

    saved = load_saved_profile()

    if saved is not None:
        _render_profile_summary(tokens, st, saved)
        st.divider()
        # v7.1.2: mostra che il profilo e' attivo a livello engine (Rule 22)
        engine_profile = safe_load_investor_profile(DEFAULT_PROFILE_ID)
        if engine_profile is not None:
            st.success(
                f"🔗 **Profilo attivo nell'engine:** "
                f"`{engine_profile.risk_tolerance.value}` · "
                f"max DD {engine_profile.max_drawdown_pct * 100:.0f}% · "
                f"orizzonte {engine_profile.horizon_years} anni · "
                f"asset class consentite: {', '.join(engine_profile.allowed_asset_classes)}"
            )
        else:
            st.warning(
                "⚠️ Il profilo e' salvato nel questionario ma NON e' ancora "
                "attivo a livello engine. Rifai il questionario per propagarlo."
            )

        render_section_header(
            "🔄 Rifai il questionario",
            "Le tue circostanze cambiano nel tempo. Rifai il test ogni 1-2 anni o quando cambiano lavoro/famiglia/orizzonte.",
        )
        if not st.session_state.get(SK.SHOW_QUESTIONNAIRE):
            if st.button("🔁 Rifai il questionario", type="secondary"):
                st.session_state[SK.SHOW_QUESTIONNAIRE] = True
                st.rerun()
            return
    else:
        render_section_header(
            "🧭 Definisci il tuo profilo investitore",
            "Rispondi al questionario per ottenere un profilo di rischio personalizzato.",
        )

    # Render del questionario
    questionnaire_result = render_risk_questionnaire(key="risk_q_v71")
    if questionnaire_result is not None:
        result, raw_answers = questionnaire_result
        # 1. Salva storico questionario in UserDataStore (raw_answers etc.)
        save_profile(result, raw_answers)
        # 2. v7.1.2: propaga al motore via InvestorProfile (Rule 22) —
        #    senza questo passaggio, il profilo non era usato per filtrare
        #    suggerimenti nel resto dell'app.
        bridge_ok = True
        try:
            save_questionnaire_to_investor_profile(
                result,
                profile_id=DEFAULT_PROFILE_ID,
                name=DEFAULT_PROFILE_NAME,
                base_currency="EUR",
            )
        except Exception as exc:  # noqa: BLE001 -- DB potrebbe non essere pronto
            bridge_ok = False
            st.warning(
                f"⚠️ Profilo salvato ma non propagato all'engine: {exc}. "
                "I suggerimenti del motore potrebbero non essere personalizzati. "
                "Verifica che le migration SQLite siano state applicate."
            )
        st.session_state.pop(SK.SHOW_QUESTIONNAIRE, None)
        if bridge_ok:
            st.success(
                f"✅ Profilo salvato: {_PROFILE_LABELS[result.profile]} · "
                f"propagato all'engine per filtrare i suggerimenti (Rule 22)."
            )
        else:
            st.info(
                f"Profilo salvato in locale: {_PROFILE_LABELS[result.profile]}."
            )
        st.balloons()
        st.rerun()


if __name__ == "__main__":  # pragma: no cover
    render_page("Profilo Investitore", "👤", body_profilo_investitore)
