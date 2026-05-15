"""EtoroImporter: facade unica (v8.2.0) — ROADMAP_CODE_QUALITY_v1.0 Settimana 7.

Split da 777 → 3 moduli:
  • etoro_position_builder.py — FX helpers, DataFrame building, ticker resolution
  • etoro_aggregator.py       — aggregazione posizioni, live price updates
  • etoro_importer.py         — questa facade: orchestrazione sorgenti, EtoroImporter
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from io import BytesIO
from typing import BinaryIO

import pandas as pd

from personal.data_entry.etoro_aggregator import (
    aggregate_by_real_ticker,
    update_live_prices,
)
from personal.data_entry.etoro_client import EtoroClient, EtoroClientError
from personal.data_entry.etoro_parser import EToroParseError, EToroParser
from personal.data_entry.etoro_position_builder import (
    _CANONICAL_COLUMNS,  # noqa: F401 — re-export for backward compat
    _align_canonical_schema,
    _api_positions_to_dataframe,  # noqa: F401 — re-export for backward compat
    _build_fx_cache,
    _empty_canonical_df,
    _extract_ticker_from_nome,
    _get_instrument_currency,  # noqa: F401 — re-export for backward compat
    _native_to_usd,  # noqa: F401 — re-export for backward compat
    _override_prices_for_numeric_tickers,
    _resolve_ticker_from_placeholder,
    build_api_positions_df,
    get_live_price_usd,
)

__version__ = "8.2.0"

__all__ = [
    "EtoroImporter",
    "EtoroImportError",
    "EtoroImportResult",
    "update_live_prices",
    "aggregate_by_real_ticker",
    "get_live_price_usd",
]

log = logging.getLogger(__name__)


class EtoroImportError(Exception):
    """Errore generico durante l'import."""


@dataclass(frozen=True, slots=True)
class EtoroImportResult:
    positions: pd.DataFrame
    source: str
    n_positions: int
    n_warnings: int = 0
    notes: str = ""


class EtoroImporter:
    """Facade unificata per import posizioni eToro."""

    def __init__(
        self,
        *,
        api_key_var: str = "ETORO_API_KEY",
        user_key_var: str = "ETORO_USER_KEY",
    ) -> None:
        self._api_key_var = api_key_var
        self._user_key_var = user_key_var

    @property
    def has_api_credentials(self) -> bool:
        return bool(
            os.environ.get(self._api_key_var, "").strip()
            and os.environ.get(self._user_key_var, "").strip()
        )

    @property
    def credential_status_message(self) -> str:
        if self.has_api_credentials:
            return "✅ API eToro configurata."
        return "ℹ️ Credenziali API eToro assenti: sarà usato il file XLSX."

    def import_open_positions(
        self,
        *,
        xlsx_source: str | bytes | BinaryIO | None = None,
        force_xlsx: bool = False,
    ) -> EtoroImportResult:
        if not force_xlsx and self.has_api_credentials:
            try:
                return self.import_via_api()
            except EtoroClientError as exc:
                log.warning("API fallita, fallback XLSX: %s", exc)
                if xlsx_source is None:
                    raise EtoroImportError(
                        f"API fallita ({exc}) e nessun XLSX di fallback."
                    ) from exc
                return self.import_via_xlsx(xlsx_source, notes=f"Fallback dopo errore API: {exc}")
        if xlsx_source is None:
            raise EtoroImportError("Nessuna fonte disponibile.")
        return self.import_via_xlsx(xlsx_source)

    def import_via_api(self) -> EtoroImportResult:
        client = EtoroClient.from_env(
            api_key_var=self._api_key_var, user_key_var=self._user_key_var
        )
        portfolio = client.get_real_portfolio()
        all_positions = portfolio.client_portfolio.positions
        if not all_positions:
            return EtoroImportResult(
                positions=_empty_canonical_df(), source="api",
                n_positions=0, notes="Nessuna posizione aperta.",
            )
        df, n_resolvable, n_unresolvable, notes = build_api_positions_df(client, all_positions)
        return EtoroImportResult(
            positions=df, source="api",
            n_positions=n_resolvable, n_warnings=n_unresolvable, notes=notes,
        )

    def import_via_xlsx(
        self, source: str | bytes | BinaryIO, *, notes: str = ""
    ) -> EtoroImportResult:
        parser = EToroParser()
        try:
            df = parser.parse(source)
        except EToroParseError as exc:
            raise EtoroImportError(f"Impossibile leggere XLSX: {exc}") from exc
        df = _align_canonical_schema(df)
        if "Nome" in df.columns:
            df["real_ticker"] = df["Nome"].apply(_extract_ticker_from_nome)
        else:
            df["real_ticker"] = df["ticker"].apply(_resolve_ticker_from_placeholder)
        fx = _build_fx_cache()
        df = _override_prices_for_numeric_tickers(df, fx)
        return EtoroImportResult(
            positions=df, source="xlsx",
            n_positions=len(df), notes=notes or "Parsing XLSX completato.",
        )

    def aggregate_by_real_ticker(self, df: pd.DataFrame) -> pd.DataFrame:
        return aggregate_by_real_ticker(df)

    def get_portfolio_overview(
        self, df: pd.DataFrame, etoro_total_value: float = 0.0
    ) -> dict:
        from personal.data_entry.etoro_aggregator import _aggregate_positions
        aggr = _aggregate_positions(df)
        total = etoro_total_value if etoro_total_value else aggr["market_value"].sum()
        return {
            "eToro": {
                "valore_corrente": total,
                "posizioni": aggr.to_dict(orient="records"),
                "aggiornato_il": pd.Timestamp.now().isoformat(),
            }
        }
