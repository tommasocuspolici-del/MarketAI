# 🚀 ROADMAP — MarketAI v11.0.0 · Fase Infrastruttura
> **v10.1.0 → v11.0.0** · Installer + Management UI + CLAUDE.md v2  
> Pianificazione: 15/06/2026 → 17/08/2026  
> Implementazione: 18/08/2026 → 06/09/2026  
> Implementazione: **Claude Code Pro (Opus 4.8)** · sessioni brevi (1–2h)

---

## 📊 Stato Ambiente — Dati Reali (da questionario)

| Parametro | Valore |
|-----------|--------|
| Python sistema | **3.14.5** ⚠️ (troppo nuovo, NON usare per il progetto) |
| Python in uso da Poetry | **3.12.10** ✅ |
| Path Python 3.12 | `C:\Users\Q256254\AppData\Local\Programs\Python\Python312\python.exe` |
| Poetry | **v2.4.1** ✅ |
| Git | **v2.54.0** ✅ |
| Venv attuale | `C:\Users\Q256254\Desktop\PERSONALE\MarketAI\market-ai\MarketAI 1.0\.venv` |
| Progetto attuale | **Desktop** (fuori dalla cartella documenti, attualmente non avviabile) |
| Target installazione | `%APPDATA%\MarketAI\` = `C:\Users\Q256254\AppData\Roaming\MarketAI\` |
| Backup | `%LOCALAPPDATA%\MarketAI\backups\` |
| GitHub | `https://github.com/tommasocuspolici-del/MarketAI` (privato, PAT) |
| Remote | `origin` configurato su git locale |
| API Keys | Tutte già configurate nel `.env` |
| Ollama | Non installato (installazione futura su dispositivo dedicato) |

---

## ⚠️ Vincoli Tecnici Critici

### 1 — Conflitto Python 3.14.5 vs 3.12.10
```
PROBLEMA:  Sistema ha Python 3.14.5 come default.
           Molte dipendenze del progetto (numpy, scipy, vectorbt, etc.)
           non sono compatibili o non testate su 3.14.x.
SOLUZIONE: L'installer deve esplicitamente specificare Python 3.12:
           poetry env use "C:\Users\Q256254\AppData\Local\Programs\Python\Python312\python.exe"
VERIFICA:  poetry env info → deve mostrare "Python: 3.12.10"
```

### 2 — Path con spazi nel percorso attuale
```
PROBLEMA:  "MarketAI 1.0" contiene uno spazio → può causare problemi in subprocess
SOLUZIONE: La copia verso %APPDATA%\MarketAI\ risolve il problema
           (il percorso di destinazione non ha spazi)
```

### 3 — install.py esistente (scripts/install.py — v1)
```
PROBLEMA:  install.py attuale funziona solo in-place (non migra il progetto)
           Non ha GUI, non gestisce la migrazione verso AppData
SOLUZIONE: Creare install_v2.py (nuovo file, NON sovrascrivere l'originale)
           L'originale resta per compatibilità backward
```

### 4 — Il progetto è attualmente non avviabile
```
STATO:     Cartella su Desktop, venv non integro (spostato da Documenti)
PIANO:     La prima sessione Opus deve essere un fresh install nella nuova location
           NON tentare di riparare il venv attuale
```

---

## 🎯 Obiettivi v11.0.0

### Obbligatori (18/08 → 06/09/2026)

```
[OB-1] Installer completo con GUI tkinter
        · Verifica Python 3.12 / Git / Poetry
        · Copia progetto → %APPDATA%\MarketAI\ (esclude .venv, cache, *.pyc)
        · Ricrea venv con Python 3.12.10 esplicito
        · Copia .env (già configurato) nella nuova location
        · Init DB (DuckDB migrations + SQLite migrations Alembic)
        · Quality gate: pytest -m regression -q
        · Crea shortcut desktop

[OB-2] Management UI standalone (tkinter + system tray)
        · Avvio/stop dashboard Streamlit
        · Backup ZIP locale → %LOCALAPPDATA%\MarketAI\backups\
        · Push GitHub (PAT, auto-commit message)
        · Backup + Push combinato
        · Test suite (3 preset) con report in reports/

[OB-3] CLAUDE.md v2 (già creato in fase pianificazione)
        · Mappa completa 40+ pagine
        · Vincoli Python documentati
        · Pattern anti-regressione
        · Session startup checklist
```

### Facoltativi (solo se OB-1/2/3 completati e rimane tempo)

```
[OPT-1] UI Refactoring: pywebview shell per Streamlit (zero regressioni)
[OPT-2] Auto-build MarketAI_Manager.exe via PyInstaller
```

---

## 📅 FASE 0 — Pianificazione (15/06 → 17/08/2026)

### Timeline

```
Settimana 1–2  (16/06–30/06)  ✅ Questionario compilato
                               ✅ CLAUDE.md v2 creato (questo documento + CLAUDE_v2.md)
                               ✅ Roadmap v2 creata

Settimana 3–4  (01/07–15/07)  Preparare specifiche sessioni Opus
                               · Rivedere e approvare design Management UI
                               · Verificare CLAUDE.md v2 su test-run con Opus

Settimana 5–6  (16/07–31/07)  Preparare ambiente pre-implementazione
                               · Scaricare Python 3.12 se non presente
                               · Verificare PAT GitHub ancora valido
                               · Testare Poetry 2.4.1 su cartella pulita

Settimana 7–9  (01/08–17/08)  Finalizzazione
                               · CLAUDE.md v2 revisionato dopo feedback
                               · Template prompts per sessioni Opus pronti
                               · Checklist pre-implementazione completa
```

### Deliverable Fase 0
```
□ CLAUDE_v2.md — approvato
□ MARKETAI_ROADMAP_v2.md — approvato (questo file)
□ Python 3.12.10 verificato avviabile su macchina
□ PAT GitHub verificato e non scaduto
□ Cartella %APPDATA%\MarketAI\ verificata scrivibile (test manuale)
□ Progetto corrente sul Desktop non corrotto (zippato come backup)
```

---

## 📅 FASE 1 — Implementazione (18/08 → 06/09/2026)

> Ogni sessione: 1–2 ore · Claude Code Pro (Opus 4.8)  
> Aprire ogni sessione con: `CLAUDE_v2.md` + `logs/session_YYYYMMDD.log`  
> Prima di ogni sessione: `poetry run pytest -m regression -q` → 0 failed

---

### Sessione 1 — Installer: Prerequisiti e Struttura (18–19/08)

**Task:** Creare `scripts/install_v2.py` — foundation con GUI tkinter

**NON toccare:** `scripts/install.py` (lasciare invariato), `pyproject.toml`, `poetry.lock`

**Prompt di apertura Opus:**
```
Leggi CLAUDE_v2.md completamente. 
Task: Sessione 1 — creare scripts/install_v2.py
Non modificare scripts/install.py né pyproject.toml.
```

**File da creare:**
```
scripts/
  install_v2.py          ← installer principale (NUOVO)
  installer_prereqs.py   ← funzioni prerequisiti (NUOVO)
  installer_copy.py      ← funzioni copia file (NUOVO, vuoto per ora)
```

**Contenuto install_v2.py — Struttura:**
```python
# scripts/install_v2.py
"""
MarketAI v11.0.0 — Installer con GUI tkinter
Migra il progetto verso %APPDATA%\MarketAI\
e ricrea il venv con Python 3.12.10

Uso:
  python scripts/install_v2.py          # GUI interattiva
  python scripts/install_v2.py --cli    # Solo terminale (no GUI)
"""
```

**Contenuto installer_prereqs.py:**
```python
# Funzioni:
# check_python_312() → Path | None
#   Cerca Python 3.12.x in: AppData/Local/Programs/Python/Python312/
#   Fallback: py -3.12 --version
#   Fallback 2: WHERE python3.12
#
# check_git() → bool
#   shutil.which("git")
#
# check_poetry() → str | None
#   Ritorna versione stringa o None
#
# check_install_git_winget() → bool
#   subprocess.run(["winget", "install", "Git.Git", "--silent"])
#
# check_install_poetry_official() → bool
#   Scarica https://install.python-poetry.org/ con urllib.request
#   Esegue: python install-poetry.py
```

**GUI tkinter (in install_v2.py):**
```
Finestra 500×350: "MarketAI — Installer v11.0.0"
  Progress bar indeterminate durante check prerequisiti
  Label con step corrente
  TextArea (read-only) con log in tempo reale
  Button "Installa" → disabilitato durante install
  Button "Annulla"
```

**Definition of Done — Sessione 1:**
```
□ install_v2.py avviabile con: poetry run python scripts/install_v2.py
□ installer_prereqs.py: tutte le funzioni con type hints + test unitari
□ GUI si apre senza errori su Windows 11
□ check_python_312() trova correttamente C:\...\Python312\python.exe
□ tests/test_installer_prereqs.py: ≥ 5 test, 0 failed
□ pytest -m regression: 0 failed (nessuna regressione)
□ mypy --strict su install_v2.py: 0 errors
```

---

### Sessione 2 — Installer: Copia File e Migrazione (20–21/08)

**Task:** Implementare `installer_copy.py` — copia progetto → `%APPDATA%\MarketAI\`

**NON toccare:** tutto il codebase di produzione (engine/, personal/, shared/, etc.)

**Funzioni da implementare in installer_copy.py:**
```python
EXCLUDE_PATTERNS = [
    ".venv", "venv", "__pycache__", ".hypothesis",
    "*.pyc", "*.pyo", ".coverage", ".coverage.*",
    "coverage.xml", "htmlcov", "data/cache",
    "*.log", ".mypy_cache", ".ruff_cache",
    ".pytest_cache", "dist", "build", "*.egg-info",
    "MarketAI.exe",  # sarà copiato separatamente
]

def get_target_path() -> Path:
    """Ritorna %APPDATA%\MarketAI\ — crea se non esiste."""

def get_source_path() -> Path:
    """Ritorna cartella del progetto corrente (parent di scripts/)."""

def calculate_copy_size(src: Path) -> int:
    """Calcola dimensione totale file da copiare (esclude EXCLUDE_PATTERNS)."""

def copy_project(
    src: Path,
    dst: Path,
    progress_callback: Callable[[int, int, str], None] | None = None
) -> tuple[int, int]:
    """
    Copia src → dst escludendo EXCLUDE_PATTERNS.
    progress_callback(files_done, files_total, current_file)
    Ritorna (files_copied, files_skipped).
    """

def copy_env_file(src: Path, dst: Path) -> bool:
    """Copia .env dalla sorgente (già configurato) → destinazione."""
```

**Update install_v2.py:**
- Step 2 nella GUI: "Copia progetto → AppData"
- Progress bar con callback da `copy_project()`
- Mostra "N file copiati" al termine

**Definition of Done — Sessione 2:**
```
□ installer_copy.py: tutte le funzioni con type hints
□ copy_project() funziona su: "MarketAI 1.0" (path con spazio)
□ EXCLUDE_PATTERNS verificati: .venv non viene copiato
□ .env viene copiato correttamente (preserva API keys)
□ Progress callback funziona (aggiorna GUI)
□ tests/test_installer_copy.py: ≥ 8 test, 0 failed
□ pytest -m regression: 0 failed
```

---

### Sessione 3 — Installer: Venv + DB Init + Shortcut (22–24/08)

**Task:** Completare installer — venv 3.12, init DB, shortcut desktop

**File da modificare:** `scripts/install_v2.py` (aggiungere step 3–5)  
**NON toccare:** `scripts/init_database.py`, `shared/db/duckdb_migrator.py`

**Step 3 — Venv con Python 3.12:**
```python
def recreate_venv(project_path: Path, python_312_path: Path) -> bool:
    """
    1. cd project_path
    2. poetry env remove --all (se venv corrotto)
    3. poetry env use <python_312_path>
    4. poetry install --no-interaction
    5. Verifica: poetry run python --version → deve essere 3.12.x
    """
```

**Step 4 — Init DB:**
```python
def init_database(project_path: Path) -> bool:
    """
    Esegue scripts/init_database.py via poetry run.
    Non bloccante: errori non-critici sono solo warning.
    """
```

**Step 5 — Shortcut Desktop:**
```python
def create_desktop_shortcut(project_path: Path) -> bool:
    """
    Crea MarketAI.lnk sul Desktop che punta a:
    Target: <project_path>\launcher.py
    Interprete: poetry run python (via BAT wrapper)
    Icona: MarketAI.exe (se presente) o icona Python
    Usa: winshell o win32com.shell (già disponibili via Poetry)
    Alternativa: crea MarketAI_start.bat come fallback
    """
```

**Step 6 — Quality gate post-install:**
```python
def run_smoke_tests(project_path: Path) -> bool:
    """
    poetry run pytest -m regression -q --tb=short
    Timeout: 120 secondi
    Non bloccante (mostra solo warning se fallisce)
    """
```

**Completamento GUI install_v2.py:**
```
Step 1: ✅ Prerequisiti verificati
Step 2: ✅ File copiati (N files → %APPDATA%\MarketAI\)
Step 3: ⏳ Creazione ambiente Python 3.12... (2–5 minuti)
Step 4: ⏳ Inizializzazione database...
Step 5: ✅ Shortcut desktop creato
Step 6: ⏳ Verifica installazione (smoke test)...
────────────────────────────────────────
✅ INSTALLAZIONE COMPLETATA
   Avvia MarketAI dal shortcut sul Desktop
   oppure: management_ui.py → [🚀 Avvia Dashboard]
```

**Definition of Done — Sessione 3:**
```
□ recreate_venv() usa Python 3.12.10 esplicitamente
□ poetry env info dopo install → Python: 3.12.x confermato
□ DB inizializzato: tabelle DuckDB e SQLite presenti
□ Shortcut desktop funzionante (o BAT wrapper)
□ Installer end-to-end: < 15 minuti su macchina reale
□ tests/test_installer_complete.py: integration test di base
□ pytest -m regression: 0 failed
```

---

### Sessione 4 — Management UI: Struttura Base + Tray (25–26/08)

**Task:** Creare `management_ui.py` — finestra principale + system tray

**REGOLA ASSOLUTA:** management_ui.py NON importa NULLA da engine/personal/shared/bridge  
Solo stdlib + `pystray` + `Pillow` (aggiungere a pyproject.toml come dipendenze)

**Aggiunta a pyproject.toml (unica modifica consentita):**
```toml
pystray = "^0.19"
Pillow = "^10.0"    # già probabile dipendenza tramite altre librerie
```

**management_ui.py — Struttura:**
```python
"""
MarketAI Management UI
Finestra standalone per gestione del progetto.
NON importa engine/, personal/, shared/, bridge/.
Solo: tkinter, subprocess, pathlib, zipfile, datetime, threading, shutil, os, pystray, PIL
"""
CREATE_NO_WINDOW = 0x08000000  # Windows subprocess senza finestra

# Configurazione letta da file JSON locale (non da config/ del progetto)
# %LOCALAPPDATA%\MarketAI\ui_config.json
# {
#   "project_path": "C:\\...\\AppData\\Roaming\\MarketAI",
#   "backup_path": "C:\\...\\AppData\\Local\\MarketAI\\backups",
#   "github_remote": "origin",
#   "github_branch": "main"
# }
```

**Layout finestra (800×520 px, no resize):**
```
┌─────────────────────────────────────────────────────┐
│  🟢 MarketAI Manager  v11.0.0                        │
│  📁 C:\Users\...\AppData\Roaming\MarketAI            │
├─────────────────────────────────────────────────────┤
│  DASHBOARD                                           │
│  [🚀 Avvia Dashboard]    [⏹ Ferma Dashboard]         │
│  Status: ⚫ Dashboard ferma                          │
├─────────────────────────────────────────────────────┤
│  BACKUP & VERSIONAMENTO                             │
│  [💾 Backup locale]  [📤 Push GitHub]  [💾+📤 Combo] │
├─────────────────────────────────────────────────────┤
│  TEST & QUALITÀ                                     │
│  [🧪 Esegui Test]       [📊 Vedi report]             │
├─────────────────────────────────────────────────────┤
│  ⚙ Impostazioni                    🔕 Minimizza     │
├─────────────────────────────────────────────────────┤
│ Log: [                                            ] │
│      [... output in tempo reale scrollabile ...   ] │
└─────────────────────────────────────────────────────┘
```

**System Tray:**
```
Icona: cerchio verde/rosso (PIL generato dinamicamente)
Menu contestuale:
  ▸ Apri Manager
  ─────────────
  ▸ Avvia Dashboard
  ▸ Ferma Dashboard
  ─────────────
  ▸ Esci
```

**Comportamento finestra:**
- [X] chiude la finestra ma l'app rimane nel tray
- Doppio click sull'icona tray → riapre la finestra
- "Esci" nel menu tray → termina completamente l'app

**Definition of Done — Sessione 4:**
```
□ management_ui.py: nessun import da engine/personal/shared/bridge
□ Finestra si apre correttamente su Windows 11
□ System tray: icona visibile, menu funzionante
□ [X] finestra → nascosta nel tray (non chiusa)
□ Doppio click tray → finestra riaperta
□ Status bar: aggiornato al cambiamento stato
□ Log textarea: scrollabile e aggiornata in tempo reale
□ Config JSON: creato automaticamente se non esiste
```

---

### Sessione 5 — Management UI: Dashboard e Backup (27–28/08)

**Task:** Implementare [🚀 Avvia] [⏹ Ferma] [💾 Backup]

**NON toccare:** codebase di produzione, pyproject.toml (già aggiornato nella s4)

**[🚀 Avvia Dashboard]:**
```python
def start_dashboard():
    """
    1. Kill porta 8501 (netstat + taskkill) se occupata
    2. subprocess.Popen(["poetry", "run", "streamlit", "run", "app_unified.py",
                         "--server.port=8501", "--server.headless=true"],
                        cwd=project_path, CREATE_NO_WINDOW)
    3. Thread di polling: is_port_open(8501) ogni 500ms per max 45s
    4. Quando pronto: webbrowser.open("http://localhost:8501")
    5. Status bar → "🟢 Dashboard attiva"
    6. Tray icon → verde
    """

def stop_dashboard():
    """
    taskkill /F /PID <streamlit_pid>
    oppure: netstat -ano → trova PID su 8501 → taskkill
    Status bar → "⚫ Dashboard ferma"
    Tray icon → rosso
    """
```

**[💾 Backup locale]:**
```python
BACKUP_EXCLUDE = [
    ".venv", "__pycache__", ".hypothesis", "*.pyc",
    ".coverage*", "htmlcov", ".mypy_cache", ".ruff_cache",
    ".pytest_cache", "data/cache", "*.log",
    "dist", "build", "db/*.duckdb.wal",
]

def run_backup():
    """
    1. ZIP_NAME = f"MarketAI_backup_{datetime.now():%Y%m%d_%H%M%S}.zip"
    2. Destinazione: %LOCALAPPDATA%\MarketAI\backups\ZIP_NAME
    3. zipfile.ZipFile con compressione ZIP_DEFLATED
    4. Itera project_path, esclude BACKUP_EXCLUDE
    5. Progress bar nella log area (% completato)
    6. Al termine: "✅ Backup creato: N MB → path"
    7. Salva last_backup_path in ui_config.json
    """
```

**Definition of Done — Sessione 5:**
```
□ Avvio Dashboard: Streamlit risponde su localhost:8501 dopo click
□ Browser si apre automaticamente quando Streamlit è pronto
□ Ferma Dashboard: processo terminato, porta libera
□ Status bar: aggiornata correttamente in entrambi i casi
□ Backup ZIP: creato in %LOCALAPPDATA%\MarketAI\backups\
□ ZIP verificabile manualmente con 7-Zip
□ .venv non incluso nel backup (verificare con zipfile.namelist())
□ .env incluso nel backup (contiene API keys)
□ Progress visibile nella log area
```

---

### Sessione 6 — Management UI: GitHub Push e Test Runner (29–31/08)

**Task:** Implementare [📤 Push GitHub] e [🧪 Esegui Test]

**NON toccare:** `.git/` directory, `pyproject.toml`

**[📤 Push GitHub] — PAT Authentication:**
```python
def configure_git_pat(project_path: Path, pat: str) -> bool:
    """
    Configura PAT per autenticazione HTTPS GitHub.
    Usa git credential store (non hardcoda PAT nel codice).
    subprocess.run(["git", "config", "credential.helper", "store"], cwd=project_path)
    Scrive ~/.git-credentials: https://<user>:<PAT>@github.com
    """

def push_to_github(project_path: Path, commit_message: str | None = None) -> tuple[bool, str]:
    """
    1. git status --porcelain → verifica file modificati
    2. Se nessuna modifica: "Nessuna modifica da committare"
    3. msg = commit_message or f"chore: backup automatico {datetime.now():%Y-%m-%d %H:%M}"
    4. git add -A
    5. git commit -m "<msg>"
    6. git push origin main
    7. Ritorna (success, output_log)
    """
```

**Dialog PAT (prima configurazione):**
```
Se ~/.git-credentials non contiene github.com:
  Dialog: "Configura GitHub Personal Access Token"
  Campo testo (password): inserisci PAT
  [OK] → configure_git_pat() → salva credentials
  Il PAT NON viene salvato in ui_config.json
```

**[🧪 Esegui Test] — Test Suite Runner:**
```python
TEST_PRESETS = {
    "Fast (< 2 min)":     ["poetry", "run", "pytest", "-m", "regression", "-q", "--tb=short"],
    "Standard (< 15 min)":["poetry", "run", "pytest", "--tb=short", "-q", "--ignore=tests/integration"],
    "Completo (< 60 min)":["poetry", "run", "pytest", "--cov", "--cov-fail-under=89", "--tb=short"],
}

def run_test_suite(preset: str) -> str:
    """
    1. Dialog: scelta preset
    2. subprocess.Popen(cmd, cwd=project_path, CREATE_NO_WINDOW,
                        stdout=PIPE, stderr=STDOUT, text=True)
    3. Thread lettore: legge stdout riga per riga → aggiorna log textarea
    4. Al termine: estrae sommario (passed/failed/error)
    5. Salva report in: <project_path>/reports/test_YYYYMMDD_HHMMSS.txt
    6. Aggiorna status: "✅ N passed, ❌ M failed"
    """
```

**[📊 Vedi report]:**
```
Lista file in reports/ ordinata per data
Click → apre in textarea scrollabile separata
```

**[💾+📤 Combo]:**
```
Esegue run_backup() poi push_to_github() in sequenza
Log unificato in textarea
```

**Definition of Done — Sessione 6:**
```
□ Push funziona su https://github.com/tommasocuspolici-del/MarketAI
□ Commit creato con messaggio automatico
□ PAT configurato una sola volta (persiste in git credentials)
□ Dialog PAT appare solo se credenziali non configurate
□ Test Suite: output in tempo reale nella log area
□ Report salvato in reports/ e visualizzabile
□ Preset "Fast": completa in < 2 minuti
□ Status aggiornato: "✅ N passed" o "❌ N failed"
```

---

### Sessione 7 — Impostazioni + Polish + Build EXE (01–03/09)

**Task:** Finestre Impostazioni, polish UI, build `MarketAI_Manager.exe`

**Dialog ⚙ Impostazioni:**
```
Sezione PERCORSI:
  Progetto:    [campo testo] [Sfoglia...]
  Backup:      [campo testo] [Sfoglia...]

Sezione GITHUB:
  Remote:      [campo testo] (default: origin)
  Branch:      [campo testo] (default: main)

Sezione TEST:
  Preset default: [dropdown] Fast/Standard/Completo

[Salva]  [Annulla]
```

**Build MarketAI_Manager.exe (PyInstaller):**
```bash
# In pyproject.toml aggiungere script build:
# [tool.poetry.scripts]
# build-manager = "scripts.build_manager:main"

# File: scripts/build_manager.py
# pyinstaller management_ui.py
#   --name MarketAI_Manager
#   --windowed
#   --onefile
#   --icon=assets/icon.ico  (o usare icona generata con PIL)
#   --add-data "assets;assets"
```

**Polish UI:**
- Icona tray: generata con PIL (cerchio verde = dashboard attiva, rosso = ferma)
- Font: `Segoe UI 10` (nativo Windows 11)
- Colori: `#1e1e1e` background, `#4CAF50` verde, `#f44336` rosso, `#2196F3` blu
- Cursore busy durante operazioni lunghe
- Tutti i messaggi di errore in dialog (non solo nel log)

**Definition of Done — Sessione 7:**
```
□ Dialog Impostazioni: salva e carica da ui_config.json
□ Modifiche Impostazioni riflesse immediatamente
□ MarketAI_Manager.exe: si avvia senza Python installato
□ .exe: dimensione < 80 MB
□ Tutti i pulsanti testati con scenario di errore (es: GitHub offline)
□ Errori mostrati in dialog messagebox, non solo nel log
```

---

### Sessione 8 — Test End-to-End + Bug Fix (04–06/09)

**Task:** Validazione completa del ciclo installer + management UI

**Checklist validazione manuale:**
```
INSTALLER:
□ Esegui install_v2.py da Desktop\PERSONALE\MarketAI\market-ai\MarketAI 1.0\
□ Progetto copiato correttamente in %APPDATA%\MarketAI\
□ .env presente con tutte le API keys
□ poetry env info → Python 3.12.10
□ DB inizializzati (no errori)
□ Shortcut desktop funzionante
□ Totale: < 15 minuti

MANAGEMENT UI:
□ [🚀 Avvia] → Streamlit su localhost:8501 in < 30 secondi
□ [⏹ Ferma] → processo terminato, porta libera
□ [💾 Backup] → ZIP in %LOCALAPPDATA%\MarketAI\backups\
□ ZIP apribile con 7-Zip: .venv assente, .env presente
□ [📤 Push] → commit visibile su GitHub
□ [💾+📤 Combo] → entrambe le operazioni
□ [🧪 Test Fast] → < 2 min, mostra passed/failed
□ [📊 Vedi report] → report leggibile
□ Tray icon: verde quando dashboard attiva

NESSUNA REGRESSIONE:
□ poetry run pytest -m regression → 0 failed
□ Dashboard E1, E6, K1, M3, P2 funzionanti con dati reali
□ mypy --strict su management_ui.py → 0 errors
```

**Buffer bug fix:** 04–06 settembre

---

## 📋 Struttura File Finale v11.0.0

```
%APPDATA%\MarketAI\
├── app_unified.py
├── launcher.py                           (invariato)
├── management_ui.py                      ★ NUOVO
├── MarketAI.exe                          (invariato)
├── MarketAI_Manager.exe                  ★ NUOVO
├── CLAUDE.md                             ★ v2 (CLAUDE_v2.md → rinominato)
├── .env                                  (copiato dall'originale)
├── pyproject.toml                        (modifica: + pystray, + Pillow)
├── poetry.lock                           (rigenerato da poetry install)
├── config/                               (invariato)
├── engine/                               (invariato)
├── personal/                             (invariato)
├── bridge/                               (invariato)
├── presentation/                         (invariato)
├── shared/                               (invariato)
├── scripts/
│   ├── install.py                        (invariato — v1, backward compat)
│   ├── install_v2.py                     ★ NUOVO
│   ├── installer_prereqs.py              ★ NUOVO
│   ├── installer_copy.py                 ★ NUOVO
│   ├── build_manager.py                  ★ NUOVO
│   └── ... (tutti gli altri invariati)
├── logs/
│   └── session_YYYYMMDD.log              ★ NUOVO (generato da test runner)
├── reports/
│   └── test_YYYYMMDD_HHMMSS.txt          ★ NUOVO (generato da UI)
└── tests/
    ├── test_installer_prereqs.py         ★ NUOVO
    ├── test_installer_copy.py            ★ NUOVO
    ├── test_installer_complete.py        ★ NUOVO
    └── ... (tutti gli altri invariati)
```

**Percorsi separati (NON nella cartella progetto):**
```
%LOCALAPPDATA%\MarketAI\
  backups/
    MarketAI_backup_20260819_143022.zip
    MarketAI_backup_20260821_091500.zip
  ui_config.json          ← config Management UI
```

---

## 📊 Metriche di Successo v11.0.0

| Metrica | Target |
|---------|--------|
| Installer: tempo totale | < 15 minuti |
| Installer: poetry install | < 5 minuti |
| Dashboard: avvio da click | < 30 secondi |
| Backup ZIP (progetto ~2 GB) | < 3 minuti |
| Push GitHub | < 60 secondi |
| Test Suite Fast preset | < 2 minuti |
| MarketAI_Manager.exe size | < 80 MB |
| Coverage post-sessioni | ≥ 89% (no regressione) |
| Test: 0 regressioni vs v10.1.0 | 3080+ passing |
| mypy --strict management_ui.py | 0 errors |

---

## 🧩 Anti-Pattern da Evitare nelle Sessioni Opus

```
❌ management_ui.py importa shared.* o engine.* o personal.*
   → Solo stdlib + pystray + Pillow

❌ Installer sovrascrive scripts/install.py
   → Crea install_v2.py (nuovo file)

❌ Installer usa "python" senza specificare 3.12
   → Sempre: poetry env use <path_python_312>

❌ pyproject.toml modificato fuori da sessioni pianificate
   → Solo nella Sessione 4 (aggiunta pystray + Pillow)

❌ PAT GitHub hardcoded in codice o in ui_config.json
   → Solo in git credential store (~/.git-credentials)

❌ Backup include .venv/
   → BACKUP_EXCLUDE sempre verificato

❌ DB reinizialized senza backup preventivo
   → init_database.py --force solo se DB corrotto/vuoto

❌ Test suite con -x (stop al primo fail) in produzione
   → Usare --tb=short -q, sempre completo

❌ Sessione Opus senza "pytest -m regression" iniziale
   → Obbligatorio: 0 failed prima di modificare qualsiasi file
```

---

## 📝 Template Prompt Apertura Sessione Opus

```
Ciao. Leggi completamente CLAUDE.md prima di scrivere qualsiasi codice.

=== SESSIONE N — [nome sessione] ===

Contesto ambiente:
- Progetto in: %APPDATA%\MarketAI\
- Python: 3.12.10 (venv Poetry — NON usare 3.14.5 di sistema)
- poetry run pytest -m regression → [N passed / 0 failed] ← eseguito ora

Task di questa sessione:
[descrizione specifica]

File da creare/modificare:
- [file1.py] → [cosa fare]
- [file2.py] → [cosa fare]

NON toccare:
- [lista file protetti]

Definition of Done:
□ [criterio 1]
□ [criterio 2]
...

Inizia con: poetry run pytest -m regression -q --tb=short
Poi procedi con il task.
```

---

*MarketAI v11.0.0 · Roadmap Infrastruttura v2.0 · 21/06/2026*  
*Pianificazione: Claude Sonnet 4.6 · Implementazione: Claude Code Pro (Opus 4.8)*  
*Hardware: Ryzen 5 5600 · RX 6700 8GB · 16GB RAM · Windows 11*
