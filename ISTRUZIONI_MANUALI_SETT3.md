ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=ISTRUZIONI MANUALI — _extract_kpi in live_market_service.py
=

Se il patch automatico non riesce, modifica manualmente:

1. Trova la funzione _extract_kpi
2. Dopo le righe:
     last_close = float(ticker_data[close_col].iloc[-1])
     prev_close = ...

   Rinomina le variabili in last_close_raw e prev_close_raw

3. Dopo la sezione 'api_delta_pct', aggiungi:
     native_ccy = get_instrument_native_currency(yf_ticker)
     last_close = self._currency_converter.to_usd(last_close_raw, native_ccy)

4. Usa last_close (in USD) per l'override_store.resolve()
