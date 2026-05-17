"""Pydantic models per il contratto eToro Public API (v7.3.3).

Changelog v7.3.3:
  - EtoroInstrumentRate ora mappa correttamente "lastExecution" (non "lastRate").
  - Aggiunti campi conversionRateAsk / conversionRateBid per conversioni valutarie.
  - EtoroInstrument include symbolFull; best_symbol lo preferisce.
  - Migliorata robustezza generale.

Changelog v7.3.2 — fix: aggiunto validator `_promote_unrealized_pnl_fields`
            per estrarre pnL e closeRate dall'oggetto annidato `unrealizedPnL`.
            Senza questo validator i valori erano sempre 0 / None.

Changelog v7.3.1 — fix definitivo case sensitivity API eToro reale:
  - L'API reale espone gli ID in upper-D notation: ``positionID``,
    ``instrumentID``, ``mirrorID``, ``orderID``, e ``CID`` (TUTTO maiuscolo).
    I precedenti alias (`positionId`, `instrumentId`, ...) erano case-sensitive
    e non matchavano. Il `model_validator` cercava `InstrumentID` (3 maiuscole)
    invece di `instrumentID` (solo D finale maiuscola).
  - Soluzione: ``AliasChoices`` di Pydantic v2 — ogni campo ID accetta
    nativamente tutte le varianti note senza model_validator manuale.
  - Promozione dei campi nested: l'API NON espone ``pnL`` e ``closeRate``
    top-level; sono dentro ``unrealizedPnL.{pnL, closeRate}``. Il validator
    `_promote_unrealized_pnl_fields` li sposta a top-level prima di Pydantic.

Changelog v7.3.0 — fix breaking change API eToro (tier-4 order resolution):
  ...

Changelog v7.2.0 — fix breaking change API eToro:
  ...

Mappa le risposte API ufficiali in dataclass type-safe. La conversione
verso il DataFrame normalizzato del progetto avviene in
``etoro_importer.EtoroImporter``, NON qui.

Reference: https://api-portal.etoro.com/api-reference/
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

__version__ = "7.3.3"

__all__ = [
    "EtoroPosition",
    "EtoroOrder",
    "EtoroMirror",
    "EtoroClientPortfolio",
    "EtoroPortfolioResponse",
    "EtoroInstrument",
    "EtoroInstrumentRate",
]

log = logging.getLogger(__name__)


class _EtoroBase(BaseModel):
    """Base con configurazione comune: ignora campi extra, alias popolato."""

    model_config = ConfigDict(
        extra="ignore",        # API può aggiungere campi senza rompere
        populate_by_name=True,
        str_strip_whitespace=True,
    )


# ──────────────────────────────────────────────────── helpers di estrazione

def _try_get_int(data: dict[str, Any], *keys: str) -> int | None:
    """Prova ogni chiave e ritorna il primo valore int valido trovato."""
    for key in keys:
        val = data.get(key)
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                continue
    return None


def _try_get_str(data: dict[str, Any], *keys: str) -> str | None:
    """Prova ogni chiave e ritorna il primo valore str non-vuoto trovato."""
    for key in keys:
        val = data.get(key)
        if val is not None:
            s = str(val).strip()
            if s and s.upper() not in {"NONE", "NULL", "NAN", "N/A", ""}:
                return s
    return None


def _dig_nested(data: dict[str, Any], nested_key: str) -> dict[str, Any] | None:
    """Ritorna un dict annidato se esiste e non è vuoto."""
    nested = data.get(nested_key)
    if isinstance(nested, dict) and nested:
        return nested
    return None


# ───────────────────────────────────────────────────────────── posizioni
class EtoroPosition(_EtoroBase):
    """Singola posizione aperta nel portfolio reale.

    Schema da:
        GET /api/v1/trading/info/real/pnl
        -> clientPortfolio.positions[]

    ...

    Campi aggiunti v7.3.0:
      - order_id:              orderId dalla risposta (per tier-4 resolution)
      - order_type:            orderType dalla risposta

    Campi aggiunti v7.2.0:
      - ticker_from_api:      ticker estratto direttamente dalla risposta
      - display_name_from_api: nome strumento leggibile estratto dalla risposta

    Comportamento downstream (etoro_importer v7.3.0):
      Tier 1 — instrument_id noto → lookup /instruments come prima.
      Tier 2 — solo ticker_from_api → nessun lookup.
      Tier 3 — solo order_id → lookup GET /orders/{orderId} per instrumentID.
      Tier 4 — nessun identificatore → posizione scartata.
    """

    # ────────────────────────────────────────────── identificatori
    position_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("positionID", "positionId", "position_id"),
    )
    cid: int | None = Field(
        default=None,
        validation_alias=AliasChoices("CID", "cid", "Cid"),
    )
    instrument_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "instrumentID", "instrumentId", "InstrumentID", "instrument_id"
        ),
    )

    # ★ NUOVO v7.2.0: ticker e nome estratti direttamente dalla risposta
    ticker_from_api: str | None = Field(default=None)
    display_name_from_api: str | None = Field(default=None)

    open_date_time: datetime = Field(alias="openDateTime")
    open_rate: float = Field(alias="openRate")
    is_buy: bool = Field(alias="isBuy")         # True=LONG, False=SHORT
    take_profit_rate: float | None = Field(default=None, alias="takeProfitRate")
    stop_loss_rate: float | None = Field(default=None, alias="stopLossRate")
    amount: float
    leverage: int
    units: float
    total_fees: float = Field(default=0.0, alias="totalFees")
    initial_amount_in_dollars: float = Field(
        default=0.0, alias="initialAmountInDollars"
    )
    initial_units: float | None = Field(default=None, alias="initialUnits")

    # v7.3.2: pnL e closeRate vengono promossi da unrealizedPnL dal validator
    pnl: float = Field(default=0.0, alias="pnL")
    close_rate: float | None = Field(default=None, alias="closeRate")
    timestamp: datetime | None = None

    mirror_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("mirrorID", "mirrorId", "mirror_id"),
    )

    # ★ NUOVO v7.3.0: esponiamo orderId/orderType (prima ignorati da extra="ignore")
    order_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("orderID", "orderId", "order_id"),
    )
    order_type: int | None = Field(
        default=None,
        validation_alias=AliasChoices("orderType", "OrderType", "order_type"),
    )

    @property
    def direction(self) -> str:
        """LONG o SHORT, derivato da is_buy."""
        return "LONG" if self.is_buy else "SHORT"

    @property
    def best_ticker(self) -> str | None:
        """Miglior ticker disponibile: ticker_from_api o '#<instrument_id>'."""
        if self.ticker_from_api:
            return self.ticker_from_api
        if self.instrument_id is not None:
            return f"#{self.instrument_id}"
        return None

    @property
    def is_resolvable(self) -> bool:
        """True se abbiamo abbastanza info per creare una riga nel DataFrame."""
        return (
            self.instrument_id is not None
            or self.ticker_from_api is not None
            or self.order_id is not None
        )

    # ─────────────────────────────────────────────── pre-validator v7.2.0
    @model_validator(mode="before")
    @classmethod
    def _extract_fields_from_nested(cls, data: Any) -> Any:
        """Estrae instrument_id e ticker da tutte le strutture annidate note."""
        if not isinstance(data, dict):
            return data

        result = dict(data)  # shallow copy per non mutare l'originale

        # ── Fase 1: instrument_id ─────────────────────────────────────────
        if result.get("instrumentId") is None:
            position_id_val = result.get("positionId")

            # --- Top-level fields ---
            iid = _try_get_int(
                result,
                "InstrumentID",
                "instrument_id",
                "StockId",
                "stockId",
                "assetId",
                "AssetID",
                "securityId",
                "SecurityID",
                "symbolId",
                "SymbolId",
            )

            # Usa 'id' top-level solo se è DIVERSO dal positionId
            if iid is None:
                raw_id = result.get("id")
                if raw_id is not None and raw_id != position_id_val:
                    try:
                        iid = int(raw_id)
                    except (ValueError, TypeError):
                        pass

            # --- Nested: instrument ---
            if iid is None:
                nested = _dig_nested(result, "instrument")
                if nested:
                    iid = _try_get_int(nested, "instrumentId", "id")

            # --- Nested: instrumentData ---
            if iid is None:
                nested = _dig_nested(result, "instrumentData")
                if nested:
                    iid = _try_get_int(nested, "instrumentId", "id")

            # --- Nested: positionData ---
            if iid is None:
                nested = _dig_nested(result, "positionData")
                if nested:
                    iid = _try_get_int(nested, "instrumentId", "InstrumentID")

            # --- Nested: symbolData ---
            if iid is None:
                nested = _dig_nested(result, "symbolData")
                if nested:
                    iid = _try_get_int(nested, "instrumentId", "id")

            # --- Nested: asset ---
            if iid is None:
                nested = _dig_nested(result, "asset")
                if nested:
                    iid = _try_get_int(nested, "instrumentId", "id")

            if iid is not None:
                result["instrumentId"] = iid
                log.debug("etoro.instrument_id_recovered_from_nested instrument_id=%s", iid)

        # ── Fase 2: ticker_from_api ───────────────────────────────────────
        ticker: str | None = None
        ticker = _try_get_str(
            result,
            "symbol",
            "ticker",
            "symbolFull",
            "Symbol",
            "Ticker",
        )
        nested_keys = (
            "instrument",
            "instrumentData",
            "symbolData",
            "asset",
            "positionData",
        )
        ticker_field_candidates = (
            "symbol",
            "ticker",
            "displayName",
            "name",
            "symbolFull",
            "exchangeSymbol",
            "Symbol",
            "Ticker",
            "DisplayName",
        )
        if ticker is None:
            for nk in nested_keys:
                nested = _dig_nested(result, nk)
                if nested:
                    ticker = _try_get_str(nested, *ticker_field_candidates)
                    if ticker:
                        break
        if ticker is not None:
            result["ticker_from_api"] = ticker.upper().strip()

        # ── Fase 3: display_name_from_api ─────────────────────────────────
        display_name: str | None = None
        display_name = _try_get_str(
            result,
            "displayName",
            "assetName",
            "name",
            "instrumentName",
        )
        if display_name is None:
            for nk in nested_keys:
                nested = _dig_nested(result, nk)
                if nested:
                    display_name = _try_get_str(
                        nested,
                        "displayName",
                        "name",
                        "assetName",
                        "instrumentName",
                    )
                    if display_name:
                        break
        if display_name is not None:
            result["display_name_from_api"] = display_name.strip()

        # ── Diagnostica (solo se ENTRAMBI mancano) ────────────────────────
        if result.get("instrumentId") is None and result.get("ticker_from_api") is None:
            found_nested = [k for k in nested_keys if isinstance(result.get(k), dict)]
            log.warning(
                "etoro.position_unresolvable — keys=%s nested=%s",
                sorted(result.keys()),
                found_nested,
            )

        return result

    # ─────────────────────────────────────────────── NEW v7.3.2: promote unrealizedPnL
    @model_validator(mode="before")
    @classmethod
    def _promote_unrealized_pnl_fields(cls, data: Any) -> Any:
        """Estrae pnL, closeRate e timestamp da unrealizedPnL (se annidati)."""
        if not isinstance(data, dict):
            return data
        unrealized = data.get("unrealizedPnL")
        if not isinstance(unrealized, dict):
            return data

        data = dict(data)  # shallow copy per non modificare l'input
        if "pnL" not in data and "pnL" in unrealized:
            data["pnL"] = unrealized["pnL"]
        if "closeRate" not in data and "closeRate" in unrealized:
            data["closeRate"] = unrealized["closeRate"]
        if "timestamp" not in data and "timestamp" in unrealized:
            data["timestamp"] = unrealized["timestamp"]
        return data


# ───────────────────────────────────────────────────────────── ordini / mirror
class EtoroOrder(_EtoroBase):
    """Ordine pendente (non ancora eseguito).
    Schema: clientPortfolio.orders[]
    """
    order_id: int = Field(alias="orderId")
    cid: int
    open_date_time: datetime = Field(alias="openDateTime")
    instrument_id: int = Field(alias="instrumentId")
    is_buy: bool = Field(alias="isBuy")
    rate: float | None = None
    amount: float
    leverage: int
    units: float
    take_profit_rate: float | None = Field(default=None, alias="takeProfitRate")
    stop_loss_rate: float | None = Field(default=None, alias="stopLossRate")


class EtoroMirror(_EtoroBase):
    """Mirror = un'istanza di copytrading di un altro investitore.
    Schema: clientPortfolio.mirrors[]
    """
    mirror_id: int = Field(alias="mirrorId")
    cid: int
    parent_cid: int = Field(alias="parentCid")
    parent_username: str = Field(default="", alias="parentUsername")
    is_paused: bool = Field(default=False, alias="isPaused")
    initial_investment: float = Field(default=0.0, alias="initialInvestment")
    available_amount: float = Field(default=0.0, alias="availableAmount")
    closed_positions_net_profit: float = Field(
        default=0.0, alias="closedPositionsNetProfit"
    )
    started_copy_date: datetime | None = Field(
        default=None, alias="startedCopyDate"
    )
    positions: list[EtoroPosition] = Field(default_factory=list)


class EtoroClientPortfolio(_EtoroBase):
    """Container principale di tutte le info del portfolio.
    Schema: response.clientPortfolio
    """
    credit: float = 0.0
    unrealized_pnl: float = Field(default=0.0, alias="unrealizedPnL")
    bonus_credit: float = Field(default=0.0, alias="bonusCredit")
    positions: list[EtoroPosition] = Field(default_factory=list)
    orders: list[EtoroOrder] = Field(default_factory=list)
    mirrors: list[EtoroMirror] = Field(default_factory=list)


class EtoroPortfolioResponse(_EtoroBase):
    """Top-level response da GET /trading/info/real/pnl."""
    client_portfolio: EtoroClientPortfolio = Field(alias="clientPortfolio")


# ─────────────────────────────────────────────────────────── instruments
class EtoroInstrument(_EtoroBase):
    """Strumento (azione, ETF, crypto, FX, commodity).

    Risolve instrument_id <-> ticker simbolico.
    Schema: GET /api/v1/market-data/instruments?instrumentIds=...
    """
    instrument_id: int = Field(alias="instrumentId")
    symbol: str = ""
    ticker: str = ""
    symbol_full: str = Field(default="", alias="symbolFull")
    display_name: str = Field(default="", alias="displayName")
    name: str = ""
    asset_class_id: int | None = Field(default=None, alias="assetClassId")
    exchange_id: int | None = Field(default=None, alias="exchangeId")
    sector_id: int | None = Field(default=None, alias="sectorId")
    precision: int = Field(default=2, alias="precision")
    is_traded: bool = Field(default=True, alias="isTraded")

    @property
    def best_symbol(self) -> str:
        """Ritorna il simbolo più rappresentativo disponibile, preferendo symbolFull."""
        return self.symbol_full or self.ticker or self.symbol or self.display_name or str(self.instrument_id)


class EtoroInstrumentRate(_EtoroBase):
    """Quote live per uno strumento.

    Schema: GET /api/v1/market-data/rates?instrumentIds=...
    """
    instrument_id: int = Field(alias="instrumentId")
    bid: float | None = None
    ask: float | None = None
    last_rate: float | None = Field(default=None, alias="lastExecution")  # Fix: corretta mappatura API
    timestamp: datetime | None = None
    conversion_rate_ask: float | None = Field(default=None, alias="conversionRateAsk")
    conversion_rate_bid: float | None = Field(default=None, alias="conversionRateBid")

    @property
    def mid_price(self) -> float | None:
        """Prezzo mid (media bid/ask) se disponibili."""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2.0
        return self.last_rate


def parse_portfolio_response(payload: dict[str, Any]) -> EtoroPortfolioResponse:
    """Parsing safe di un payload arbitrario in EtoroPortfolioResponse."""
    return EtoroPortfolioResponse.model_validate(payload)