"""
MarketAI · Launcher
===================

Avvia Streamlit in background SENZA mostrare la finestra del prompt dei comandi
e apre il browser sul dashboard unificato.

Funziona in due modalità:
  1. Sviluppo:  python launcher.py
  2. Eseguibile: dist/MarketAI.exe  (compilato con PyInstaller --windowed)

Strategia (Windows-compatibile, no admin):
  · Chiude automaticamente sessioni Streamlit precedenti sulla porta 8501.
  · Verifica che il venv Poetry sia integro (poetry env info).
  · Avvia `poetry run streamlit run app_unified.py` con CREATE_NO_WINDOW.
  · Mostra una finestra di avvio con progress bar durante il boot.
  · Polling sulla porta finché Streamlit risponde, poi apre il browser.
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
STARTUP_TIMEOUT_S: int = 45  # tempo massimo di attesa per Streamlit pronto
KILL_GRACE_S: float = 2.0   # secondi attesi dopo SIGTERM prima di SIGKILL

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# ───────────────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────────────

def project_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def msgbox(title: str, text: str, icon: int = 0x10) -> None:
    """Mostra una MessageBox Windows (no console)."""
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, title, icon)


def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, socket.timeout, OSError):
        return False


def kill_port(port: int) -> int:
    """
    Termina tutti i processi che ascoltano su *port* (Windows: netstat+taskkill).
    Restituisce il numero di processi terminati.
    """
    if sys.platform != "win32":
        return 0

    killed = 0
    try:
        # netstat -ano elenca PID dei processi in ascolto
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
        )
        pids: set[str] = set()
        for line in result.stdout.splitlines():
            parts = line.split()
            # cerchiamo righe tipo: TCP  0.0.0.0:8501  0.0.0.0:0  LISTENING  <PID>
            if len(parts) >= 5 and f":{port}" in parts[1] and "LISTENING" in parts[3]:
                pids.add(parts[4])
            # oppure: TCP  [::]:8501 ...
            elif len(parts) >= 5 and f":{port}" in parts[1]:
                pids.add(parts[4])

        for pid in pids:
            subprocess.run(
                ["taskkill", "/F", "/PID", pid],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
            )
            killed += 1

        if killed:
            time.sleep(KILL_GRACE_S)  # lascia che le porte si liberino
    except Exception:
        pass

    return killed


def verify_venv(project: Path) -> bool:
    """
    Controlla che `poetry env info` restituisca un venv valido.
    Restituisce False solo se Poetry stesso non è raggiungibile.
    """
    try:
        r = subprocess.run(
            ["poetry", "env", "info", "--path"],
            cwd=str(project),
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
        return r.returncode == 0 and bool(r.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def wait_for_server(host: str, port: int, timeout_s: int) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if is_port_open(host, port):
            return True
        time.sleep(0.4)
    return False


def build_command(project: Path) -> list[str]:
    app_path = project / APP_FILE
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


# ───────────────────────────────────────────────────────────────────────────
# Finestra di avvio (tkinter — opzionale, incluso in CPython standard)
# ───────────────────────────────────────────────────────────────────────────

def _splash_thread(stop_event: object) -> None:
    """Mostra una finestra di attesa finché stop_event non viene settato."""
    try:
        import threading
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("MarketAI")
        root.geometry("380x110")
        root.resizable(False, False)
        root.attributes("-topmost", True)

        # Centra la finestra
        root.update_idletasks()
        x = (root.winfo_screenwidth() - 380) // 2
        y = (root.winfo_screenheight() - 110) // 2
        root.geometry(f"+{x}+{y}")

        tk.Label(root, text="MarketAI · Avvio in corso…", font=("Segoe UI", 11, "bold")).pack(pady=(18, 4))
        tk.Label(root, text="Attendi il caricamento del dashboard nel browser.", font=("Segoe UI", 9), fg="#555").pack()

        bar = ttk.Progressbar(root, mode="indeterminate", length=320)
        bar.pack(pady=12)
        bar.start(12)

        def _check() -> None:
            if getattr(stop_event, "is_set", lambda: False)():
                root.destroy()
            else:
                root.after(200, _check)

        root.after(200, _check)
        root.mainloop()
    except Exception:
        pass  # tkinter non disponibile nell'exe — silenzioso


# ───────────────────────────────────────────────────────────────────────────
# Entry point
# ───────────────────────────────────────────────────────────────────────────

def main() -> int:
    project = project_dir()
    app_path = project / APP_FILE

    if not app_path.exists():
        msgbox(
            "MarketAI · Errore di avvio",
            f"File non trovato:\n{app_path}\n\n"
            f"Posiziona MarketAI.exe nella radice del progetto.",
        )
        return 1

    # 1. Chiudi sessioni precedenti sulla porta
    prev = kill_port(PORT)
    _ = prev  # usato solo per feedback futuro (tray icon)

    # 2. Verifica venv
    if not verify_venv(project):
        msgbox(
            "MarketAI · Dipendenza mancante",
            "Poetry non trovato nel PATH di sistema.\n\n"
            "Installa Poetry o aggiungilo al PATH:\n"
            "  https://python-poetry.org/docs/#installation",
        )
        return 2

    # 3. Finestra di attesa (thread separato)
    import threading
    stop_event = threading.Event()
    splash = threading.Thread(target=_splash_thread, args=(stop_event,), daemon=True)
    splash.start()

    # 4. Environment subprocess (UTF-8 ovunque — Rule 19)
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    # 5. Avvia Streamlit
    cmd = build_command(project)
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
        stop_event.set()
        msgbox(
            "MarketAI · Dipendenza mancante",
            "Poetry non trovato nel PATH di sistema.\n\n"
            "Installa Poetry o aggiungilo al PATH:\n"
            "  https://python-poetry.org/docs/#installation",
        )
        return 2

    # 6. Polling → apri browser → chiudi splash
    url = f"http://{HOST}:{PORT}"
    ready = wait_for_server(HOST, PORT, STARTUP_TIMEOUT_S)
    stop_event.set()

    if ready:
        webbrowser.open(url)
    else:
        proc.kill()
        msgbox(
            "MarketAI · Timeout",
            f"Streamlit non si è avviato entro {STARTUP_TIMEOUT_S} secondi.\n\n"
            f"Possibili cause:\n"
            f"  · `poetry install` non eseguito\n"
            f"  · Dipendenze mancanti nel venv\n"
            f"  · Porta {PORT} bloccata dal firewall\n\n"
            f"Prova ad eseguire dal terminale:\n"
            f"  poetry run streamlit run app_unified.py",
        )
        return 3

    # 7. Resta vivo finché Streamlit è attivo
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    return proc.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
