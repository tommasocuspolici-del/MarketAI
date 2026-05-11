"""EtoroImporter: facade unica per importare posizioni eToro (v7.3.0).

Changelog v7.3.0 — fix breaking change API eToro (tier-4 order resolution):
  - import_via_api(): aggiunto tier-4 di risoluzione tramite orderId.
    Quando né instrument_id né ticker_from_api sono disponibili, ma la
    posizione ha un orderId, viene chiamato
    GET /api/v1/trading/info/real/orders/{orderId} (instrumentID è campo
    obbligatorio per spec v1.158.0) per ricavare l'instrumentId.
    Richiede EtoroClient.get_instrument_id_from_order(order_id) — v. nota.
  - Nuova funzione helper _resolve_instrument_ids_via_orders().
  - Classificazione ora a 4 livelli: with_id | ticker_only | via_order |
    unresolvable.
  - Note diagnostiche aggiornate con conteggio tier-4.

  NOTA EtoroClient: necessaria l'aggiunta del metodo:
    def get_instrument_id_from_order(self, order_id: int) -> int | None:
        '''GET /api/v1/trading/info/real/orders/{orderId} → instrumentID.'''

Changelog v7.2.0 — fix breaking change API eToro:
  - import_via_api(): non scarta più le posizioni senza instrument_id se
    EtoroPosition.ticker_from_api è valorizzato (estratto dal model_validator
    di etoro_models.py v7.2.0).
  - _api_positions_to_dataframe(): accetta posizioni con solo ticker_from_api
    (nessun lookup /instruments necessario in quel caso).
  - Note di diagnostica più precise: distingue "nessun dato" da "dati parziali".

Decide automaticamente la sorgente migliore disponibile:
  1. Se ``ETORO_API_KEY`` e ``ETORO_USER_KEY`` sono presenti -> API ufficiale.
  2. Altrimenti -> parser XLSX (fallback offline).

Schema output (colonne canoniche):
  ticker, direction, quantity, open_price, current_price, open_date,
  market_value, profit_pct, profit_eur, currency, raw_action

Pattern d'uso (UI Streamlit)::

    importer = EtoroImporter()
    if importer.has_api_credentials:
        df = importer.import_via_api()
    else:
        df = importer.import_via_xlsx(uploaded_file)

    # Comodità: decide automaticamente
    df = importer.import_open_positions(xlsx_fallback=uploaded_file_or_none)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

import pandas as pd

from personal.data_entry.etoro_client import (
    EtoroAuthError,
    EtoroClient,
    EtoroClientError,
)
from personal.data_entry.etoro_models import (
    EtoroInstrument,
    EtoroInstrumentRate,
    EtoroPortfolioResponse,
    EtoroPosition,
)
from personal.data_entry.etoro_parser import EToroParseError, EToroParser

__version__ = "7.3.0"

__all__ = ["EtoroImporter", "EtoroImportError", "EtoroImportResult"]

log = logging.getLogger(__name__)


class EtoroImportError(Exception):
    """Errore generico durante l'import (API o XLSX)."""


@dataclass(frozen=True, slots=True)
class EtoroImportResult:
    """Risultato dell'import: DataFrame + meta-informazioni sulla sorgente."""

    positions: pd.DataFrame
    source: str               # "api" | "xlsx"
    n_positions: int
    n_warnings: int = 0
    notes: str = ""


# ───────────────────────────────────────────────── canonical columns
_CANONICAL_COLUMNS = [
    "ticker",
    "direction",
    "quantity",
    "open_price",
    "current_price",
    "open_date",
    "market_value",
    "profit_pct",
    "profit_eur",
    "currency",
    "raw_action",
]


class EtoroImporter:
    """Facade unica per import posizioni eToro.

    Strategia:
      - Preferisce sempre l'API ufficiale se disponibile.
      - Cade su parser XLSX se l'utente non ha credenziali API o se l'API
        ritorna un errore di rete.
      - Espone properties per la UI per sapere "quale sorgente sto usando".
    """

    def __init__(
        self,
        *,
        api_key_var: str = "ETORO_API_KEY",
        user_key_var: str = "ETORO_USER_KEY",
    ) -> None:
        self._api_key_var = api_key_var
        self._user_key_var = user_key_var

    # ─────────────────────────────────────────────────── credentials
    @property
    def has_api_credentials(self) -> bool:
        """True se entrambe le env vars sono settate (non vuote)."""
        api_key = os.environ.get(self._api_key_var, "").strip()
        user_key = os.environ.get(self._user_key_var, "").strip()
        return bool(api_key and user_key)

    @property
    def credential_status_message(self) -> str:
        """Messaggio user-facing su quale sorgente verrà usata."""
        if self.has_api_credentials:
            return (
                "✅ API eToro configurata: le posizioni verranno fetchate "
                "automaticamente, nessun upload richiesto."
            )
        return (
            "ℹ️ Credenziali API eToro non trovate (ETORO_API_KEY / "
            "ETORO_USER_KEY). Verrà usato il parsing del file XLSX "
            "Account Statement come fallback. Per abilitare l'API, "
            "vai su https://www.etoro.com/settings/trade e genera le "
            "chiavi, poi salvale nel file .env."
        )

    # ─────────────────────────────────────────────────── public api
    def import_open_positions(
        self,
        *,
        xlsx_source: str | bytes | BinaryIO | None = None,
        force_xlsx: bool = False,
    ) -> EtoroImportResult:
        """Import unificato: sceglie automaticamente API o XLSX.

        Args:
            xlsx_source: file XLSX (path/bytes/file-like) usato in fallback.
            force_xlsx: se True, ignora API anche se le credenziali sono
                presenti. Utile per debug/test.

        Returns:
            EtoroImportResult con DataFrame normalizzato.

        Raises:
            EtoroImportError: se entrambe le sorgenti falliscono.
        """
        if not force_xlsx and self.has_api_credentials:
            try:
                return self.import_via_api()
            except EtoroClientError as exc:
                log.warning("API eToro fallita, fallback su XLSX: %s", exc)
                if xlsx_source is None:
                    raise EtoroImportError(
                        f"API eToro fallita ({exc}) e nessun file XLSX "
                        f"di fallback fornito. Carica l'Account Statement "
                        f"come backup."
                    ) from exc
                return self.import_via_xlsx(
                    xlsx_source,
                    notes=f"Fallback XLSX dopo errore API: {exc}",
                )

        if xlsx_source is None:
            raise EtoroImportError(
                "Nessuna credenziale API eToro trovata e nessun file "
                "XLSX fornito. Carica l'Account Statement oppure "
                "configura ETORO_API_KEY e ETORO_USER_KEY in .env."
            )
        return self.import_via_xlsx(xlsx_source)

    def import_via_api(self) -> EtoroImportResult:
        """Forza l'import via API ufficiale eToro.

        v7.3.0: aggiunto tier-4 — posizioni senza instrument_id e senza
        ticker_from_api ma con orderId vengono risolte tramite
        GET /api/v1/trading/info/real/orders/{orderId} (instrumentID è campo
        required per spec API v1.158.0).

        v7.2.0: utilizza EtoroPosition.ticker_from_api per le posizioni
        senza instrument_id, invece di scartarle tutte.

        Raises:
            EtoroAuthError: credenziali mancanti o invalide.
            EtoroClientError: altri errori del client API.
        """
        client = EtoroClient.from_env(
            api_key_var=self._api_key_var,
            user_key_var=self._user_key_var,
        )
        portfolio = client.get_real_portfolio()
        all_positions = portfolio.client_portfolio.positions

        if not all_positions:
            return EtoroImportResult(
                positions=_empty_canonical_df(),
                source="api",
                n_positions=0,
                notes="Nessuna posizione aperta nel portfolio.",
            )

        # ── v7.3.0: classifica le posizioni in quattro livelli ────────────
        #
        # Tier 1 — resolvable_with_id:    hanno instrument_id → lookup /instruments
        # Tier 2 — resolvable_ticker_only: hanno solo ticker_from_api → nessun lookup
        # Tier 3 — resolvable_via_order:  hanno solo orderId → lookup /orders/{orderId}
        #          (risolto in un secondo passaggio sotto)
        # Tier 4 — unresolvable:          nessun identificatore → scartate
        #
        resolvable_with_id: list[EtoroPosition] = []
        resolvable_ticker_only: list[EtoroPosition] = []
        candidate_via_order: list[EtoroPosition] = []   # potrebbero diventare tier-1
        unresolvable: list[EtoroPosition] = []

        for pos in all_positions:
            if pos.instrument_id is not None:
                resolvable_with_id.append(pos)
            elif pos.ticker_from_api is not None:
                resolvable_ticker_only.append(pos)
            elif pos.order_id is not None:
                candidate_via_order.append(pos)
            else:
                unresolvable.append(pos)

        # ── Tier-3: risoluzione tramite /orders/{orderId} ─────────────────
        # GET /api/v1/trading/info/real/orders/{orderId}
        # → OrderForOpenInfoResponse.instrumentID (campo required per spec)
        resolvable_via_order: list[EtoroPosition] = []
        if candidate_via_order:
            resolved_via_order, still_unresolvable = _resolve_instrument_ids_via_orders(
                client, candidate_via_order
            )
            resolvable_via_order = resolved_via_order
            # Le posizioni risolte tramite order ora hanno instrument_id iniettato:
            # le trattiamo come tier-1 per il lookup /instruments
            resolvable_with_id.extend(resolved_via_order)
            unresolvable.extend(still_unresolvable)

        n_unresolvable = len(unresolvable)
        n_resolvable   = (
            len(resolvable_with_id)          # include già via_order dopo merge
            + len(resolvable_ticker_only)
        )

        log.info(
            "etoro.import_classification",
            total=len(all_positions),
            with_instrument_id=len(resolvable_with_id) - len(resolvable_via_order),
            ticker_only=len(resolvable_ticker_only),
            via_order=len(resolvable_via_order),
            unresolvable=n_unresolvable,
        )

        if n_resolvable == 0:
            # Nessuna posizione recuperabile in nessun modo.
            # Fornisce diagnostica dettagliata per aiutare il debug.
            return EtoroImportResult(
                positions=_empty_canonical_df(),
                source="api",
                n_positions=0,
                n_warnings=n_unresolvable,
                notes=(
                    f"Tutte le {n_unresolvable} posizioni restituite dall'API "
                    "eToro sono prive di instrument_id, ticker e orderId "
                    "(breaking change API non gestito dalla v7.3.0). "
                    "Azione: (1) usa import XLSX come alternativa; "
                    "(2) segnala il bug con i log DEBUG del client "
                    "(attiva con logging.basicConfig(level=logging.DEBUG))."
                ),
            )

        # ── Risolvi instrument_id -> ticker via /instruments (batch) ──────
        instruments: dict[int, EtoroInstrument] = {}
        if resolvable_with_id:
            instrument_ids = list({p.instrument_id for p in resolvable_with_id})  # type: ignore[misc]
            try:
                instruments = client.get_instruments(instrument_ids)
            except EtoroClientError as exc:
                log.warning(
                    "etoro.instruments_lookup_failed: %s — usando ticker_from_api come fallback",
                    exc,
                )
                # Non è fatale: le posizioni con id ma senza risoluzione
                # usano il fallback f"#{instrument_id}" in _api_positions_to_dataframe

        # ── Quote correnti (best effort) ──────────────────────────────────
        rates: dict[int, EtoroInstrumentRate] = {}
        if resolvable_with_id:
            try:
                rates = client.get_rates(
                    [p.instrument_id for p in resolvable_with_id]  # type: ignore[misc]
                )
            except EtoroClientError as exc:
                log.warning("etoro.rates_lookup_failed: %s", exc)

        # ── Costruisci DataFrame ──────────────────────────────────────────
        all_resolvable = resolvable_with_id + resolvable_ticker_only
        df = _api_positions_to_dataframe(all_resolvable, instruments, rates)

        # ── Metriche e note ───────────────────────────────────────────────
        n_unresolved_id = sum(
            1 for p in resolvable_with_id
            if p.instrument_id not in instruments
        )
        n_warnings = n_unresolvable + n_unresolved_id

        notes_parts = [
            f"Importate {n_resolvable} posizioni via API ufficiale eToro."
        ]
        if len(resolvable_ticker_only) > 0:
            notes_parts.append(
                f"{len(resolvable_ticker_only)} posizioni importate tramite "
                "ticker_from_api (instrument_id non disponibile ma ticker "
                "estratto direttamente dalla risposta API)."
            )
        if len(resolvable_via_order) > 0:
            notes_parts.append(
                f"{len(resolvable_via_order)} posizioni risolte tramite "
                "orderId → GET /orders/{{orderId}} (tier-4 v7.3.0)."
            )
        if n_unresolvable > 0:
            notes_parts.append(
                f"{n_unresolvable} posizioni scartate: nessun identificatore "
                "recuperabile (né instrument_id né ticker né orderId)."
            )
        if n_unresolved_id > 0:
            notes_parts.append(
                f"{n_unresolved_id} posizioni con instrument_id non risolto "
                "dal lookup /instruments (usato ticker placeholder #ID)."
            )

        return EtoroImportResult(
            positions=df,
            source="api",
            n_positions=n_resolvable,
            n_warnings=n_warnings,
            notes=" ".join(notes_parts),
        )

    def import_via_xlsx(
        self,
        source: str | bytes | BinaryIO,
        *,
        notes: str = "",
    ) -> EtoroImportResult:
        """Forza l'import via parsing XLSX (fallback).

        Raises:
            EtoroImportError: se il file XLSX non è valido.
        """
        parser = EToroParser()
        try:
            df = parser.parse(source)
        except EToroParseError as exc:
            raise EtoroImportError(
                f"Impossibile leggere il file XLSX: {exc}"
            ) from exc

        df = _align_canonical_schema(df)

        return EtoroImportResult(
            positions=df,
            source="xlsx",
            n_positions=len(df),
            notes=notes or "Parsing XLSX completato.",
        )


# ─────────────────────────────────────────────────────── helpers
def _resolve_instrument_ids_via_orders(
    client: EtoroClient,
    positions: list[EtoroPosition],
) -> tuple[list[EtoroPosition], list[EtoroPosition]]:
    """Risolve instrument_id per posizioni che ce l'hanno mancante tramite orderId.

    Chiama GET /api/v1/trading/info/real/orders/{orderId} per ogni orderId
    univoco. Il campo ``instrumentID`` è obbligatorio nella risposta per spec
    API v1.158.0 (OrderForOpenInfoResponse).

    Richiede che EtoroClient esponga il metodo::

        def get_instrument_id_from_order(self, order_id: int) -> int | None:
            '''GET /api/v1/trading/info/real/orders/{orderId} → instrumentID.'''

    Raises EtoroClientError solo se il client non supporta il metodo (AttributeError
    catturato e convertito per retrocompatibilità).

    Args:
        client:    istanza EtoroClient autenticata.
        positions: posizioni prive di instrument_id e ticker_from_api ma
                   con order_id valorizzato.

    Returns:
        (resolved, still_unresolvable):
          - resolved:            posizioni con instrument_id iniettato via
                                 model_copy(update={"instrument_id": iid})
          - still_unresolvable:  posizioni per cui il lookup è fallito.
    """
    if not positions:
        return [], []

    if not hasattr(client, "get_instrument_id_from_order"):
        log.warning(
            "etoro.order_resolution_unavailable — EtoroClient non espone "
            "get_instrument_id_from_order(). Aggiornare etoro_client.py "
            "per abilitare il tier-4 di risoluzione (v7.3.0)."
        )
        return [], positions

    # Raccogli gli orderId univoci per evitare chiamate duplicate
    unique_order_ids: list[int] = list(
        {p.order_id for p in positions if p.order_id is not None}
    )

    order_to_instrument: dict[int, int] = {}
    for order_id in unique_order_ids:
        try:
            iid = client.get_instrument_id_from_order(order_id)
            if iid is not None:
                order_to_instrument[order_id] = int(iid)
                log.debug(
                    "etoro.order_resolved order_id=%s instrument_id=%s",
                    order_id,
                    iid,
                )
            else:
                log.warning(
                    "etoro.order_resolved_no_instrument order_id=%s "
                    "(instrumentID assente nella risposta /orders)",
                    order_id,
                )
        except EtoroClientError as exc:
            log.warning(
                "etoro.order_resolution_failed order_id=%s: %s",
                order_id,
                exc,
            )

    resolved: list[EtoroPosition] = []
    still_unresolvable: list[EtoroPosition] = []

    for pos in positions:
        iid = order_to_instrument.get(pos.order_id) if pos.order_id is not None else None
        if iid is not None:
            # Iniettiamo instrument_id nel modello Pydantic immutato altrimenti
            resolved.append(pos.model_copy(update={"instrument_id": iid}))
        else:
            still_unresolvable.append(pos)

    log.info(
        "etoro.order_resolution_summary resolved=%d failed=%d",
        len(resolved),
        len(still_unresolvable),
    )
    return resolved, still_unresolvable


def _empty_canonical_df() -> pd.DataFrame:
    """DataFrame vuoto con tutte le colonne canoniche."""
    return pd.DataFrame({col: pd.Series(dtype="object") for col in _CANONICAL_COLUMNS})


def _align_canonical_schema(df: pd.DataFrame) -> pd.DataFrame:
    """Garantisce che il DataFrame abbia tutte le colonne canoniche."""
    out = pd.DataFrame()
    for col in _CANONICAL_COLUMNS:
        if col in df.columns:
            out[col] = df[col].values
        else:
            out[col] = pd.NA
    return out.reset_index(drop=True)


def _api_positions_to_dataframe(
    positions: list[EtoroPosition],
    instruments: dict[int, EtoroInstrument],
    rates: dict[int, EtoroInstrumentRate],
) -> pd.DataFrame:
    """Converte le posizioni API nel DataFrame canonico.

    v7.2.0: gestisce correttamente posizioni con solo ticker_from_api
    (senza instrument_id o senza risoluzione da /instruments).

    Priorità ticker:
      1. EtoroInstrument.best_symbol (risolto via /instruments)
      2. EtoroPosition.ticker_from_api (estratto direttamente dalla risposta)
      3. f"#{instrument_id}" (placeholder se id noto ma non risolto)
    """
    rows = []
    for pos in positions:
        inst = instruments.get(pos.instrument_id) if pos.instrument_id is not None else None
        rate = rates.get(pos.instrument_id) if pos.instrument_id is not None else None

        # ── Ticker ────────────────────────────────────────────────────────
        if inst is not None:
            ticker = inst.best_symbol
        elif pos.ticker_from_api:
            ticker = pos.ticker_from_api
        elif pos.instrument_id is not None:
            ticker = f"#{pos.instrument_id}"
        else:
            ticker = "UNKNOWN"

        # ── raw_action (nome leggibile) ───────────────────────────────────
        raw_action: str
        if inst is not None and inst.name:
            raw_action = inst.name
        elif pos.display_name_from_api:
            raw_action = pos.display_name_from_api
        else:
            raw_action = ticker

        # ── Current price ─────────────────────────────────────────────────
        current_price: float | None = None
        if rate is not None and rate.mid_price is not None:
            current_price = rate.mid_price
        elif pos.close_rate is not None:
            current_price = pos.close_rate

        # ── Market value ──────────────────────────────────────────────────
        market_value: float | None = None
        if current_price is not None and pos.units > 0:
            market_value = current_price * pos.units

        # ── Profit % ──────────────────────────────────────────────────────
        profit_pct: float | None = None
        if pos.amount > 0:
            profit_pct = (pos.pnl / pos.amount) * 100.0

        rows.append(
            {
                "ticker": ticker,
                "direction": pos.direction,
                "quantity": pos.units,
                "open_price": pos.open_rate,
                "current_price": current_price,
                "open_date": pos.open_date_time,
                "market_value": market_value,
                "profit_pct": profit_pct,
                "profit_eur": pos.pnl,
                "currency": "USD",
                "raw_action": raw_action,
            }
        )

    if not rows:
        return _empty_canonical_df()

    df = pd.DataFrame(rows, columns=_CANONICAL_COLUMNS)

    for col in ("quantity", "open_price", "current_price", "market_value",
                "profit_pct", "profit_eur"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_date"] = pd.to_datetime(df["open_date"], errors="coerce", utc=True)

    return df.reset_index(drop=True)
