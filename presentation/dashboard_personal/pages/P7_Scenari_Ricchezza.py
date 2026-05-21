# ruff: noqa: N999
"""P7 — Scenari Ricchezza (v7.1).

Risolve "il calcolo FIRE non spiega come arriva al risultato" della v6.
Aggiunge:
  - sezione "Come funziona FIRE" con derivazione visiva
  - spiegazione dei 4% Rule (SWR) integrata
  - breakdown dello scenario in step verificabili dall'utente

Il calcolo Monte Carlo e' invariato (usa il WealthSimulator esistente).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from presentation.ui.components.metric_card import (
    MetricSpec,
    render_metric_row,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "8.2.0"

__all__ = ["body_scenari_ricchezza"]


def _load_networth_for_fire() -> float:
    """Carica patrimonio netto attuale come punto di partenza simulazione."""
    try:
        from personal.data_entry.networth_editor import net_worth_summary
        return float(net_worth_summary().get("net_worth", 0.0))
    except Exception:
        return 0.0


def _explain_fire(st_module, age, expenses, savings, return_mean) -> None:  # pragma: no cover
    """Spiega step-by-step come si arriva al numero FIRE.

    Mostra all'utente i 4 passaggi concettuali e i numeri intermedi.
    """
    st = st_module
    target_capital = expenses * 25  # regola del 4% (SWR)

    with st.expander("🧭 Come funziona il calcolo FIRE — passo per passo", expanded=True):
        st.markdown(
            f"""
**Cosa significa FIRE?**

FIRE = *Financial Independence, Retire Early*: avere un capitale
investito sufficiente da generare, tramite il proprio rendimento,
le spese annue di cui hai bisogno per vivere — *senza dover lavorare*.

---

**Passo 1 · Quanto capitale ti serve?**

La regola del **4% (SWR)** di Bengen (1994) dice che, in un portafoglio
diversificato, puoi prelevare ogni anno il 4% del capitale iniziale
(aggiustato per inflazione) senza esaurirlo in 30 anni di pensione.

Tradotto: il tuo capitale FIRE è circa **25 volte** le tue spese annue.

```
Capitale_FIRE = Spese_annue × 25
              = €{expenses:,.0f} × 25
              = €{target_capital:,.0f}
```

---

**Passo 2 · Quanto manca al traguardo?**

Il simulatore Monte Carlo tiene conto di:
- patrimonio iniziale (quello che hai oggi);
- contributi mensili (ciò che riesci a risparmiare);
- rendimento atteso del portafoglio ({return_mean * 100:.1f}% medio annuo)
  con la sua volatilità tipica;
- 1.000-10.000 simulazioni di percorsi possibili (good case / bad case).

L'età FIRE è la prima età in cui ≥80% delle simulazioni superano il
target di €{target_capital:,.0f}.

---

**Passo 3 · Perché Monte Carlo e non un calcolo deterministico?**

Un calcolo a tasso fisso ("se rendo il 7% ogni anno...") è una bugia.
I rendimenti veri oscillano: gli anni cattivi all'inizio del percorso
sono *molto* più dannosi degli anni cattivi alla fine
(*sequence-of-returns risk*). Monte Carlo cattura questo effetto.

---

**Passo 4 · Perché ci sono diversi esiti possibili?**

Per definizione il futuro è incerto. Il simulatore mostra:
- **scenario mediano** (50% probabilità): risultato più realistico;
- **scenario pessimistico** (10° percentile): se le cose vanno male;
- **scenario ottimistico** (90° percentile): se va tutto bene.

Il risultato che vedi non è una promessa — è la mediana di migliaia
di possibili futuri.
"""
        )


def body_scenari_ricchezza(tokens: DesignTokens) -> None:  # pragma: no cover
    """Body Streamlit della pagina P7 v7.1."""
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

    cols_top = st.columns([4, 1])
    with cols_top[1]:
        if st.button("🔄 Aggiorna", key="p7_refresh"):
            st.cache_data.clear()
            st.rerun()

    # Tenta import dei simulatori esistenti
    try:
        from personal.wealth_scenarios import RetirementSimulator, WealthSimulator
    except ImportError:
        st.error("⚠️ Modulo personal.wealth_scenarios non disponibile.")
        return

    tab_mc, tab_fire = st.tabs(["📊 Monte Carlo Patrimonio", "🔥 FIRE Calculator"])

    # ─────────────────────────────────────── Monte Carlo
    with tab_mc:
        render_section_header(
            "Simulazione Monte Carlo del patrimonio futuro",
            "Migliaia di simulazioni stocastiche dell'evoluzione del tuo patrimonio.",
        )
        cols = st.columns(4)
        initial = cols[0].number_input("Patrimonio iniziale (€)", value=50_000.0, step=1_000.0)
        monthly = cols[1].number_input("Risparmio mensile (€)", value=1_000.0, step=100.0)
        years = cols[2].slider("Orizzonte (anni)", 5, 40, 20)
        n_sim = cols[3].selectbox("Simulazioni", [1_000, 5_000, 10_000], index=2)

        with st.expander("📚 Cosa significano i parametri?", expanded=False):
            st.markdown(
                "**Rendimento atteso annuo: 7%** — ipotesi storica per "
                "portafoglio bilanciato globale (60% azioni, 40% obbligazioni).\n\n"
                "**Volatilità annua: 15%** — deviazione standard tipica di un "
                "portafoglio bilanciato. In ~68% degli anni il rendimento sarà "
                "tra -8% e +22%; in ~95% tra -23% e +37%."
            )

        # ── Parametri da engine via bridge (Roadmap Sett. 8) ──────────
        eq_return = 0.07
        eq_vol    = 0.15
        try:
            from bridge.market_context_builder import build_market_context
            mctx      = build_market_context()
            eq_return = mctx.equity_expected_return
            eq_vol    = mctx.equity_volatility
            st.caption(
                f"📡 Parametri engine: rendimento atteso {eq_return*100:.1f}% "
                f"| volatilità {eq_vol*100:.1f}% "
                f"| regime {mctx.current_regime} | VIX {mctx.vix:.1f}"
            )
        except Exception as _exc:
            st.caption(f"⚠️ Parametri engine non disponibili, uso default: {_exc}")

        if st.button("🎲 Simula", type="primary"):
            sim = WealthSimulator()
            result = sim.simulate(
                initial_wealth=initial,
                monthly_savings=monthly,
                annual_return_mean=eq_return,
                annual_return_std=eq_vol,
                years=years,
                n_simulations=int(n_sim),
                seed=None,
            )
            try:
                from presentation.ui.components.wealth_scenario_chart import (
                    render_wealth_scenario_chart,
                )
                render_wealth_scenario_chart(tokens, result)
            except ImportError:
                pass

            metrics = [
                MetricSpec(
                    term="Mediana finale",
                    value=getattr(result, "final_p50", 0.0),
                    format_spec=",.0f",
                    unit_override="€",
                ),
                MetricSpec(
                    term="Pessimistico",
                    value=getattr(result, "final_p10", 0.0),
                    format_spec=",.0f",
                    unit_override="€",
                ),
                MetricSpec(
                    term="Ottimistico",
                    value=getattr(result, "final_p90", 0.0),
                    format_spec=",.0f",
                    unit_override="€",
                ),
            ]
            render_metric_row(tokens, metrics)

    # ─────────────────────────────────────── FIRE
    with tab_fire:
        render_section_header(
            "🔥 FIRE Calculator — quanto ci vuole?",
            "Stima l'età alla quale puoi smettere di lavorare basandoti sulle tue spese.",
        )
        cols = st.columns(3)
        age = cols[0].number_input("Età attuale", value=30, min_value=18, max_value=80)
        expenses = cols[1].number_input(
            "Spese annue (€)",
            value=30_000.0,
            step=1_000.0,
            help="Quanto ti serve all'anno per vivere come oggi.",
        )
        fire_savings = cols[2].number_input(
            "Risparmio FIRE/mese (€)",
            value=2_000.0,
            step=100.0,
        )
        initial = st.number_input(
            "Patrimonio investito attuale (€)",
            value=50_000.0,
            step=1_000.0,
        )

        target_capital = expenses * 25
        st.info(
            f"🎯 **Capitale FIRE necessario: €{target_capital:,.0f}** "
            f"(= €{expenses:,.0f} x 25, regola del 4%)"
        )

        if st.button("🔥 Calcola FIRE", type="primary"):
            ret_sim = RetirementSimulator()
            fire = ret_sim.find_fire_age(
                current_age=int(age),
                annual_expenses=expenses,
                initial_wealth=initial,
                monthly_savings=fire_savings,
                annual_return_mean=0.07,
                annual_return_std=0.15,
                n_simulations=2_000,
                seed=None,
            )
            if fire.fire_age is not None:
                st.success(
                    f"### 🎉 FIRE raggiungibile a **{fire.fire_age} anni**\n\n"
                    f"**Mancano {fire.years_to_fire} anni** dalla tua età attuale.  \n"
                    f"**Probabilità di successo:** {fire.probability:.0%}"
                )
            else:
                st.error(
                    "⚠️ FIRE non raggiungibile entro l'orizzonte massimo (80 anni). "
                    "Strategie possibili: aumentare il risparmio mensile, "
                    "ridurre le spese annue, o accettare un orizzonte più lungo."
                )

        # Spiegazione esplicita del calcolo
        _explain_fire(st, age, expenses, fire_savings, 0.07)


if __name__ == "__main__":  # pragma: no cover
    render_page("Scenari Ricchezza", "🚀", body_scenari_ricchezza)
