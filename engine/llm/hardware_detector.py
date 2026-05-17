"""Hardware Detector — rileva RAM, disco, GPU disponibili per LLM.

Usato da S0_Health per mostrare raccomandazione modello.
Nessuna chiamata a Ollama — solo psutil/shutil/platform.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import Enum

__version__ = "1.0.0"
__all__ = ["HardwareDetector", "HardwareReport", "LLMErrorCode", "detect_hardware"]

# Requisiti RAM per ogni modello (GB)
MODEL_REQUIREMENTS: dict[str, float] = {
    "phi3:mini":     4.0,
    "mistral:7b-q4": 5.0,
    "mistral:7b":    8.0,
    "llama3:8b":     8.0,
}


class LLMErrorCode(str, Enum):
    RAM_INSUFFICIENT   = "ram_insufficient"
    OLLAMA_UNAVAILABLE = "ollama_unavailable"
    MODEL_NOT_FOUND    = "model_not_found"
    GPU_VRAM_LOW       = "gpu_vram_low"
    DISK_INSUFFICIENT  = "disk_insufficient"


LLM_ERROR_MESSAGES: dict[LLMErrorCode, str] = {
    LLMErrorCode.RAM_INSUFFICIENT:
        "RAM disponibile insufficiente ({free_ram:.1f} GB liberi). "
        "Minimo richiesto: 4.0 GB (phi3:mini). "
        "Chiudi applicazioni o aggiungi RAM.",
    LLMErrorCode.OLLAMA_UNAVAILABLE:
        "Ollama non è installato o non raggiungibile. "
        "Installa da https://ollama.ai · poi esegui: ollama serve",
    LLMErrorCode.MODEL_NOT_FOUND:
        "Il modello {model} non è scaricato. "
        "Esegui: ollama pull {model}",
    LLMErrorCode.GPU_VRAM_LOW:
        "GPU VRAM insufficiente ({vram:.1f} GB). "
        "Il modello girerà su CPU (più lento, ma funzionante).",
    LLMErrorCode.DISK_INSUFFICIENT:
        "Spazio disco insufficiente. Richiesto: {required:.1f} GB · "
        "Disponibile: {available:.1f} GB. Libera spazio e riprova.",
}


@dataclass
class HardwareReport:
    """Risultato rilevamento hardware per LLM."""
    total_ram_gb:     float
    available_ram_gb: float
    free_disk_gb:     float
    gpu_vram_gb:      float | None
    recommended_model: str | None
    supported_models:  list[str]
    errors:            list[str]

    @property
    def can_run_llm(self) -> bool:
        return self.available_ram_gb >= 4.0 and bool(self.recommended_model)


class HardwareDetector:
    """Rileva capacità hardware per eseguire modelli LLM locali."""

    def detect(self) -> HardwareReport:
        """Esegue il rilevamento hardware completo."""
        total_ram, avail_ram = self._get_ram()
        free_disk = self._get_disk()
        vram = self._get_gpu_vram()

        supported = [
            m for m, req in sorted(MODEL_REQUIREMENTS.items(), key=lambda x: x[1])
            if avail_ram >= req
        ]

        recommended: str | None = None
        if "mistral:7b-q4" in supported:
            recommended = "mistral:7b-q4"
        elif supported:
            recommended = supported[-1]

        errors: list[str] = []
        if avail_ram < 4.0:
            errors.append(
                LLM_ERROR_MESSAGES[LLMErrorCode.RAM_INSUFFICIENT].format(free_ram=avail_ram)
            )
        if free_disk < 5.0:
            errors.append(
                LLM_ERROR_MESSAGES[LLMErrorCode.DISK_INSUFFICIENT].format(
                    required=4.1, available=free_disk
                )
            )

        return HardwareReport(
            total_ram_gb=total_ram,
            available_ram_gb=avail_ram,
            free_disk_gb=free_disk,
            gpu_vram_gb=vram,
            recommended_model=recommended,
            supported_models=supported,
            errors=errors,
        )

    def _get_ram(self) -> tuple[float, float]:
        try:
            import psutil
            mem = psutil.virtual_memory()
            return mem.total / 1e9, mem.available / 1e9
        except ImportError:
            return 0.0, 0.0

    def _get_disk(self) -> float:
        try:
            usage = shutil.disk_usage("/")
            return usage.free / 1e9
        except Exception:
            return 0.0

    def _get_gpu_vram(self) -> float | None:
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                mb = float(result.stdout.strip().split("\n")[0])
                return mb / 1024.0
        except Exception:
            pass
        return None


def detect_hardware() -> HardwareReport:
    """Helper singleton-like per rilevamento hardware."""
    return HardwareDetector().detect()
