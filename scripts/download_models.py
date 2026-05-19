#!/usr/bin/env python3
"""MarketAI — Download modelli Ollama per LLM locale (Fase 11).

Scarica il modello LLM raccomandato in base all'hardware disponibile.
LLM è opzionale — MarketAI funziona completamente senza Ollama.

Uso:
  python scripts/download_models.py                  # auto-detect modello
  python scripts/download_models.py --model mistral:7b-q4
  python scripts/download_models.py --list           # elenca modelli supportati
  python scripts/download_models.py --check          # verifica Ollama senza scaricare
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_SUPPORTED_MODELS: list[dict] = [
    {
        "id": "mistral:7b-q4",
        "ram_gb": 5.0,
        "disk_gb": 4.1,
        "quality": "alta",
        "recommended_for": "8-16 GB RAM",
        "description": "Modello raccomandato — ottimo rapporto qualità/velocità",
    },
    {
        "id": "phi3:mini",
        "ram_gb": 4.0,
        "disk_gb": 2.3,
        "quality": "media",
        "recommended_for": "4-8 GB RAM",
        "description": "Modello compatto — per hardware con RAM limitata",
    },
    {
        "id": "mistral:7b",
        "ram_gb": 8.0,
        "disk_gb": 4.7,
        "quality": "alta",
        "recommended_for": "16+ GB RAM",
        "description": "Versione non quantizzata — massima qualità",
    },
]

_DEFAULT_MODEL = "mistral:7b-q4"


def _check_ollama() -> bool:
    """Verifica che Ollama sia installato e raggiungibile."""
    try:
        import httpx
        r = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        return r.status_code == 200
    except Exception:
        return False


def _list_models() -> None:
    """Stampa tabella modelli supportati."""
    print("\nModelli LLM supportati da MarketAI:\n")
    print(f"{'Modello':<20} {'RAM':<8} {'Disco':<8} {'Qualità':<8} {'Consigliato per'}")
    print("─" * 70)
    for m in _SUPPORTED_MODELS:
        star = " ★" if m["id"] == _DEFAULT_MODEL else "  "
        print(f"{m['id']:<20} {m['ram_gb']:.1f}GB{'':<3} {m['disk_gb']:.1f}GB{'':<3} "
              f"{m['quality']:<8} {m['recommended_for']}{star}")
    print()
    print("★ = modello raccomandato")


def _detect_recommended_model() -> str:
    """Rileva RAM disponibile e suggerisce il modello migliore."""
    try:
        from engine.llm.hardware_detector import detect_hardware
        hw = detect_hardware()
        if hw.recommended_model:
            return hw.recommended_model
    except Exception:
        pass
    return _DEFAULT_MODEL


def _pull_model(model_id: str) -> bool:
    """Esegue ollama pull per il modello specificato."""
    print(f"\n→ Download: {model_id}")
    m = next((m for m in _SUPPORTED_MODELS if m["id"] == model_id), None)
    if m:
        print(f"   Dimensione stimata: ~{m['disk_gb']:.1f} GB su disco")
        print(f"   RAM richiesta: {m['ram_gb']:.1f} GB durante l'inferenza")

    print(f"\n   Avvio: ollama pull {model_id}")
    print("   (il download può richiedere diversi minuti...)\n")

    try:
        proc = subprocess.run(
            ["ollama", "pull", model_id],
            check=True,
        )
        return proc.returncode == 0
    except FileNotFoundError:
        print("❌ Comando 'ollama' non trovato nel PATH.")
        _print_ollama_install_instructions()
        return False
    except subprocess.CalledProcessError as e:
        print(f"❌ Download fallito (exit code {e.returncode})")
        return False


def _enable_llm_flag() -> None:
    """Mostra istruzioni per abilitare LLM in MarketAI."""
    print("\n" + "─" * 50)
    print("Per abilitare LLM in MarketAI:")
    print()
    print("  1. Avvia Ollama come servizio:")
    print("       ollama serve")
    print()
    print("  2. In MarketAI, vai su S2_Settings → sezione LLM")
    print("       → abilita 'Master Switch (llm_engine_enabled)'")
    print()
    print("  3. Oppure modifica config/feature_flags.yaml:")
    print("       llm_engine_enabled: true")
    print("       llm_model: mistral:7b-q4")
    print()
    print("  Verifica stato LLM in S0_Health → sezione LLM Status")


def _print_ollama_install_instructions() -> None:
    import platform
    print("\n  Come installare Ollama:")
    if platform.system() == "Windows":
        print("    Scarica l'installer da: https://ollama.ai/download")
        print("    Oppure: winget install Ollama.Ollama")
    elif platform.system() == "Darwin":
        print("    brew install ollama")
        print("    oppure: https://ollama.ai/download")
    else:
        print("    curl -fsSL https://ollama.ai/install.sh | sh")
    print("  Dopo l'installazione, esegui: ollama serve")


def main() -> int:
    parser = argparse.ArgumentParser(description="MarketAI — Download modelli LLM")
    parser.add_argument("--model", default=None,
                        help=f"ID modello da scaricare (default: auto-detect)")
    parser.add_argument("--list",  action="store_true", help="Elenca modelli supportati")
    parser.add_argument("--check", action="store_true", help="Verifica Ollama senza scaricare")
    args = parser.parse_args()

    print("=" * 50)
    print("  MarketAI — Download Modelli LLM")
    print("  (Ollama è opzionale — MarketAI funziona senza LLM)")
    print("=" * 50)

    if args.list:
        _list_models()
        return 0

    # Verifica Ollama
    print("\n→ Verifica Ollama...")
    if _check_ollama():
        print("  ✅ Ollama raggiungibile (localhost:11434)")
    else:
        print("  ❌ Ollama non raggiungibile")
        print("  Assicurati che Ollama sia installato e avviato (ollama serve)")
        _print_ollama_install_instructions()
        if args.check:
            return 1
        print("\n  Vuoi procedere comunque? (ollama pull richiede Ollama avviato)")
        resp = input("  Procedi? [s/N] ").strip().lower()
        if resp not in ("s", "si", "y", "yes"):
            print("  Annullato.")
            return 0

    if args.check:
        return 0

    # Determina modello
    model_id = args.model
    if not model_id:
        model_id = _detect_recommended_model()
        print(f"\n  Modello rilevato per il tuo hardware: {model_id}")
        resp = input(f"  Scaricare {model_id}? [S/n] ").strip().lower()
        if resp in ("n", "no"):
            _list_models()
            model_id = input("  Inserisci ID modello: ").strip()
            if not model_id:
                print("  Annullato.")
                return 0

    if model_id not in [m["id"] for m in _SUPPORTED_MODELS]:
        print(f"  ⚠️  Modello '{model_id}' non nella lista supportata (procedo comunque)")

    ok = _pull_model(model_id)

    if ok:
        print(f"\n✅ Download completato: {model_id}")
        _enable_llm_flag()
    else:
        print(f"\n❌ Download fallito: {model_id}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
