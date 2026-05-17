"""shared.llm — LLM Integration Latente (Fase 9).

Tutti i moduli che possono beneficiare dell'LLM lo usano tramite LLMGateway.
Il gateway rimane INATTIVO (feature flag false) finché l'utente non lo attiva.
Tutti i moduli hanno template fallback deterministici (sempre corretti).

Regola privacy: LLMGateway chiama SOLO localhost:11434 (Ollama locale).
"""
from __future__ import annotations

__version__ = "1.0.0"
