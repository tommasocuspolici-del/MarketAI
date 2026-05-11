# ruff: noqa: N999
"""P2 — Portafoglio eToro (v7.1.1).

Bugfix v7.1.1:
  - Aggiunto import via API ufficiale eToro (preferito) — sostituisce il
    bisogno dell'utente di scaricare manualmente l'XLSX Account Statement.
  - Parser XLSX rimane come FALLBACK per chi non ha credenziali API o
    se l'API e' temporaneamente non raggiungibile.

La pagina ha tre tab:
  1. Posizioni — lista CRUD, manual entry form
  2. Import — API eToro (preferito) + XLSX fallback
  3. Metriche — TWR/Sharpe/VaR ecc. ognuna con tooltip spiegato
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from personal.data_entry.etoro_importer import (
    EtoroImporter,
    EtoroImportError,
    EtoroImportResult,
)
from personal.data_entry.position_form import (
    PositionInput,
    delete_position,
    list_positions,
    render_position_form,
    save_position,
)
from presentation.ui.components.metric_card import (
    MetricSpec,
    render_metric_row,
)
from presentation.ui.layout import render_section_header
from presentation.ui.page_factory import render_page

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.1.1"

__all__ = ["body_portafoglio_etoro"]


def _kpi_specs_demo() -> tuple[list[MetricSpec], list[MetricSpec]]:
    """Costruisce la riga di metriche performance e risk con valori demo."""
    perf = [
        MetricSpec(term="TWR", value=0.0940, format_spec=".2%", delta=0.094, delta_pct=False),
        MetricSpec(term="MWR", value=0.0870, format_spec=".2%", delta=0.087, delta_pct=False),
        MetricSpec(term="Alpha", value=0.0120, format_spec=".2%", delta=0.012, delta_pct=False),
        MetricSpec(term="Sharpe", value=0.94, format_spec=".2f"),
    ]
    risk = [
        MetricSpec(term="VaR 95%", value=-0.042, format_spec=".2%"),
        MetricSpec(term="CVaR 95%", value=-0.068, format_spec=".2%"),
        MetricSpec(term="Beta vs S&P", value=0.82, format_spec=".2f"),
        MetricSpec(term="Max DD", value=-0.124, format_spec=".2%"),
    ]
    return perf, risk


def _render_review_and_import(
    st_module, result: EtoroImportResult
) -> None:  # pragma: no cover -- Streamlit
    """Mostra anteprima + grid editabile + bottone import per qualsiasi sorgente."""
    st = st_module
    df = result.positions
    n_rows = len(df)
    n_missing_ticker = (
        int(df["ticker"].isna().sum()) if "ticker" in df.columns else 0
    )
    n_missing_qty = (
        int(df["quantity"].isna().sum()) if "quantity" in df.columns else 0
    )
    n_warn = n_missing_ticker + n_missing_qty

    badge = "🌐 API eToro" if result.source == "api" else "📄 XLSX"
    if n_warn > 0:
        st.warning(
            f"⚠️ {badge} - {n_rows} posizioni · "
            f"{n_warn} righe con campi mancanti "
            f"({n_missing_ticker} senza ticker, {n_missing_qty} senza quantita'). "
            f"Modifica nel grid prima di confermare."
        )
    else:
        st.success(f"✅ {badge} - {n_rows} posizioni parsate senza errori critici.")

    if result.notes:
        st.caption(f"ℹ️ {result.notes}")

    st.caption(
        "📝 Modifica direttamente la tabella per correggere i dati prima "
        "dell'import. Le righe critiche non confermate non saranno importate."
    )

    visible_cols = [
        "ticker", "direction", "quantity", "open_price",
        "current_price", "open_date", "currency",
    ]
    visible_df = df[[c for c in visible_cols if c in df.columns]].copy()
    edited = st.data_editor(
        visible_df,
        num_rows="dynamic",
        use_container_width=True,
        key=f"etoro_review_editor_{result.source}",
    )

    cols = st.columns([1, 3])
    with cols[0]:
        if st.button(
            "✅ Conferma import",
            type="primary",
            key=f"etoro_confirm_{result.source}",
        ):
            imported = 0
            for _, row in edited.iterrows():
                if pd.isna(row.get("ticker")) or pd.isna(row.get("quantity")):
                    continue
                try:
                    pos = PositionInput(
                        ticker=str(row["ticker"]),
                        exchange="ALTRO",
                        quantity=float(row["quantity"]),
                        avg_cost=float(
                            row.get("open_price")
                            or row.get("current_price")
                            or 1.0
                        ),
                        current_price=float(row["current_price"])
                        if pd.notna(row.get("current_price"))
                        else None,
                        open_date=row["open_date"].date()
                        if pd.notna(row.get("open_date"))
                        else pd.Timestamp.today().date(),
                        direction=str(row.get("direction") or "LONG"),
                        currency=str(row.get("currency") or "USD"),
                        notes=f"source={result.source}",
                        source="etoro_import",
                    )
                except (ValueError, TypeError):
                    continue
                save_position(pos)
                imported += 1
            st.success(f"💾 Importate {imported} posizioni nel portafoglio.")
            st.rerun()
    with cols[1]:
        st.caption("Le posizioni esistenti con stesso ID non vengono duplicate.")


def _render_import_tab(st_module) -> None:  # pragma: no cover -- Streamlit
    """Tab di import unificato: API eToro (preferito) + XLSX fallback (Rule 42)."""
    st = st_module
    importer = EtoroImporter()

    render_section_header(
        "📥 Import posizioni eToro",
        "Sceglie automaticamente API eToro se le credenziali sono configurate, "
        "altrimenti chiede il file XLSX.",
    )

    # Banner stato credenziali
    if importer.has_api_credentials:
        st.success(importer.credential_status_message)
    else:
        st.info(importer.credential_status_message)

    # Sub-tab per scegliere esplicitamente la sorgente
    api_tab, xlsx_tab, help_tab = st.tabs(
        ["🌐 API eToro (preferito)", "📄 File XLSX (fallback)", "❓ Come ottenere le chiavi API"]
    )

    # ─────────────────────────────────────────────────── API tab
    with api_tab:
        if not importer.has_api_credentials:
            st.warning(
                "🔑 Credenziali API eToro non configurate. "
                "Vai alla scheda *'Come ottenere le chiavi API'* per istruzioni."
            )
        else:
            st.markdown(
                "Premi il bottone qui sotto per recuperare le posizioni "
                "aperte direttamente dal tuo account eToro tramite API ufficiale."
            )
            if st.button(
                "🌐 Recupera posizioni da eToro API",
                type="primary",
                key="etoro_api_fetch",
            ):
                with st.spinner("Sto contattando l'API eToro..."):
                    try:
                        result = importer.import_via_api()
                        st.session_state["etoro_import_result_api"] = result
                    except EtoroImportError as exc:
                        st.error(f"❌ {exc}")
                    except Exception as exc:  # pragma: no cover  # noqa: BLE001
                        st.error(
                            f"❌ Errore inatteso durante la chiamata API: "
                            f"{type(exc).__name__}: {exc}"
                        )

            api_result = st.session_state.get("etoro_import_result_api")
            if api_result is not None:
                _render_review_and_import(st, api_result)

    # ─────────────────────────────────────────────────── XLSX tab
    with xlsx_tab:
        st.markdown(
            "Usa questa modalita' se non hai ancora configurato l'API "
            "oppure come backup nel caso l'API sia momentaneamente "
            "irraggiungibile."
        )
        uploaded = st.file_uploader(
            "Seleziona il file Account Statement .xlsx",
            type=["xlsx"],
            key="etoro_uploader_v711",
            help=(
                "Esporta da eToro: Web -> Portfolio -> Account Statement, "
                "scegli il periodo, scarica come Excel (.xlsx)."
            ),
        )
        if uploaded is None:
            st.info(
                "Carica il file XLSX per visualizzare l'anteprima delle posizioni."
            )
        else:
            try:
                result = importer.import_via_xlsx(uploaded)
                st.session_state["etoro_import_result_xlsx"] = result
            except EtoroImportError as exc:
                st.error(f"❌ {exc}")
            xlsx_result = st.session_state.get("etoro_import_result_xlsx")
            if xlsx_result is not None:
                _render_review_and_import(st, xlsx_result)

    # ─────────────────────────────────────────────────── Help tab
    with help_tab:
        st.markdown(
            """
### 📋 Procedura per attivare l'API eToro

L'API ufficiale eToro permette di sincronizzare automaticamente le tue
posizioni senza dover scaricare manualmente l'Account Statement.

**1. Pre-requisiti:**
- Account eToro con verifica completa (KYC)
- Account "Real" (non solo demo) per accedere alle posizioni reali

**2. Genera le chiavi API:**

1. Vai su [eToro Settings → Trade](https://www.etoro.com/settings/trade)
2. Clicca su **Get API Keys**
3. Seleziona i permessi: **Read** è sufficiente per leggere il portfolio
   (Write serve solo se vuoi eseguire ordini, che NON facciamo qui)
4. Conferma con il codice SMS di verifica
5. Copia **API Key** (`x-api-key`) e **User Key** (`x-user-key`)

**3. Salva le chiavi in `.env`:**

Apri (o crea) il file `.env` nella cartella del progetto e aggiungi:

```
ETORO_API_KEY=la_tua_api_key_qui
ETORO_USER_KEY=la_tua_user_key_qui
```

**4. Riavvia l'app** per caricare le nuove variabili.

⚠️ **NON committare il file `.env`** su Git: contiene segreti personali.
La directory `.gitignore` del progetto lo esclude gia'.

**Documentazione ufficiale:**
[api-portal.etoro.com/getting-started/authentication](https://api-portal.etoro.com/getting-started/authentication)
            """
        )


def _render_positions_tab(st_module) -> None:  # pragma: no cover -- Streamlit
    """Tab di gestione manuale posizioni (Rule 41)."""
    st = st_module
    render_section_header("💼 Posizioni in portafoglio")

    positions = list_positions()
    if not positions:
        st.info(
            "Nessuna posizione presente. Aggiungi una posizione manualmente "
            "qui sotto, oppure importa da eToro nella tab dedicata."
        )
    else:
        rows = [
            {
                "Ticker": p.ticker,
                "Borsa": p.exchange,
                "Dir.": p.direction,
                "Qta": p.quantity,
                "Carico": p.avg_cost,
                "Valuta": p.currency,
                "Data apertura": p.open_date.isoformat(),
                "Origine": "📥 Import" if p.source == "etoro_import" else "✏️ Manuale",
            }
            for p in positions
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
        ticker_list = [f"{p.ticker} ({p.position_id[:6]})" for p in positions]
        selected_label = st.selectbox(
            "Seleziona posizione da modificare/eliminare",
            options=["—"] + ticker_list,
            key="position_selector",
        )
        if selected_label != "—":
            idx = ticker_list.index(selected_label)
            selected = positions[idx]
            edit_col, delete_col = st.columns([3, 1])
            with edit_col:
                edited = render_position_form(selected, key="edit_position_form")
                if edited is not None:
                    save_position(edited)
                    st.success(f"✅ Posizione {edited.ticker} aggiornata.")
                    st.rerun()
            with delete_col:
                if st.button(
                    "🗑️ Elimina posizione",
                    type="secondary",
                    key="delete_position_btn",
                ):
                    st.session_state["confirm_delete_position"] = selected.position_id
                if st.session_state.get("confirm_delete_position") == selected.position_id:
                    st.warning("⚠️ Sei sicuro?")
                    if st.button("Conferma eliminazione", key="confirm_del"):
                        delete_position(selected.position_id)
                        del st.session_state["confirm_delete_position"]
                        st.success("Posizione eliminata.")
                        st.rerun()

    st.divider()
    new_pos = render_position_form(key="new_position_form")
    if new_pos is not None:
        save_position(new_pos)
        st.success(f"✅ Posizione {new_pos.ticker} aggiunta al portafoglio.")
        st.rerun()


def _render_metrics_tab(tokens, st_module) -> None:  # pragma: no cover -- Streamlit
    """Tab di metriche performance e rischio, ognuna esplicitata (Rule 33)."""
    st = st_module
    render_section_header(
        "📊 Performance del portafoglio",
        "Ogni metrica ha una spiegazione dettagliata: clicca su 'ⓘ Cos'è?'.",
    )

    perf, risk = _kpi_specs_demo()

    st.markdown("**Performance** — quanto rende il portafoglio")
    render_metric_row(tokens, perf)

    with st.expander("📚 Differenza tra TWR e MWR (importante)", expanded=False):
        st.markdown(
            "**TWR (Time-Weighted Return)** misura quanto e' bravo l'algoritmo "
            "di selezione, indipendentemente dal momento in cui hai versato "
            "denaro. E' la metrica giusta per confrontare con benchmark "
            "come l'S&P 500.\n\n"
            "**MWR (Money-Weighted Return)** misura quanto hai guadagnato tu "
            "in termini effettivi: include il timing dei tuoi versamenti. "
            "Se aggiungi denaro vicino ai minimi di mercato, l'MWR sale rispetto "
            "al TWR. Se lo aggiungi vicino ai massimi, l'MWR scende.\n\n"
            "**Alpha** e' il rendimento extra rispetto a quello che ti dovevi "
            "aspettare dato il tuo livello di rischio assunto: alpha positivo "
            "= sovraperformance reale, oltre la fortuna del mercato."
        )

    st.divider()
    st.markdown("**Rischio** — quanto puoi perdere")
    render_metric_row(tokens, risk)

    with st.expander("📚 Come interpretare VaR, CVaR, Beta, Max DD", expanded=False):
        st.markdown(
            "**VaR 95%** dice qual e' la perdita massima che ci si attende "
            "nel 95% dei giorni di mercato. Esempio: VaR -4.2% significa che "
            "in 95 giorni su 100 la perdita giornaliera non supera il 4.2%; "
            "negli altri 5 giorni *puo'* essere peggiore.\n\n"
            "**CVaR 95%** e' la perdita media nei giorni 'peggio del VaR'. "
            "E' piu' informativo del VaR, perche' descrive la severita' delle "
            "code estreme (CVaR = -6.8% significa che, quando le cose vanno "
            "davvero male, la perdita media e' del 6.8%).\n\n"
            "**Beta vs S&P** misura quanto il portafoglio si muove rispetto "
            "all'S&P 500: 1.0 = stesso movimento, 0.5 = meta', 1.5 = "
            "amplifica del 50%, valori negativi = inverso al mercato.\n\n"
            "**Max DD** e' la peggiore caduta dal picco al minimo nel periodo "
            "osservato. Misura l'esperienza emotiva peggiore dell'investitore. "
            "Drawdown > 20% significa bear market; > 40% = crisi sistemica."
        )


def body_portafoglio_etoro(tokens: DesignTokens) -> None:  # pragma: no cover -- Streamlit
    """Body Streamlit della pagina P2 (v7.1.1)."""
    try:
        import streamlit as st
    except ImportError:
        return

    tab_positions, tab_import, tab_metrics = st.tabs(
        ["💼 Posizioni", "📥 Import", "📊 Metriche"]
    )
    with tab_positions:
        _render_positions_tab(st)
    with tab_import:
        _render_import_tab(st)
    with tab_metrics:
        _render_metrics_tab(tokens, st)


if __name__ == "__main__":  # pragma: no cover
    render_page("Portafoglio eToro", "📂", body_portafoglio_etoro)
