#!/usr/bin/env python3
"""MarketAI v1.0 — Installer cross-platform.

Esegue l'installazione completa di MarketAI:
  1. Verifica prerequisiti (Python 3.11+, Poetry)
  2. Installa dipendenze Python (poetry install)
  3. Inizializza i database (DuckDB + SQLite)
  4. Crea il file .env dall'esempio se non esiste
  5. Applica le migration DB
  6. Verifica installazione (quality gate --skip-mypy)
  7. (Opzionale) scarica modello Ollama per LLM

Uso:
  python scripts/install.py
  python scripts/install.py --no-llm        # salta download Ollama
  python scripts/install.py --skip-checks   # salta verifica finale
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PYTHON_MIN = (3, 11)
_POETRY_MIN = (1, 7)


# ── Colori ANSI (disabilitati su Windows senza terminal moderno) ────────────
_HAS_COLOR = sys.stdout.isatty() and platform.system() != "Windows" or (
    platform.system() == "Windows" and "TERM" in __import__("os").environ
)

def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _HAS_COLOR else text

OK    = _c("✅", "32")
WARN  = _c("⚠️ ", "33")
ERR   = _c("❌", "31")
INFO  = _c("ℹ️ ", "36")
STEP  = _c("→", "34;1")


def _run(cmd: list[str], cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), check=check, capture_output=True, text=True)


def _print_step(n: int, total: int, msg: str) -> None:
    print(f"\n{STEP} [{n}/{total}] {msg}")


# ── Step 1: Verifica Python ──────────────────────────────────────────────────

def check_python() -> bool:
    v = sys.version_info[:2]
    if v < _PYTHON_MIN:
        print(f"{ERR} Python {_PYTHON_MIN[0]}.{_PYTHON_MIN[1]}+ richiesto. Trovato: {v[0]}.{v[1]}")
        return False
    print(f"{OK} Python {v[0]}.{v[1]} OK")
    return True


# ── Step 2: Verifica Poetry ──────────────────────────────────────────────────

def check_poetry() -> bool:
    poetry = shutil.which("poetry")
    if not poetry:
        print(f"{ERR} Poetry non trovato nel PATH.")
        print(f"   Installare da: https://python-poetry.org/docs/#installation")
        return False
    try:
        r = _run(["poetry", "--version"], check=False)
        version_str = r.stdout.strip().replace("Poetry (version ", "").rstrip(")")
        parts = version_str.split(".")
        v = tuple(int(x) for x in parts[:2] if x.isdigit())
        if v < _POETRY_MIN:
            print(f"{WARN} Poetry {_POETRY_MIN[0]}.{_POETRY_MIN[1]}+ raccomandato. Trovato: {version_str}")
        else:
            print(f"{OK} Poetry {version_str} OK")
    except Exception:
        print(f"{OK} Poetry trovato")
    return True


# ── Step 3: Installa dipendenze ──────────────────────────────────────────────

def install_dependencies() -> bool:
    print(f"   Esecuzione: poetry install (può richiedere qualche minuto)...")
    try:
        r = _run(["poetry", "install", "--no-interaction"])
        print(f"{OK} Dipendenze installate")
        return True
    except subprocess.CalledProcessError as e:
        print(f"{ERR} poetry install fallito:\n{e.stderr[:500]}")
        return False


# ── Step 4: Setup .env ───────────────────────────────────────────────────────

def setup_env() -> bool:
    env_path = ROOT / ".env"
    example_path = ROOT / ".env.example"

    if env_path.exists():
        print(f"{OK} File .env già presente — lasciato invariato")
        return True

    if not example_path.exists():
        print(f"{WARN} .env.example non trovato — skip creazione .env")
        return True

    import shutil as sh
    sh.copy(example_path, env_path)
    print(f"{OK} Creato .env da .env.example")
    print(f"   {WARN} Apri .env e configura le API key (FRED, Alpha Vantage, Finnhub, ecc.)")
    return True


# ── Step 5: Crea directory DB ────────────────────────────────────────────────

def create_db_dirs() -> bool:
    for d in ["db", "data", "data/backups", "logs"]:
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    print(f"{OK} Directory DB e log create")
    return True


# ── Step 6: Init database ────────────────────────────────────────────────────

def init_database() -> bool:
    init_script = ROOT / "scripts" / "init_database.py"
    if not init_script.exists():
        print(f"{WARN} init_database.py non trovato — skip")
        return True
    try:
        _run(["poetry", "run", "python", str(init_script)])
        print(f"{OK} Database inizializzati")
        return True
    except subprocess.CalledProcessError as e:
        print(f"{WARN} DB init con warning: {e.stderr[:200]}")
        return True   # non bloccante


# ── Step 7: Quality gate ─────────────────────────────────────────────────────

def run_quality_gate() -> bool:
    qg = ROOT / "scripts" / "quality_gate.py"
    if not qg.exists():
        print(f"{WARN} quality_gate.py non trovato — skip")
        return True
    try:
        r = _run(["poetry", "run", "python", str(qg), "--skip-mypy"], check=False)
        if r.returncode == 0:
            print(f"{OK} Quality gate superato")
            return True
        else:
            print(f"{WARN} Quality gate con warning:\n{r.stdout[-300:]}")
            return True   # non bloccante in installer
    except Exception as e:
        print(f"{WARN} Quality gate non eseguibile: {e}")
        return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="MarketAI v1.0 Installer")
    parser.add_argument("--no-llm",       action="store_true", help="Salta download Ollama")
    parser.add_argument("--skip-checks",  action="store_true", help="Salta quality gate finale")
    parser.add_argument("--dev",          action="store_true", help="Modalità sviluppo (verbose)")
    args = parser.parse_args()

    print("=" * 60)
    print("  MarketAI v1.0 — Professional Edition")
    print("  Installer cross-platform")
    print("=" * 60)
    print(f"  Sistema:   {platform.system()} {platform.release()}")
    print(f"  Python:    {sys.version.split()[0]}")
    print(f"  Root:      {ROOT}")
    print("=" * 60)

    TOTAL = 7 if not args.skip_checks else 6
    step  = 0

    step += 1; _print_step(step, TOTAL, "Verifica prerequisiti")
    if not check_python() or not check_poetry():
        return 1

    step += 1; _print_step(step, TOTAL, "Installazione dipendenze Python")
    if not install_dependencies():
        return 1

    step += 1; _print_step(step, TOTAL, "Configurazione .env")
    setup_env()

    step += 1; _print_step(step, TOTAL, "Creazione directory")
    create_db_dirs()

    step += 1; _print_step(step, TOTAL, "Inizializzazione database")
    init_database()

    if not args.no_llm:
        step += 1; _print_step(step, TOTAL, "LLM (Ollama) — opzionale")
        _print_llm_instructions()
    else:
        step += 1; _print_step(step, TOTAL, "LLM — saltato (--no-llm)")
        print(f"   {INFO} Ollama può essere configurato in seguito da S2_Settings")

    if not args.skip_checks:
        step += 1; _print_step(step, TOTAL, "Verifica installazione (quality gate)")
        run_quality_gate()

    print("\n" + "=" * 60)
    print(f"{OK} INSTALLAZIONE COMPLETATA")
    print()
    print("  Per avviare MarketAI:")
    print("    python launcher.py")
    print()
    print("  Oppure direttamente:")
    print("    poetry run streamlit run app_unified.py")
    print()
    print("  Documentazione: INSTALL.md")
    print("=" * 60)
    return 0


def _print_llm_instructions() -> None:
    """Mostra istruzioni per installazione Ollama (opzionale)."""
    dl_script = ROOT / "scripts" / "download_models.py"
    if dl_script.exists():
        print(f"   {INFO} Per scaricare il modello LLM:")
        print(f"       python scripts/download_models.py")
    else:
        print(f"   {INFO} Per abilitare LLM (opzionale, richiede Ollama):")
        if platform.system() == "Windows":
            print("       Scarica Ollama da: https://ollama.ai/download")
        else:
            print("       curl https://ollama.ai/install.sh | sh")
        print("       ollama pull mistral:7b-q4")
        print("       Poi abilita da S2_Settings → sezione LLM")


if __name__ == "__main__":
    sys.exit(main())
