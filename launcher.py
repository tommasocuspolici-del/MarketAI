"""
MarketAI · Launcher
===================

Avvia Streamlit in background SENZA mostrare la finestra del prompt dei comandi
e apre il browser sul dashboard unificato.

Funziona in due modalità:
  1. Sviluppo:  python launcher.py
  2. Eseguibile: dist/MarketAI.exe  (compilato con PyInstaller --windowed)

Strategia (Windows-compatibile, no admin):
  · Rileva la directory del progetto (sys.executable se frozen, altrimenti __file__).
  · Imposta PYTHONUTF8=1 nell'environment del subprocess.
  · Avvia `poetry run streamlit run app_unified.py` con CREATE_NO_WINDOW.
  · Polling sulla porta finché Streamlit risponde, poi apre il browser.
  · Quando l'utente chiude la finestra del browser il processo Streamlit
    resta vivo: per chiuderlo, usare l'icona MarketAI in tray (futuro)
    o terminare il processo `python.exe` da Task Manager.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

# ───────────────────────────────────────────────────────────────────────────
# Configurazione
# ───────────────────────────────────────────────────────────────────────────
PORT: int = 8501
HOST: str = "localhost"
APP_FILE: str = "app_unified.py"
STARTUP_TIMEOUT_S: int = 30  # tempo massimo di attesa per Streamlit pronto

# Su Windows: nessuna console nera
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def project_dir() -> Path:
    """Restituisce la directory del progetto, sia in dev che da .exe."""
    if getattr(sys, "frozen", False):
        # Eseguito come .exe PyInstaller: il .exe sta nella root del progetto
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """True se Streamlit risponde sulla porta indicata."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False


def wait_for_server(host: str, port: int, timeout_s: int) -> bool:
    """Polling sulla porta finché Streamlit risponde o scade il timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if is_port_open(host, port):
            return True
        time.sleep(0.4)
    return False


def build_command(project: Path) -> list[str]:
    """Costruisce il comando Streamlit. Usa Poetry se disponibile."""
    app_path = project / APP_FILE

    # Comando preferito: Poetry (rispetta il venv del progetto)
    return [
        "poetry",
        "run",
        "streamlit",
        "run",
        str(app_path),
        f"--server.port={PORT}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--global.developmentMode=false",
    ]


def main() -> int:
    project = project_dir()
    app_path = project / APP_FILE

    if not app_path.exists():
        # Mostra errore con messagebox Windows (non console) se .exe
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"File non trovato:\n{app_path}\n\n"
                f"Posiziona MarketAI.exe nella radice del progetto.",
                "MarketAI · Errore di avvio",
                0x10,  # MB_ICONERROR
            )
        return 1

    # Environment del subprocess (Rule 19: UTF-8 ovunque)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = build_command(project)

    # Avvia Streamlit senza console (Windows) — i log vanno scartati
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(project),
            env=env,
            creationflags=CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        # Poetry non trovato nel PATH
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                "Poetry non trovato nel PATH di sistema.\n\n"
                "Installa Poetry o aggiungilo al PATH:\n"
                "  https://python-poetry.org/docs/#installation",
                "MarketAI · Dipendenza mancante",
                0x10,
            )
        return 2

    # Attendi che Streamlit sia pronto, poi apri il browser
    url = f"http://{HOST}:{PORT}"
    if wait_for_server(HOST, PORT, STARTUP_TIMEOUT_S):
        webbrowser.open(url)
    else:
        # Streamlit non si è avviato: kill e segnala
        proc.kill()
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"Streamlit non si è avviato entro {STARTUP_TIMEOUT_S} secondi.\n"
                f"Verifica che `poetry install` sia stato eseguito.",
                "MarketAI · Timeout",
                0x10,
            )
        return 3

    # Aspetta che Streamlit termini (l'utente chiude da Task Manager / browser tab)
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    return proc.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
