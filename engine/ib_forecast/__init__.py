"""engine.ib_forecast — IB Forecast Engine (Fase 8).

Architettura two-stage:
  Stage 1: regex + Fed SEP + IMF/WB — pienamente funzionale senza LLM
  Stage 2: LLM parsing semantico (attivato in Fase 9 via ib_llm_extraction flag)

Regola 33: zero previsioni simulate — solo testi IB reali parsati.
Regola 34: forecast IB cachati 86400s — non ri-parsati ad ogni query.
"""
from __future__ import annotations

__version__ = "1.1.0"

from engine.ib_forecast.schemas import ExtractedForecast, IBConsensus, IBSignal
from engine.ib_forecast.ib_rss_fetcher import IBRSSFetcher
from engine.ib_forecast.forecast_extractor import ForecastExtractor
from engine.ib_forecast.consensus_builder import ConsensusBuilder
from engine.ib_forecast.fed_projections_parser import FedProjectionsParser
from engine.ib_forecast.imf_wb_outlook_fetcher import IMFWBOutlookFetcher
from engine.ib_forecast.ib_signal_generator import IBSignalGenerator

__all__ = [
    "ExtractedForecast", "IBConsensus", "IBSignal",
    "IBRSSFetcher", "ForecastExtractor", "ConsensusBuilder",
    "FedProjectionsParser", "IMFWBOutlookFetcher", "IBSignalGenerator",
]
