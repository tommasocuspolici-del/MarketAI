# 🔴 ROADMAP — MarketAI v15.0.0 · Fase 4: UI Nativa e Produzione
> **v14.0.0 → v15.0.0** · UI Nativa pywebview · Persistenza Sessioni · Scalabilità  
> Prerequisito: v14.0.0 completato (N-BEATS · Backtesting Realistico · FastAPI)  
> Pianificazione: Claude Sonnet 4.6 · Implementazione: Claude Code Pro (Opus 4.8)  
> Sessioni: 7 sessioni · Durata stimata: 1–2h ciascuna · Totale: ~5 settimane

---

## 📊 Stato Pre-Fase 4

| Parametro | Valore |
|-----------|--------|
| Versione base | v14.0.0 (FastAPI attivo · N-BEATS · Backtesting costi) |
| UI attuale | Streamlit su localhost:8501 (browser) |
| Obiettivo UI | Applicazione nativa Windows con pywebview (niente browser visibile) |
| Persistenza | Assente (refresh → configurazioni perse) |
| Scalabilità | Processo singolo, no parallelismo training |
| Hardware | Ryzen 5 5600 · RX 6700 8GB · 16GB RAM |

---

## 🎯 Obiettivi v15.0.0

### Obbligatori

```
[OB-1] Shell pywebview per Streamlit (UI nativa, zero browser visible)
        · MarketAI si apre come finestra nativa Windows (non localhost)
        · Integrazione con Management UI esistente (pulsante Avvia)
        · Icona taskbar e sistema tray aggiornati
        · Zero regressioni su tutte le 40+ pagine dashboard

[OB-2] Persistenza sessioni e configurazioni
        · SQLite: salvataggio configurazioni analisi (simbolo, modello, periodo)
        · Storico analisi con possibilità di ricaricare
        · Preferenze utente (tema, lingua, pagina default)
        · Esportazione/importazione configurazioni JSON

[OB-3] Sistema di logging metriche e model drift detection
        · Salvataggio metriche predittive per ogni previsione (SQLite)
        · Job schedulato: confronto metriche recenti vs baseline rolling
        · Alert se MAE aumenta > 20% rispetto alla baseline
        · Dashboard S2_Settings: sezione "Salute Modelli"
```

### Facoltativi (solo se OB-1/2/3 completi)

```
[OPT-1] Build MarketAI.exe con PyInstaller che include pywebview + Streamlit
[OPT-2] Parallelismo CPU: joblib multiprocessing per benchmark multi-asset
[OPT-3] Celery + Redis per job asincroni (overkill per uso personale — valutare)
```

---

## ⚠️ Vincoli Critici — LEGGERE PRIMA DI OGNI SESSIONE

```
PYWEBVIEW SU WINDOWS 11:
  · Richiede Microsoft Edge WebView2 Runtime (già installato su W11)
  · pywebview usa WebView2 come engine → non serve browser esterno
  · Streamlit continua a girare su localhost (invisibile all'utente)
  · pywebview crea una finestra nativa che mostra localhost:8501

SEQUENZA AVVIO CORRETTA (non cambiare):
  1. Avvia Streamlit: subprocess (background, no window)
  2. Attendi porta 8501 disponibile (polling, max 45s)
  3. Apri pywebview su http://localhost:8501
  4. pywebview gestisce chiusura finestra → kill Streamlit

ANTI-REGRESSIONE MASSIMA:
  · Streamlit continua a girare invariato (pagine non toccate)
  · pywebview è solo un wrapper: NON modificare l'app Streamlit
  · Se pywebview fallisce → fallback automatico su webbrowser.open()
  · Test pages: le 40+ pagine non vengono modificate in questa fase

COMPATIBILITÀ PYINSTALLER + PYWEBVIEW:
  · Richiede --hidden-import webview, --collect-all webview
  · WebView2 Runtime NON viene bundlato nell'exe (installato separatamente)
  · Verificare su macchina pulita senza development environment

PERSISTENZA — REGOLE DB:
  · Nuovo database SQLite separato: db/user_sessions.db
  · NON toccare il SQLite principale del progetto (posizioni, profili)
  · Tabelle: analysis_sessions, user_preferences, model_metrics
```

---

## 🧩 Anti-Pattern Vietati v15.0.0

```
❌ pywebview che modifica le pagine Streamlit
   → pywebview è solo shell: le pagine rimangono identiche

❌ Persistenza che usa lo stesso SQLite delle posizioni eToro
   → db/user_sessions.db separato e dedicato

❌ Model drift alert che interrompe l'analisi in corso
   → Solo notifica passiva (sidebar warning), mai blocco

❌ PyInstaller build senza test su macchina pulita
   → Test obbligatorio senza Python installato (VM o macchina separata)

❌ Avvio pywebview prima che Streamlit sia pronto
   → Polling porta 8501 con timeout 45s (identico a Management UI)

❌ configurazioni utente salvate in engine/ o shared/
   → Solo in personal/user_preferences/ o db/user_sessions.db

❌ Sessione Opus senza regression test iniziale → 0 failed obbligatorio

❌ pywebview con window title hardcoded
   → Sempre da config: f"MarketAI v{__version__}"
```

---

## 📅 SESSIONE 1 — pywebview Shell: Struttura Base (1–2h)

**Obiettivo:** Creare il launcher pywebview che wrappa Streamlit come app nativa

**NON toccare:** Streamlit app, Management UI esistente, pyproject.toml (aggiornato qui)

**Aggiungere a pyproject.toml (unica modifica consentita questa sessione):**
```toml
pywebview = "^5.1"
```

**File da creare:**
```
launcher_webview.py         ← NUOVO: entry point pywebview
webview_bridge.py           ← NUOVO: comunicazione Python↔JS (optional API)
scripts/
  start_webview.py          ← NUOVO: avvio con gestione errori e fallback
```

**launcher_webview.py:**
```python
# launcher_webview.py
"""MarketAI — Launcher con pywebview (UI nativa Windows).

Questo file sostituisce il browser come visualizzatore della dashboard.
Streamlit continua a girare su localhost (invisibile).
pywebview crea una finestra nativa che mostra http://localhost:8501.

Avvio:
    poetry run python launcher_webview.py

Fallback automatico se pywebview non disponibile:
    Apre http://localhost:8501 nel browser di sistema (comportamento attuale).

Chiusura:
    Chiudere la finestra nativa → termina anche Streamlit (cleanup automatico).
"""
from __future__ import annotations
import subprocess
import sys
import time
import os
import socket
import webbrowser
import threading
import structlog

log = structlog.get_logger(__name__)

STREAMLIT_PORT = 8501
STREAMLIT_URL = f"http://localhost:{STREAMLIT_PORT}"
STARTUP_TIMEOUT_S = 45
WINDOW_TITLE = "MarketAI Professional"
WINDOW_WIDTH = 1440
WINDOW_HEIGHT = 900
CREATE_NO_WINDOW = 0x08000000   # Windows: subprocess senza finestra cmd

def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """Verifica se una porta è in ascolto."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except (OSError, ConnectionRefusedError):
        return False

def start_streamlit() -> subprocess.Popen:
    """Avvia Streamlit in background (senza finestra cmd visibile)."""
    cmd = [
        sys.executable, "-m", "streamlit", "run", "app_unified.py",
        f"--server.port={STREAMLIT_PORT}",
        "--server.headless=true",
        "--server.enableCORS=false",
        "--server.enableXsrfProtection=false",
    ]
    log.info("streamlit.starting", cmd=" ".join(cmd))
    process = subprocess.Popen(
        cmd,
        creationflags=CREATE_NO_WINDOW,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process

def wait_for_streamlit(timeout_s: int = STARTUP_TIMEOUT_S) -> bool:
    """Attende che Streamlit sia pronto. Ritorna True se OK, False se timeout."""
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        if is_port_open(STREAMLIT_PORT):
            log.info("streamlit.ready", elapsed_s=round(time.monotonic() - start, 1))
            return True
        time.sleep(0.5)
    log.error("streamlit.timeout", timeout_s=timeout_s)
    return False

def open_webview(streamlit_process: subprocess.Popen) -> None:
    """Apre la finestra nativa pywebview."""
    try:
        import webview  # type: ignore[import]
    except ImportError:
        log.warning("pywebview.not_installed", fallback="browser")
        webbrowser.open(STREAMLIT_URL)
        streamlit_process.wait()
        return

    window = webview.create_window(
        title=WINDOW_TITLE,
        url=STREAMLIT_URL,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        resizable=True,
        min_size=(1024, 600),
        confirm_close=False,
    )

    def on_closed():
        """Callback: finestra chiusa → termina Streamlit."""
        log.info("webview.closed")
        streamlit_process.terminate()

    window.events.closed += on_closed

    # Avvia pywebview (blocca fino alla chiusura della finestra)
    webview.start(debug=False)
    log.info("webview.exited")

def main() -> None:
    """Entry point principale."""
    # Se già in ascolto → non riavviare Streamlit (già aperto da Management UI)
    if is_port_open(STREAMLIT_PORT):
        log.info("streamlit.already_running")
        streamlit_proc = None
        open_webview_no_process()
        return

    streamlit_proc = start_streamlit()

    if not wait_for_streamlit():
        log.error("startup.failed")
        streamlit_proc.terminate()
        sys.exit(1)

    open_webview(streamlit_proc)

def open_webview_no_process() -> None:
    """Apre pywebview senza gestire il processo Streamlit (già avviato)."""
    try:
        import webview
        window = webview.create_window(WINDOW_TITLE, STREAMLIT_URL,
                                       width=WINDOW_WIDTH, height=WINDOW_HEIGHT)
        webview.start(debug=False)
    except ImportError:
        webbrowser.open(STREAMLIT_URL)

if __name__ == "__main__":
    main()
```

**Aggiornare management_ui.py — pulsante [🚀 Avvia Dashboard]:**
```python
# Modificare start_dashboard() per usare launcher_webview.py invece di Streamlit diretto

def start_dashboard():
    """
    Avvia MarketAI con pywebview (finestra nativa).
    Fallback: browser se pywebview non disponibile.
    """
    cmd = [sys.executable, "launcher_webview.py"]
    self._streamlit_process = subprocess.Popen(
        cmd, cwd=self._project_path, creationflags=CREATE_NO_WINDOW
    )
    # Il launcher_webview gestisce internamente Streamlit + pywebview
    self._update_status("🟢 Dashboard aperta")
```

**Definition of Done — Sessione 1:**
```
□ launcher_webview.py: avvio + wait + webview funzionante su Windows 11
□ Finestra nativa apre http://localhost:8501 (non browser esterno)
□ Chiusura finestra → Streamlit terminato (no processi zombie)
□ Fallback browser funzionante se pywebview non disponibile
□ is_port_open(): già in ascolto → non riavvia Streamlit
□ Management UI [🚀 Avvia]: usa launcher_webview.py
□ pytest -m regression: 0 failed (Streamlit invariato)
□ pywebview = "^5.1" in pyproject.toml
□ Window title: "MarketAI Professional" (non hardcoded in stringa)
```

---

## 📅 SESSIONE 2 — pywebview: Barra Nativa e Icona (1–2h)

**Obiettivo:** Migliorare l'esperienza UI nativa con barra titolo, icona e shortcut tastiera

**NON toccare:** Streamlit dashboard, pagine esistenti

**File da modificare/creare:**
```
launcher_webview.py          ← aggiungere configurazioni finestra
assets/
  icon_16.png               ← icona 16×16 (generata con PIL)
  icon_32.png               ← icona 32×32
  icon_64.png               ← icona 64×64
  icon.ico                  ← bundle multi-size (per PyInstaller)
scripts/
  generate_icon.py           ← NUOVO: genera icona PIL programmaticamente
```

**generate_icon.py:**
```python
# scripts/generate_icon.py
"""Genera l'icona MarketAI programmaticamente con PIL.

Design: cerchio blu scuro con 'M' in bianco e accent line verde.
Non richiede file immagine esterni.

Avvio: poetry run python scripts/generate_icon.py
Output: assets/icon_16.png, assets/icon_32.png, assets/icon_64.png, assets/icon.ico
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path("assets")

def generate_icon(size: int) -> Image.Image:
    """Genera icona quadrata size×size px."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Sfondo cerchio blu scuro (#1a1f3a)
    margin = size // 10
    draw.ellipse([margin, margin, size - margin, size - margin],
                 fill=(26, 31, 58, 255))

    # Accent line verde (#4CAF50) in basso a destra
    accent_r = size // 4
    draw.ellipse([size - accent_r - margin, size - accent_r - margin,
                  size - margin, size - margin],
                 fill=(76, 175, 80, 255))

    # "M" al centro in bianco
    font_size = size // 2
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except OSError:
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), "M", font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    draw.text(((size - text_w) // 2, (size - text_h) // 2),
              "M", fill=(255, 255, 255, 255), font=font)
    return img

def main() -> None:
    ASSETS_DIR.mkdir(exist_ok=True)
    sizes = [16, 32, 64]
    images = []
    for s in sizes:
        img = generate_icon(s)
        img.save(ASSETS_DIR / f"icon_{s}.png")
        images.append(img)
        print(f"✅ assets/icon_{s}.png generata")

    # Bundle .ico multi-size per PyInstaller
    images[0].save(
        ASSETS_DIR / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
    )
    print("✅ assets/icon.ico generata (multi-size)")

if __name__ == "__main__":
    main()
```

**Aggiornamenti launcher_webview.py:**
```python
# Aggiungere alla finestra pywebview:
import webview

# Icona della finestra (Windows)
window = webview.create_window(
    title=WINDOW_TITLE,
    url=STREAMLIT_URL,
    width=WINDOW_WIDTH,
    height=WINDOW_HEIGHT,
    resizable=True,
    # Shortcut tastiera F5 = refresh (utile durante sviluppo)
)

# JavaScript injection: nascondi header Streamlit "Running..." durante caricamento
def inject_ui_tweaks(window):
    """Piccoli aggiustamenti CSS via JS per look più nativo."""
    window.evaluate_js("""
        // Nascondi menu hamburger Streamlit (non necessario in app nativa)
        const style = document.createElement('style');
        style.textContent = `
            #MainMenu { visibility: hidden !important; }
            footer { visibility: hidden !important; }
        `;
        document.head.appendChild(style);
    """)

webview.start(inject_ui_tweaks, window, debug=False)
```

**Definition of Done — Sessione 2:**
```
□ generate_icon.py: genera icon_16/32/64.png e icon.ico senza errori
□ Finestra pywebview: icona visibile nella taskbar Windows
□ Menu hamburger Streamlit nascosto via CSS injection
□ Footer Streamlit nascosto (look più pulito)
□ Shortcut F5: reload pagina funzionante
□ pytest -m regression: 0 failed
```

---

## 📅 SESSIONE 3 — Persistenza Sessioni (SQLite user_sessions.db) (1–2h)

**Obiettivo:** Salvare configurazioni analisi e preferenze utente tra una sessione e l'altra

**NON toccare:** SQLite principale del progetto (posizioni, profili eToro)

**File da creare:**
```
personal/user_preferences/
  __init__.py
  session_model.py         ← AnalysisSession, UserPreference (Pydantic)
  session_repo.py          ← CRUD su db/user_sessions.db (SQLite)
  preferences_loader.py    ← caricamento preferenze all'avvio

shared/db/
  user_sessions_client.py  ← SQLiteClient dedicato (separato dal principale)

tests/personal/user_preferences/
  test_session_repo.py
  test_preferences_loader.py
```

**session_model.py:**
```python
# personal/user_preferences/session_model.py
"""Modelli dati per sessioni utente e preferenze.

Separati dal modello finanziario principale.
Salvati in db/user_sessions.db (NON nel SQLite delle posizioni).
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class AnalysisSession(BaseModel):
    """Configurazione di una sessione di analisi salvata."""
    session_id: str                     # UUID generato automaticamente
    name: Optional[str] = None         # nome personalizzato dall'utente
    symbol: str
    start_date: str
    end_date: str
    model_name: str
    horizon_days: int = 30
    auto_features: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_used_at: Optional[datetime] = None
    notes: Optional[str] = None

class UserPreference(BaseModel):
    """Preferenze UI dell'utente."""
    key: str
    value: str                          # sempre stringa; conversione nel loader

# Preferenze supportate e valori default:
DEFAULT_PREFERENCES = {
    "theme": "dark",                    # "dark" | "light"
    "default_page": "E1",              # pagina di apertura
    "default_symbol": "SPY",
    "default_horizon": "30",
    "language": "it",                   # "it" | "en"
    "auto_refresh_seconds": "900",      # TTL refresh automatico
    "show_data_quality_badge": "true",
}
```

**session_repo.py:**
```python
# personal/user_preferences/session_repo.py
"""Repository CRUD per sessioni analisi su db/user_sessions.db."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
import sqlite3
import structlog

log = structlog.get_logger(__name__)
DB_PATH = Path("db/user_sessions.db")

class SessionRepository:
    """CRUD per AnalysisSession su SQLite dedicato."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._db = db_path
        self._init_schema()

    def _init_schema(self) -> None:
        self._db.parent.mkdir(exist_ok=True)
        with sqlite3.connect(self._db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analysis_sessions (
                    session_id TEXT PRIMARY KEY,
                    name TEXT,
                    symbol TEXT NOT NULL,
                    start_date TEXT,
                    end_date TEXT,
                    model_name TEXT,
                    horizon_days INTEGER DEFAULT 30,
                    auto_features INTEGER DEFAULT 0,
                    created_at TEXT,
                    last_used_at TEXT,
                    notes TEXT,
                    config_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT
                )
            """)

    def save_session(self, session: "AnalysisSession") -> str:
        """Salva o aggiorna una sessione. Ritorna session_id."""
        if not session.session_id:
            session.session_id = str(uuid.uuid4())
        with sqlite3.connect(self._db) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO analysis_sessions
                (session_id, name, symbol, start_date, end_date, model_name,
                 horizon_days, auto_features, created_at, last_used_at, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (session.session_id, session.name, session.symbol,
                  session.start_date, session.end_date, session.model_name,
                  session.horizon_days, int(session.auto_features),
                  session.created_at.isoformat(),
                  datetime.utcnow().isoformat(), session.notes))
        log.info("session_repo.saved", session_id=session.session_id)
        return session.session_id

    def list_recent(self, limit: int = 20) -> list["AnalysisSession"]:
        """Lista le sessioni più recenti."""
        with sqlite3.connect(self._db) as conn:
            rows = conn.execute("""
                SELECT session_id, name, symbol, start_date, end_date,
                       model_name, horizon_days, auto_features, created_at, last_used_at, notes
                FROM analysis_sessions
                ORDER BY last_used_at DESC LIMIT ?
            """, (limit,)).fetchall()
        # ... conversione in AnalysisSession
        return []

    def set_preference(self, key: str, value: str) -> None:
        """Salva una preferenza utente."""
        with sqlite3.connect(self._db) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO user_preferences (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, value, datetime.utcnow().isoformat()))

    def get_preference(self, key: str, default: str = "") -> str:
        """Legge una preferenza utente."""
        with sqlite3.connect(self._db) as conn:
            row = conn.execute(
                "SELECT value FROM user_preferences WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else default
```

**Integrazione in Streamlit (pagina S2_Settings.py):**
```python
# Aggiungere sezione "Sessioni Salvate" in S2_Settings.py

st.subheader("📂 Sessioni Analisi")
repo = SessionRepository()
sessions = repo.list_recent(limit=10)

if sessions:
    selected = st.selectbox("Ricarica sessione precedente:", 
                            options=[f"{s.symbol} — {s.model_name} ({s.created_at:%d/%m/%Y})" 
                                     for s in sessions])
    if st.button("📂 Carica"):
        # Imposta st.session_state con i parametri della sessione
        idx = sessions[st.selectbox.index]
        st.session_state["symbol"] = sessions[idx].symbol
        st.rerun()
```

**Definition of Done — Sessione 3:**
```
□ SessionRepository: save, list_recent, delete funzionanti
□ UserPreference: get/set per tutti i DEFAULT_PREFERENCES
□ db/user_sessions.db: creato automaticamente alla prima apertura
□ S2_Settings.py: sezione "Sessioni Salvate" con ricaricamento
□ Export JSON: configurazione esportabile/importabile
□ test_session_repo.py: CRUD completo, concorrenza SQLite
□ pytest -m regression: 0 failed
□ db/user_sessions.db NON è il SQLite delle posizioni (path diverso verificato)
```

---

## 📅 SESSIONE 4 — Model Drift Detection e Alert (1–2h)

**Obiettivo:** Monitorare degradazione previsioni nel tempo e avvisare l'utente

**NON toccare:** modelli, training pipeline

**File da creare:**
```
engine/analytics/evaluation/
  drift_detector.py          ← DriftDetector con finestra mobile
  metrics_store.py           ← salvataggio metriche su user_sessions.db

presentation/dashboard_engine/pages/
  S2_Settings.py             ← aggiungere sezione "Salute Modelli"
```

**drift_detector.py:**
```python
# engine/analytics/evaluation/drift_detector.py
"""DriftDetector: monitoraggio degradazione performance modelli nel tempo.

Logica:
  1. Dopo ogni previsione (quando il dato reale è disponibile),
     calcola MAE su finestra recente e salva in metrics_store.
  2. Ogni volta che viene aperta S2_Settings, confronta MAE recente
     vs baseline (media mobile delle ultime N settimane).
  3. Se MAE_recente > MAE_baseline * (1 + threshold) → alert GIALLO/ROSSO.

NON interrompe mai l'analisi in corso: solo notifica passiva.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

import numpy as np
import structlog

log = structlog.get_logger(__name__)

AlertLevel = Literal["OK", "WARNING", "CRITICAL"]

@dataclass
class DriftAlert:
    model_name: str
    symbol: str
    alert_level: AlertLevel
    current_mae: float
    baseline_mae: float
    degradation_pct: float
    message: str

class DriftDetector:
    """Rileva degradazione performance rispetto alla baseline storica."""

    def __init__(
        self,
        warning_threshold: float = 0.20,    # +20% MAE → WARNING
        critical_threshold: float = 0.50,   # +50% MAE → CRITICAL
        baseline_window_days: int = 90,     # giorni per calcolare baseline
    ) -> None:
        self._warning_thr = warning_threshold
        self._critical_thr = critical_threshold
        self._window = baseline_window_days

    def check_drift(
        self,
        model_name: str,
        symbol: str,
        current_mae: float,
        historical_maes: list[float],       # MAE storici dalla metrics_store
    ) -> DriftAlert:
        """
        Confronta MAE corrente con baseline storica.
        """
        if len(historical_maes) < 5:
            return DriftAlert(model_name, symbol, "OK", current_mae, 0.0, 0.0,
                              "Dati insufficienti per rilevare drift")

        baseline = float(np.mean(historical_maes[-self._window:]))
        degradation = (current_mae - baseline) / (baseline + 1e-8)

        if degradation >= self._critical_thr:
            level: AlertLevel = "CRITICAL"
            msg = (f"⛔ Performance {model_name} su {symbol} degradata del "
                   f"{degradation:.0%}. Considera ri-addestramento.")
        elif degradation >= self._warning_thr:
            level = "WARNING"
            msg = (f"⚠️ Performance {model_name} su {symbol} in calo del "
                   f"{degradation:.0%} rispetto alla baseline.")
        else:
            level = "OK"
            msg = "✅ Performance nella norma"

        log.info("drift_detector.check", model=model_name, symbol=symbol,
                 level=level, degradation_pct=round(degradation * 100, 1))

        return DriftAlert(model_name, symbol, level, current_mae, baseline, degradation, msg)
```

**S2_Settings.py — sezione "Salute Modelli":**
```python
# Aggiungere a S2_Settings.py (NON modificare altre pagine)

st.subheader("🔬 Salute Modelli")
detector = DriftDetector()
store = MetricsStore()

for model_name in ModelRegistry.list_names():
    recent_mae = store.get_recent_mae(model_name, days=7)
    historical_maes = store.get_historical_maes(model_name, days=90)
    if recent_mae is not None:
        alert = detector.check_drift(model_name, "portfolio", recent_mae, historical_maes)
        if alert.alert_level == "CRITICAL":
            st.error(alert.message)
        elif alert.alert_level == "WARNING":
            st.warning(alert.message)
        else:
            st.success(alert.message)
```

**Definition of Done — Sessione 4:**
```
□ DriftDetector: WARNING a +20% MAE, CRITICAL a +50% (testato con valori noti)
□ MetricsStore: salva e legge MAE da user_sessions.db
□ S2_Settings: sezione "Salute Modelli" con semaforo per modello
□ Alert non bloccante: l'analisi continua normalmente
□ test_drift_detector.py: tutti gli scenari (OK, WARNING, CRITICAL, dati insufficienti)
□ pytest -m regression: 0 failed
```

---

## 📅 SESSIONE 5 — Pagina "Cronologia Analisi" (1–2h)

**Obiettivo:** Aggiungere pagina dedicata allo storico delle analisi salvate

**NON toccare:** pagine esistenti E*, K*, M*, Q*

**File da creare:**
```
presentation/dashboard_engine/pages/
  H1_Cronologia.py           ← NUOVO: storico sessioni con ricaricamento

presentation/ui/components/
  session_card.py            ← NUOVO: componente card sessione
```

**H1_Cronologia.py:**
```python
# presentation/dashboard_engine/pages/H1_Cronologia.py
"""Pagina storico sessioni analisi.

Mostra le sessioni salvate con possibilità di:
- Ricaricare configurazione (porta sulla pagina corretta con i parametri)
- Confrontare risultati di due sessioni
- Esportare/importare sessioni in JSON
- Eliminare sessioni obsolete

Questa pagina NON fa analisi: solo gestione sessioni.
"""
import streamlit as st
import json
from pathlib import Path
from presentation.ui.auth import require_auth
from personal.user_preferences.session_repo import SessionRepository
from presentation.ui.session_keys import SK

require_auth()
st.title("📂 Cronologia Analisi")

repo = SessionRepository()
sessions = repo.list_recent(limit=50)

# Ricerca e filtro
col1, col2 = st.columns([3, 1])
with col1:
    search = st.text_input("🔍 Cerca per simbolo o modello", placeholder="AAPL, xgboost...")
with col2:
    if st.button("🗑️ Pulisci cronologia"):
        if st.session_state.get("confirm_delete"):
            repo.delete_all()
            st.success("Cronologia eliminata")
        st.session_state["confirm_delete"] = True

filtered = [s for s in sessions if
            (not search) or
            search.lower() in s.symbol.lower() or
            search.lower() in s.model_name.lower()]

if not filtered:
    st.info("Nessuna sessione trovata. Le analisi vengono salvate automaticamente.")
else:
    for session in filtered:
        with st.expander(f"**{session.symbol}** — {session.model_name} — {session.created_at:%d/%m/%Y %H:%M}"):
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("Simbolo", session.symbol)
            with col_b:
                st.metric("Modello", session.model_name)
            with col_c:
                st.metric("Orizzonte", f"{session.horizon_days}gg")

            if st.button(f"📂 Ricarica questa analisi", key=f"load_{session.session_id}"):
                st.session_state[SK.SELECTED_SYMBOL] = session.symbol
                st.session_state[SK.SELECTED_MODEL] = session.model_name
                st.session_state[SK.HORIZON_DAYS] = session.horizon_days
                repo.mark_used(session.session_id)
                st.switch_page("pages/Q1_Backtesting.py")

# Export JSON
st.divider()
st.subheader("📤 Esporta / Importa")
col_exp, col_imp = st.columns(2)
with col_exp:
    if st.button("📥 Esporta tutte (JSON)"):
        data = [s.model_dump() for s in sessions]
        st.download_button(
            "💾 Scarica sessions.json",
            data=json.dumps(data, default=str, indent=2),
            file_name="marketai_sessions.json",
            mime="application/json",
        )
with col_imp:
    uploaded = st.file_uploader("📤 Importa da JSON", type="json")
    if uploaded:
        data = json.load(uploaded)
        imported = 0
        for item in data:
            try:
                from personal.user_preferences.session_model import AnalysisSession
                session = AnalysisSession(**item)
                repo.save_session(session)
                imported += 1
            except Exception:
                pass
        st.success(f"✅ {imported} sessioni importate")
```

**Definition of Done — Sessione 5:**
```
□ H1_Cronologia.py: lista sessioni con filtro e ricaricamento
□ Ricaricamento: porta su Q1_Backtesting con parametri pre-impostati
□ Export JSON: file scaricabile correttamente
□ Import JSON: sessioni importate salvate nel repo
□ Eliminazione: con conferma esplicita
□ Pagina carica senza eccezioni con sessioni di fixture
□ pytest -m regression: 0 failed
```

---

## 📅 SESSIONE 6 — Build MarketAI.exe con pywebview (1–2h)

**Obiettivo:** Creare eseguibile standalone che include pywebview (niente Python visibile all'utente)

**NON toccare:** Streamlit dashboard, management_ui.py

**File da creare/modificare:**
```
scripts/
  build_webview.py           ← NUOVO: build PyInstaller per launcher_webview
  build_full.py              ← NUOVO: build completa (Manager + WebView)
  webview.spec               ← NUOVO: spec file PyInstaller per launcher_webview
```

**webview.spec:**
```python
# webview.spec — PyInstaller spec per launcher_webview.py
# Generato con: pyinstaller launcher_webview.py --name MarketAI --windowed --onefile
# Poi modificato manualmente per aggiungere hidden imports pywebview

a = Analysis(
    ["launcher_webview.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("assets/icon.ico", "assets"),
        ("assets/icon_64.png", "assets"),
    ],
    hiddenimports=[
        "webview",
        "webview.platforms.winforms",   # Windows edge WebView2
        "clr",                          # pythonnet per WebView2
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "wx"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="MarketAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                 # nessuna finestra cmd
    icon="assets/icon.ico",
)
```

**build_webview.py:**
```python
# scripts/build_webview.py
"""Build script per MarketAI.exe (launcher pywebview).

Prerequisiti:
    poetry add pyinstaller --group dev
    Oppure: pip install pyinstaller --break-system-packages

Note:
    L'exe NON include Streamlit (troppo grande, ~500MB aggiuntivi).
    Streamlit viene avviato dall'exe come subprocess (dal venv Poetry).
    Il venv Poetry deve esistere nella cartella del progetto.

Build:
    poetry run python scripts/build_webview.py

Output:
    dist/MarketAI.exe    → copiare in %APPDATA%\MarketAI\
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

def build() -> None:
    print("🔨 Building MarketAI.exe con pywebview...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "MarketAI",
        "--windowed",        # nessuna finestra cmd
        "--onefile",         # singolo exe
        "--icon", "assets/icon.ico",
        "--hidden-import", "webview",
        "--hidden-import", "webview.platforms.winforms",
        "--add-data", "assets;assets",
        "--exclude-module", "tkinter",
        "--noconfirm",
        "launcher_webview.py",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Build fallita:\n{result.stderr}")
        sys.exit(1)
    print(f"✅ Build completata: dist/MarketAI.exe")
    size_mb = Path("dist/MarketAI.exe").stat().st_size / 1_048_576
    print(f"   Dimensione: {size_mb:.1f} MB")

if __name__ == "__main__":
    build()
```

**Definition of Done — Sessione 6:**
```
□ MarketAI.exe: avvio senza Python installato (test su macchina pulita/VM)
□ MarketAI.exe: dimensione < 80MB (pywebview alone è leggero)
□ Avvio exe: Streamlit si avvia automaticamente (dal venv Poetry locale)
□ Chiusura finestra: processi terminati correttamente (no zombie)
□ Fallback browser: se pywebview non inizializza, apre Chrome/Edge
□ WebView2 Runtime: prerequisito documentato in CONTRIBUTING.md
□ pytest -m regression: 0 failed
```

---

## 📅 SESSIONE 7 — Validazione Completa e CLAUDE.md v3 (1–2h)

**Obiettivo:** Validazione end-to-end su hardware reale, aggiornare CLAUDE.md, chiudere v15

**Attività:**

```
1. Test hardware reale Ryzen 5 5600:
   · MarketAI.exe → apre finestra nativa < 10 secondi
   · Navigazione tra pagine E1, E6, K1, Q1, H1 senza crash
   · Sessione salvata automaticamente → H1_Cronologia la mostra
   · Drift detector: sezione S2 con semafori visibili

2. CLAUDE.md v3 — aggiornamenti:
   · Nuova sezione: "UI Nativa — pywebview"
     - Sequenza avvio corretta
     - File launcher_webview.py
     - Gestione processi e cleanup
   · Nuova sezione: "Persistenza Sessioni"
     - db/user_sessions.db (schema)
     - SessionRepository CRUD
   · Nuova sezione: "Model Drift Detection"
     - DriftDetector (soglie warning/critical)
     - MetricsStore (come salvare metriche)
   · Pagina aggiunta: H1_Cronologia

3. Aggiornare Management UI (management_ui.py):
   · Pulsante [🚀 Avvia Dashboard] → lancia MarketAI.exe (non Streamlit diretto)
   · Status bar: "🟢 MarketAI aperto" quando la finestra è visibile

4. Aggiornare installer_v2.py:
   · Step aggiuntivo: verifica WebView2 Runtime installato
   · Se mancante → link download automatico (o winget install)

5. Documentazione finale:
   · README.md: sezione "Avvio Rapido" aggiornata
   · docs/architecture.md: diagramma aggiornato con pywebview shell
```

**Checklist validazione hardware finale:**
```
PYWEBVIEW:
□ MarketAI.exe: avvio < 10s (dalla chiusura del Management UI click Avvia)
□ Finestra nativa: barra titolo "MarketAI Professional"
□ Pagina E1 Market Overview: KPI visibili senza errori
□ Pagina Q1 Backtesting: fan chart e diagnostica residui visibili
□ Pagina H1 Cronologia: sessioni salvate e ricaricabili
□ Chiusura finestra: porta 8501 libera dopo 5 secondi (verificato con netstat)

PERSISTENZA:
□ Analisi su AAPL salvata → H1_Cronologia la mostra con data corretta
□ Preferenza "default_symbol" salvata → persistente dopo riavvio
□ Export JSON: file valido e reimportabile

DRIFT DETECTION:
□ S2_Settings: sezione "Salute Modelli" con almeno un modello monitorato
□ Simulazione drift: MAE artificialmente alto → alert WARNING visibile

NESSUNA REGRESSIONE:
□ poetry run pytest -m regression: 0 failed
□ E1, E6, K1, M3, Q1, P2: funzionanti con dati reali
□ mypy --strict su launcher_webview.py e personal/user_preferences/: 0 errors
```

**Definition of Done — Sessione 7 (= Definition of Done Fase 4 = Definition of Done Progetto v15):**
```
□ MarketAI.exe: finestra nativa funzionante su Windows 11
□ Fallback browser: attivato automaticamente se WebView2 mancante
□ H1_Cronologia: storico sessioni con export/import JSON
□ DriftDetector: alert visibili in S2_Settings
□ management_ui.py: [🚀 Avvia] → apre finestra nativa
□ installer_v2.py: verifica WebView2 Runtime
□ CLAUDE.md v3: aggiornato con tutte le novità v15
□ pytest --cov --cov-fail-under=89: verde
□ pytest -m regression: 0 failed
□ mypy --strict: 0 errors su tutti i nuovi file
□ Documentazione MkDocs: aggiornata con H1_Cronologia e pywebview
```

---

## 📁 Struttura File Finale v15.0.0

```
%APPDATA%\MarketAI\
├── launcher_webview.py              ★ NUOVO (entry point UI nativa)
├── webview_bridge.py                ★ NUOVO
├── MarketAI.exe                     ★ NUOVO (build PyInstaller)
├── assets/
│   ├── icon_16.png                  ★ NUOVO
│   ├── icon_32.png                  ★ NUOVO
│   ├── icon_64.png                  ★ NUOVO
│   └── icon.ico                     ★ NUOVO
├── personal/
│   └── user_preferences/            ★ NUOVO
│       ├── session_model.py
│       ├── session_repo.py
│       └── preferences_loader.py
├── engine/analytics/evaluation/
│   ├── drift_detector.py            ★ NUOVO
│   └── metrics_store.py             ★ NUOVO
├── presentation/dashboard_engine/pages/
│   ├── H1_Cronologia.py             ★ NUOVO
│   └── S2_Settings.py               ★ MODIFICATO (sezione Salute Modelli)
├── db/
│   └── user_sessions.db             ★ NUOVO (generato a runtime)
├── scripts/
│   ├── build_webview.py             ★ NUOVO
│   ├── build_full.py                ★ NUOVO
│   ├── generate_icon.py             ★ NUOVO
│   └── webview.spec                 ★ NUOVO
├── management_ui.py                  ★ MODIFICATO (avvia launcher_webview)
└── CLAUDE.md                         ★ v3 — aggiornato
```

---

## 📊 Metriche di Successo v15.0.0

| Metrica | Target | Note hardware |
|---------|--------|---------------|
| Avvio MarketAI.exe → finestra nativa | < 10s | Ryzen 5 5600 |
| Streamlit startup interno | < 30s | (già validato v11) |
| H1_Cronologia caricamento | < 1s | SQLite locale |
| DriftDetector check | < 100ms | — |
| Export 50 sessioni JSON | < 500ms | — |
| MarketAI.exe dimensione | < 80MB | pywebview solo |
| pytest regression | 0 failed | SEMPRE |
| mypy --strict nuovi file | 0 errors | — |
| Coverage personal/user_preferences/ | 100% | — |
| Coverage evaluation/ (drift) | ≥ 90% | — |

---

## 🗺️ Riepilogo Timeline Completa v12→v15

```
v12.0.0 (Fase 1) — ~3 settimane
  · Data Provider Plugin System (yfinance, AV, Finnhub)
  · Logging JSON strutturato
  · CI/CD GitHub Actions
  · MkDocs documentazione

v13.0.0 (Fase 2) — ~4 settimane
  · EnsemblePredictor (3 strategie)
  · XGBoost Quantile Regression
  · FeatureBuilder automatizzato
  · Fan chart in Q1_Backtesting

v14.0.0 (Fase 3) — ~5 settimane
  · N-BEATS (PyTorch CPU, 16GB RAM safe)
  · RealisticBacktester con commissioni/slippage
  · Metriche avanzate (SMAPE, Theil's U, CRPS)
  · FastAPI backend (/predict /backtest /health)
  · Diagnostica residui (ACF, ARCH, Jarque-Bera)

v15.0.0 (Fase 4) — ~5 settimane  ← QUESTA ROADMAP
  · UI nativa Windows (pywebview, zero browser)
  · Persistenza sessioni (SQLite dedicato)
  · Model drift detection e alert
  · Cronologia analisi (H1_Cronologia)
  · Build MarketAI.exe standalone

TOTALE: ~17 settimane (~4 mesi) post v11.0.0
```

---

*MarketAI v15.0.0 · Roadmap Fase 4 — UI Nativa e Produzione*  
*Pianificazione: Claude Sonnet 4.6 · Implementazione: Claude Code Pro (Opus 4.8)*  
*Hardware: Ryzen 5 5600 · RX 6700 8GB · 16GB RAM · Windows 11*  
*Obiettivo: app nativa professionale, zero configurazione manuale per l'utente finale*
