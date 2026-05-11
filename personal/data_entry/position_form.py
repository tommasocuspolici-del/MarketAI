"""Form di creazione/modifica posizione manuale (Rule 41).

Risolve "non posso aggiungere posizioni senza il file XLSX di eToro".
Ogni posizione e' un record in UserDataStore con entity_type="position".

Validazione Pydantic v2 lato server (Rule 41 anti-pattern: validazione solo JS).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from personal.data_entry.user_data_store import UserDataStore, new_id, get_default_store

__version__ = "7.1.0"

__all__ = [
    "PositionInput",
    "list_positions",
    "save_position",
    "delete_position",
    "render_position_form",
]

ENTITY_TYPE = "position"

# Borse supportate. "ALTRO" e' il fallback per ticker generici.
SUPPORTED_EXCHANGES: tuple[str, ...] = (
    "NASDAQ",
    "NYSE",
    "XETRA",
    "LSE",
    "EURONEXT",
    "BORSA_IT",
    "TSE",
    "HKEX",
    "CRYPTO",
    "FOREX",
    "ALTRO",
)

# Valute supportate dal nostro FX service.
SUPPORTED_CURRENCIES: tuple[str, ...] = (
    "EUR",
    "USD",
    "GBP",
    "CHF",
    "JPY",
    "CNY",
    "AUD",
    "CAD",
    "USDT",
)


class PositionInput(BaseModel):
    """Schema validazione di una posizione manuale."""

    model_config = ConfigDict(str_strip_whitespace=True)

    position_id: str = Field(default_factory=new_id)
    ticker: str = Field(min_length=1, max_length=20)
    exchange: str = Field(min_length=2, max_length=12)
    quantity: float = Field(gt=0, description="Numero di unita' detenute")
    avg_cost: float = Field(gt=0, description="Prezzo medio di carico")
    current_price: float | None = Field(
        default=None, description="Prezzo corrente opzionale (override)"
    )
    open_date: date
    direction: str = Field(pattern="^(LONG|SHORT)$")
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    notes: str = Field(default="")
    source: str = Field(
        default="manual",
        description="Origine: 'manual' | 'etoro_import'",
    )

    # ────────────────────────────────────────────── validators
    @field_validator("ticker")
    @classmethod
    def _ticker_uppercase(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("currency")
    @classmethod
    def _currency_uppercase(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("exchange")
    @classmethod
    def _exchange_uppercase(cls, v: str) -> str:
        return v.strip().upper()

    # ────────────────────────────────────────────── helpers
    def market_value(self, current_price: float | None = None) -> float:
        """Valore corrente della posizione."""
        price = current_price or self.current_price or self.avg_cost
        sign = 1 if self.direction == "LONG" else -1
        return sign * self.quantity * price

    def cost_basis(self) -> float:
        """Costo totale di acquisto (o ricavo netto se SHORT)."""
        return self.quantity * self.avg_cost

    def to_payload(self) -> dict[str, Any]:
        """Serializza per UserDataStore."""
        return {
            "position_id": self.position_id,
            "ticker": self.ticker,
            "exchange": self.exchange,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "current_price": self.current_price,
            "open_date": self.open_date.isoformat(),
            "direction": self.direction,
            "currency": self.currency,
            "notes": self.notes,
            "source": self.source,
            "updated_at": datetime.utcnow().isoformat(timespec="seconds"),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PositionInput":
        """Deserializza da UserDataStore."""
        data = dict(payload)
        if isinstance(data.get("open_date"), str):
            data["open_date"] = date.fromisoformat(data["open_date"])
        return cls.model_validate(data)


# ────────────────────────────────────────────── persistence layer
def list_positions(store: UserDataStore | None = None) -> list[PositionInput]:
    """Ritorna tutte le posizioni salvate dall'utente."""
    s = store or get_default_store()
    records = s.list_by_type(ENTITY_TYPE)
    out: list[PositionInput] = []
    for r in records:
        try:
            out.append(PositionInput.from_payload(r.payload))
        except (ValueError, KeyError, TypeError):
            # Skip record corrotti — l'utente potra' eliminarli da UI
            continue
    return out


def save_position(
    position: PositionInput, store: UserDataStore | None = None
) -> None:
    """Salva o aggiorna una posizione."""
    s = store or get_default_store()
    s.upsert(ENTITY_TYPE, position.position_id, position.to_payload())


def delete_position(
    position_id: str, store: UserDataStore | None = None
) -> bool:
    """Elimina una posizione. True se ha eliminato qualcosa."""
    s = store or get_default_store()
    return s.delete(ENTITY_TYPE, position_id)


# ────────────────────────────────────────────── streamlit form
def render_position_form(
    existing: PositionInput | None = None,
    *,
    key: str = "position_form",
) -> PositionInput | None:  # pragma: no cover -- Streamlit-rendered
    """Renderizza il form Streamlit. Ritorna PositionInput se confermato.

    Args:
        existing: Se fornito, precompila il form (modalita' modifica).
        key: Chiave Streamlit univoca (per supportare piu' form sulla stessa pagina).

    Returns:
        PositionInput validato se l'utente ha confermato, None altrimenti.
    """
    try:
        import streamlit as st
    except ImportError:
        return None

    is_edit = existing is not None
    title = "✏️ Modifica posizione" if is_edit else "➕ Nuova posizione"
    st.subheader(title)

    with st.form(key=key, clear_on_submit=not is_edit):
        col1, col2 = st.columns(2)

        with col1:
            ticker = st.text_input(
                "Ticker *",
                value=existing.ticker if existing else "",
                placeholder="Es. AAPL, MSFT, BTC-USD",
                help="Simbolo del ticker. Esempio: per Apple su NASDAQ -> AAPL.",
                key=f"{key}_ticker",
            ).strip().upper()

            exchange = st.selectbox(
                "Borsa *",
                options=SUPPORTED_EXCHANGES,
                index=SUPPORTED_EXCHANGES.index(existing.exchange)
                if existing and existing.exchange in SUPPORTED_EXCHANGES
                else 0,
                key=f"{key}_exchange",
            )

            quantity = st.number_input(
                "Quantita' *",
                min_value=0.0001,
                value=float(existing.quantity) if existing else 1.0,
                step=0.001,
                format="%.4f",
                help="Unita' detenute (puo' essere frazionaria per ETF/crypto).",
                key=f"{key}_quantity",
            )

            currency = st.selectbox(
                "Valuta *",
                options=SUPPORTED_CURRENCIES,
                index=SUPPORTED_CURRENCIES.index(existing.currency)
                if existing and existing.currency in SUPPORTED_CURRENCIES
                else SUPPORTED_CURRENCIES.index("EUR"),
                help="Valuta in cui e' denominato il prezzo di carico.",
                key=f"{key}_currency",
            )

        with col2:
            avg_cost = st.number_input(
                "Prezzo medio di carico *",
                min_value=0.0001,
                value=float(existing.avg_cost) if existing else 100.0,
                step=0.01,
                format="%.4f",
                help="Prezzo medio di acquisto, al netto di commissioni.",
                key=f"{key}_avg_cost",
            )

            current_price_default = (
                float(existing.current_price)
                if existing and existing.current_price
                else 0.0
            )
            current_price = st.number_input(
                "Prezzo corrente (opzionale)",
                min_value=0.0,
                value=current_price_default,
                step=0.01,
                format="%.4f",
                help="Lascia 0 per usare automaticamente il prezzo live (yfinance).",
                key=f"{key}_current_price",
            )

            open_date_val = st.date_input(
                "Data apertura *",
                value=existing.open_date if existing else date.today(),
                max_value=date.today(),
                key=f"{key}_open_date",
            )

            direction = st.radio(
                "Direzione *",
                options=["LONG", "SHORT"],
                index=0 if not existing else ["LONG", "SHORT"].index(existing.direction),
                horizontal=True,
                help="LONG = acquisto. SHORT = vendita allo scoperto.",
                key=f"{key}_direction",
            )

        notes = st.text_area(
            "Note (opzionale)",
            value=existing.notes if existing else "",
            placeholder="Es. 'DCA mensile', 'Hedge su MSFT'",
            max_chars=500,
            key=f"{key}_notes",
        )

        submitted = st.form_submit_button(
            "💾 Salva modifiche" if is_edit else "➕ Aggiungi",
            type="primary",
        )

    if not submitted:
        return None

    # Validazione Pydantic lato server
    try:
        position = PositionInput(
            position_id=existing.position_id if existing else new_id(),
            ticker=ticker,
            exchange=exchange,
            quantity=quantity,
            avg_cost=avg_cost,
            current_price=current_price if current_price > 0 else None,
            open_date=open_date_val
            if isinstance(open_date_val, date)
            else date.today(),
            direction=direction,
            currency=currency,
            notes=notes,
            source=existing.source if existing else "manual",
        )
    except ValueError as exc:
        st.error(f"❌ Errore di validazione: {exc}")
        return None

    return position
