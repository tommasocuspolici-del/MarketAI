# ruff: noqa: N999
"""P2 — Portafoglio eToro (v7.3.0).

Bugfix v7.3.0:
  - FIX CRITICO: _get_current_price_yf sostituita con get_live_price_usd
    (importata da etoro_importer). La vecchia implementazione chiamava
    yf.Ticker(ticker).fast_info.last_price restituendo il prezzo RAW in GBX
    (pence) per i ticker LSE (SWDA.L, CSPX.L, EIMI.L): es. 10 426 GBX
    trattato come 10 426 USD invece di ~132 USD. get_live_price_usd applica
    la conversione GBX→USD (÷100 × GBP/USD) e EUR→USD per *.DE/*.MI.
  - FIX: _render_portfolio_totals ora mostra la valuta esplicita nelle metric
    label e avvisa l'utente se nel DataFrame sono presenti colonne con valute
    diverse (situazione possibile con posizioni inserite manualmente in EUR).
  - FIX: _build_grouped_portfolio usa get_live_price_usd come fallback (stesso
    motivo di sopra).
  - Tutti i valori importati da etoro_importer v7.4.0 sono normalizzati in USD;
    le posizioni inserite manualmente mantengono la valuta dell'utente ma vengono
    segnalate nel riepilogo.

Bugfix v7.2.1 (Modifica 4):
  - _render_positions_tab: posizioni raggruppate per ticker con aggregazione
    (quantità totale, costo medio ponderato, valore di mercato, P/L).
  - Rimossa colonna "Origine" dalla tabella posizioni.
  - Aggiunto riepilogo portafoglio: valore totale investito, valore corrente,
    P/L assoluto e percentuale.
  - Prezzo corrente recuperato via yfinance per ticker standard (non #ID).
  - Borsa mostrata solo se non è "ALTRO" (per import eToro non disponibile).

Bugfix v7.1.1:
  - Aggiunto import via API ufficiale eToro (preferito) — sostituisce il
    bisogno dell'utente di scaricare manualmente l'XLSX Account Statement.
  - Parser XLSX rimane come FALLBACK per chi non ha credenziali API o
    se l'API e' temporaneamente non raggiungibile.

La pagina ha tre tab:
  1. Posizioni — vista raggruppata per ticker + CRUD
  2. Import — API eToro (preferito) + XLSX fallback
  3. Metriche — TWR/Sharpe/VaR ecc. ognuna con tooltip spiegato
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pandas as pd

from personal.data_entry.etoro_importer import (
    EtoroImporter,
    EtoroImportError,
    EtoroImportResult,
    get_live_price_usd,          # ← v7.3.0: import pubblico con conversione GBX/EUR→USD
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
from presentation.ui.session_keys import SK

if TYPE_CHECKING:
    from presentation.ui.theme import DesignTokens

__version__ = "7.3.0"

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
                raw_action = ""
                if "raw_action" in df.columns:
                    orig_match = df[df["ticker"] == row.get("ticker")]
                    if not orig_match.empty:
                        raw_action = str(orig_match.iloc[0].get("raw_action", ""))
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
                        notes=f"source={result.source}" + (f";name={raw_action}" if raw_action else ""),
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
                        st.session_state[SK.ETORO_IMPORT_RESULT_API] = result
                    except EtoroImportError as exc:
                        st.error(f"❌ {exc}")
                    except Exception as exc:  # pragma: no cover  # noqa: BLE001
                        st.error(
                            f"❌ Errore inatteso durante la chiamata API: "
                            f"{type(exc).__name__}: {exc}"
                        )

            api_result = st.session_state.get(SK.ETORO_IMPORT_RESULT_API)
            if api_result is not None:
                _render_review_and_import(st, api_result)

    # ─────────────────────────────────────────────────── XLSX tab
    with xlsx_tab:
        st.markdown(
            "Usa il file Account Statement (.xlsx) scaricato da eToro come backup, "
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
                st.session_state[SK.ETORO_IMPORT_RESULT_XLSX] = result
            except EtoroImportError as exc:
                st.error(f"❌ {exc}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"❌ Errore inatteso durante il caricamento del file: {type(exc).__name__}")
            xlsx_result = st.session_state.get(SK.ETORO_IMPORT_RESULT_XLSX)
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


def _extract_display_name(position: PositionInput) -> str:
    """Estrae il nome display dalla posizione.

    I ticker come '#3040' sono instrument_id eToro (fallback quando
    il lookup /instruments API fallisce). Il nome leggibile viene salvato nelle
    note come 'name=<display_name>' durante l'import.
    """
    ticker = position.ticker
    # Cerca nome salvato nelle note (formato: source=api;name=iShares MSCI World...)
    if position.notes and "name=" in position.notes:
        for part in position.notes.split(";"):
            if part.startswith("name="):
                name = part[5:].strip()
                if name:
                    return name
    return ticker


def _get_current_price_yf(ticker: str) -> float | None:
    """Recupera prezzo corrente in USD via yfinance.

    v7.3.0 — FIX: ora delega a get_live_price_usd (etoro_importer v7.4.0)
    che converte correttamente:
      · GBX → USD per ticker *.L  (es. SWDA.L: 10 426 GBX / 100 * 1.27 ≈ 132 USD)
      · EUR → USD per ticker *.DE (es. EUN5.DE: 118.88 EUR * 1.08 ≈ 128 USD)

    Problema v7.2.1: questa funzione chiamava direttamente yf.Ticker(ticker)
    e restituiva il prezzo GREZZO in valuta nativa (GBX per LSE). Il valore
    10 426 GBX veniva poi trattato come USD in _build_grouped_portfolio,
    producendo "Valore corrente" ~100x gonfiato per SWDA.L/CSPX.L/EIMI.L.
    """
    if ticker.startswith("#") or ticker == "UNKNOWN":
        return None
    return get_live_price_usd(ticker)   # ← conversione GBX/EUR→USD inclusa


def _build_grouped_portfolio(positions: list[PositionInput]) -> pd.DataFrame:
    """Raggruppa le posizioni per ticker e calcola aggregati.

    Aggrega quantità, costo ponderato, valore corrente e P/L
    per ogni ticker. I ticker '#ID' mantengono il nome leggibile dalle note.

    Prezzi correnti recuperati via get_live_price_usd (v7.3.0):
    tutti i valori sono in USD (o nella valuta nativa del PositionInput
    per posizioni inserite manualmente con valuta diversa).

    Returns:
        DataFrame con colonne: Ticker, Nome, Dir., Qta totale,
        Costo medio, Investito (CCY), Prezzo corrente, Valore corrente (CCY),
        P/L (CCY), P/L %.
    """
    if not positions:
        return pd.DataFrame()

    # Raggruppa per ticker
    grouped: dict[str, dict] = {}
    for pos in positions:
        key = pos.ticker
        display = _extract_display_name(pos)
        if key not in grouped:
            grouped[key] = {
                "display_name": display,
                "direction": pos.direction,
                "currency": pos.currency,
                "total_qty": 0.0,
                "total_cost": 0.0,
                "positions_list": [],
            }
        grouped[key]["total_qty"] += pos.quantity
        grouped[key]["total_cost"] += pos.quantity * pos.avg_cost
        grouped[key]["positions_list"].append(pos)

    rows = []
    for ticker, data in grouped.items():
        total_qty = data["total_qty"]
        total_cost = data["total_cost"]
        avg_cost_weighted = total_cost / total_qty if total_qty > 0 else 0.0

        # Prezzo corrente: usa il valore salvato nella posizione (già in USD dopo
        # import v7.4.0), altrimenti fallback a get_live_price_usd (con conversione GBX).
        current_price: float | None = None
        for p in data["positions_list"]:
            if p.current_price is not None:
                current_price = p.current_price
                break
        if current_price is None:
            current_price = _get_current_price_yf(ticker)  # delega a get_live_price_usd

        current_value = (current_price * total_qty) if current_price is not None else None
        pl_abs = (current_value - total_cost) if current_value is not None else None
        pl_pct = (
            pl_abs / total_cost * 100.0
            if (pl_abs is not None and total_cost > 0)
            else None
        )

        ccy = data["currency"]
        rows.append({
            "Ticker": ticker,
            "Nome": data["display_name"] if data["display_name"] != ticker else "—",
            "Dir.": data["direction"],
            "Qta totale": round(total_qty, 4),
            "Costo medio": round(avg_cost_weighted, 2),
            f"Investito ({ccy})": round(total_cost, 2),
            "Prezzo corrente": round(current_price, 2) if current_price is not None else "N/D",
            f"Valore corrente ({ccy})": round(current_value, 2) if current_value is not None else "N/D",
            f"P/L ({ccy})": round(pl_abs, 2) if pl_abs is not None else "N/D",
            "P/L %": f"{pl_pct:+.2f}%" if pl_pct is not None else "N/D",
        })

    return pd.DataFrame(rows)


def _render_portfolio_totals(st_module, df_grouped: pd.DataFrame) -> None:  # pragma: no cover
    """Mostra il riepilogo totale del portafoglio.

    v7.3.0 — FIX: mostra la valuta esplicitamente nel label delle metric.
    Se sono presenti colonne con valute diverse (posizioni manuali in EUR
    mescolate con posizioni importate in USD) mostra un avviso e aggrega
    separatamente per valuta invece di sommare valori eterogenei.

    Problema v7.2.1: le colonne erano nominate dinamicamente ("Investito (USD)",
    "Investito (EUR)" ecc.) ma la funzione le sommava tutte senza distinzione,
    producendo aggregati senza senso quando erano presenti valute diverse.
    Dopo il fix etoro_importer v7.4.0 tutte le posizioni importate sono in USD,
    quindi in condizioni normali ci sarà una sola colonna "Investito (USD)".
    """
    st = st_module

    # Individua tutte le colonne per investito/corrente/P/L e la loro valuta
    invested_cols = [c for c in df_grouped.columns if c.startswith("Investito (")]
    value_cols    = [c for c in df_grouped.columns if c.startswith("Valore corrente (")]

    # Estrai le valute uniche presenti nel DataFrame
    def _extract_ccy(col_name: str) -> str:
        m = re.search(r'\((\w+)\)', col_name)
        return m.group(1) if m else "?"

    currencies_invested = {_extract_ccy(c) for c in invested_cols}
    currencies_value    = {_extract_ccy(c) for c in value_cols}
    all_currencies = currencies_invested | currencies_value

    # ── Avviso valute miste ────────────────────────────────────────────────
    if len(all_currencies) > 1:
        st.warning(
            f"⚠️ Valute miste rilevate: {', '.join(sorted(all_currencies))}. "
            "Le posizioni importate da eToro v7.4.0 sono normalizzate in USD; "
            "le posizioni manuali mantengono la valuta originale. "
            "I totali sotto sono mostrati separatamente per valuta."
        )
        # Mostra un riepilogo per ogni valuta
        for ccy in sorted(all_currencies):
            inv_col  = f"Investito ({ccy})"
            val_col  = f"Valore corrente ({ccy})"
            pl_col   = f"P/L ({ccy})"
            if inv_col not in df_grouped.columns:
                continue
            t_inv = float(pd.to_numeric(df_grouped[inv_col], errors="coerce").sum())
            has_val = val_col in df_grouped.columns
            t_val = float(
                pd.to_numeric(df_grouped[val_col], errors="coerce").dropna().sum()
            ) if has_val else None
            t_pl  = (t_val - t_inv) if t_val is not None else None
            t_pct = (t_pl / t_inv * 100.0) if (t_pl is not None and t_inv > 0) else None

            st.markdown(f"**{ccy}**")
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.metric(f"💼 Investito ({ccy})", f"{t_inv:,.2f}")
            with c2:
                st.metric(f"📈 Corrente ({ccy})", f"{t_val:,.2f}" if t_val is not None else "N/D")
            with c3:
                if t_pl is not None:
                    st.metric(f"💹 P/L ({ccy})", f"{t_pl:+,.2f}")
                else:
                    st.metric(f"💹 P/L ({ccy})", "N/D")
            with c4:
                st.metric("📊 P/L %", f"{t_pct:+.2f}%" if t_pct is not None else "N/D")
        st.divider()
        return

    # ── Caso normale: singola valuta (USD dopo import v7.4.0) ─────────────
    ccy = next(iter(all_currencies), "USD") if all_currencies else "USD"

    total_invested = 0.0
    total_current  = 0.0
    has_current    = False

    for col in invested_cols:
        vals = pd.to_numeric(df_grouped[col], errors="coerce")
        total_invested += float(vals.sum())

    for col in value_cols:
        vals = pd.to_numeric(df_grouped[col], errors="coerce")
        valid = vals.dropna()
        if not valid.empty:
            total_current += float(valid.sum())
            has_current = True

    total_pl     = total_current - total_invested if has_current else None
    total_pl_pct = (
        total_pl / total_invested * 100.0
        if (total_pl is not None and total_invested > 0)
        else None
    )

    st.markdown(f"### 💰 Riepilogo portafoglio · {ccy}")
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric(f"💼 Totale investito ({ccy})", f"{total_invested:,.2f}")
    with col2:
        if has_current:
            st.metric(f"📈 Valore corrente ({ccy})", f"{total_current:,.2f}")
        else:
            st.metric(f"📈 Valore corrente ({ccy})", "N/D")
    with col3:
        if total_pl is not None:
            st.metric(f"💹 P/L assoluto ({ccy})", f"{total_pl:+,.2f}")
        else:
            st.metric(f"💹 P/L assoluto ({ccy})", "N/D")
    with col4:
        if total_pl_pct is not None:
            st.metric("📊 P/L %", f"{total_pl_pct:+.2f}%")
        else:
            st.metric("📊 P/L %", "N/D")
    st.divider()


def _render_positions_tab(st_module) -> None:  # pragma: no cover -- Streamlit
    """Tab di gestione posizioni con vista raggruppata per ticker."""
    st = st_module
    render_section_header("💼 Posizioni in portafoglio")

    positions = list_positions()
    if not positions:
        st.info(
            "Nessuna posizione presente. Aggiungi una posizione manualmente "
            "qui sotto, oppure importa da eToro nella tab dedicata."
        )
    else:
        df_grouped = _build_grouped_portfolio(positions)

        # Riepilogo totali portafoglio
        _render_portfolio_totals(st, df_grouped)

        st.caption(
            "📋 Vista raggruppata per ticker · "
            "I prezzi correnti sono recuperati via yfinance (possono essere "
            "leggermente differiti). I ticker in formato '#ID' non sono "
            "risolvibili automaticamente — usa l'Import per aggiornare i dati."
        )
        st.dataframe(df_grouped, use_container_width=True, hide_index=True)

        # ── Gestione posizioni singole: elimina inline + modifica ──────────
        st.markdown("#### ✏️ Posizioni singole — Modifica / Elimina")
        st.caption("Ogni riga ha un pulsante 🗑️ di eliminazione rapida. Clicca ✏️ per modificare.")

        confirm_key = "confirm_delete_position"
        edit_key    = "editing_position_id"

        for pos in positions:
            display = _extract_display_name(pos)
            col_info, col_edit, col_del = st.columns([5, 1, 1])
            with col_info:
                st.markdown(
                    f"<span style='font-size:0.85rem;opacity:0.8;'>"
                    f"<b>{display}</b> &nbsp;|&nbsp; {pos.direction} &nbsp;|&nbsp; "
                    f"qty {pos.quantity:.4f} &nbsp;|&nbsp; carico {pos.avg_cost:.2f} "
                    f"&nbsp;|&nbsp; {pos.currency}</span>",
                    unsafe_allow_html=True,
                )
            with col_edit:
                if st.button("✏️", key=f"edit_{pos.position_id}", help=f"Modifica {display}"):
                    st.session_state[edit_key] = pos.position_id
            with col_del:
                if st.session_state.get(confirm_key) == pos.position_id:
                    c_ok, c_cancel = st.columns(2)
                    with c_ok:
                        if st.button("✅", key=f"del_ok_{pos.position_id}", help="Conferma"):
                            delete_position(pos.position_id)
                            del st.session_state[confirm_key]
                            st.success(f"Eliminata: {display}")
                            st.rerun()
                    with c_cancel:
                        if st.button("❌", key=f"del_cancel_{pos.position_id}", help="Annulla"):
                            del st.session_state[confirm_key]
                            st.rerun()
                else:
                    if st.button("🗑️", key=f"del_{pos.position_id}", help=f"Elimina {display}"):
                        st.session_state[confirm_key] = pos.position_id
                        st.rerun()

        # Sezione modifica espandibile per la posizione selezionata
        editing_id = st.session_state.get(edit_key)
        if editing_id:
            editing_pos = next((p for p in positions if p.position_id == editing_id), None)
            if editing_pos:
                with st.expander(f"✏️ Modifica: {_extract_display_name(editing_pos)}", expanded=True):
                    edited = render_position_form(editing_pos, key="edit_position_form")
                    if edited is not None:
                        save_position(edited)
                        del st.session_state[edit_key]
                        st.success(f"✅ Posizione {edited.ticker} aggiornata.")
                        st.rerun()
                    if st.button("✖ Chiudi", key="close_edit_form"):
                        del st.session_state[edit_key]
                        st.rerun()

    st.divider()
    st.markdown("#### ➕ Aggiungi posizione manuale")
    new_pos = render_position_form(key="new_position_form")
    if new_pos is not None:
        save_position(new_pos)
        st.success(f"✅ Posizione {new_pos.ticker} aggiunta al portafoglio.")
        st.rerun()


def _render_metrics_tab(tokens, st_module) -> None:  # pragma: no cover -- Streamlit
    """Tab di metriche performance e rischio, ognuna esplicitata."""
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
    """Body Streamlit della pagina P2 (v7.3.0)."""
    # [v8.1.0 FIX-P9] rimosso try/except ImportError silenzioso;
    # funzione body già #pragma:no cover — ImportError qui è un errore reale
    import streamlit as st

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
