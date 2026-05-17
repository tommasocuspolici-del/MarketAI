"""engine.ib_forecast — IB Forecast Engine (Fase 8).

Architettura two-stage:
  Stage 1: regex + Fed SEP + IMF/WB — pienamente funzionale senza LLM
  Stage 2: LLM parsing semantico (attivato in Fase 9 via ib_llm_extraction flag)

Regola 33: zero previsioni simulate — solo testi IB reali parsati.
Regola 34: forecast IB cachati 86400s — non ri-parsati ad ogni query.
"""
from __future__ import annotations

__version__ = "1.0.0"
