"""Policy unica per @st.cache_data TTL nelle pagine Streamlit.

Elimina i TTL numerici sparsi (P8 — ROADMAP_CODE_QUALITY_v1.0).
Ogni valore legge da OP_CONFIG dove disponibile; gli altri hanno un
razionale esplicito nel commento.

Uso::

    from presentation.ui.cache_policy import CACHE_TTL

    @st.cache_data(ttl=CACHE_TTL.MARKET_KPI)
    def _load_market_data():
        ...
"""
from __future__ import annotations

from shared.config.operational_config import OP_CONFIG


class _CacheTTL:
    """Namespace per i TTL delle cache. Non istanziare: usa CACHE_TTL."""

    # Real-time market data (yfinance) — stesso valore di LiveMarketService
    MARKET_KPI       = OP_CONFIG.cache.live_market_ttl_s          # 900s

    # Macro indicators (FRED) — dati daily/monthly
    MACRO_CONVICTION = OP_CONFIG.cache.macro_conviction_ttl_s      # 3600s

    # Instrument lookup (DuckDB) — mapping ticker, stabile
    INSTRUMENT_LOOKUP = OP_CONFIG.cache.instrument_lookup_ttl_s    # 86400s

    # Portafoglio / bilanci — cambiano raramente durante la sessione
    PORTFOLIO_TOTALS  = 300     # 5min
    FUNDAMENTALS      = 3600    # 1h: bilanci, dividendi, valutazioni

    # Dati equity e obbligazionari intraday
    EQUITIES          = 300     # 5min
    BONDS             = 3600    # 1h: curva dei tassi aggiornata raramente

    # Forex e commodity — più frequenti
    FOREX_COMMODITY   = 1800    # 30min

    # Alert e notifiche — cambiano spesso
    ALERT_HISTORY     = 120     # 2min

    # Backtesting / forecasting — calcoli pesanti
    BACKTESTING       = 900     # 15min: stesso del market KPI

    # Segnali engine (composite signal, regime) — letti da DuckDB al riavvio
    SIGNALS           = OP_CONFIG.cache.signals_disk_ttl_s           # 3600s

    # Senza cache: dati che cambiano ad ogni load
    STATIC            = 0


CACHE_TTL = _CacheTTL()
