# 01 — Ambiente, Installer e Percorsi

## Configurazione Python (CRITICO)

| Variabile | Valore |
|---|---|
| Python venv (da usare) | **3.12.10** |
| Python sistema (mai usare) | 3.14.5 |
| Path Python 3.12 | `C:\Users\Q256254\AppData\Local\Programs\Python\Python312\python.exe` |
| Posizione venv | `<project_root>\.venv\` |
| Poetry | v2.4.1 |

**Problema:** Python 3.14.5 è il default di sistema. Molte dipendenze del progetto
(numpy, scipy, vectorbt, pandera) non sono compatibili con 3.14.x.

**Fix immediato se Poetry usa versione sbagliata:**
```bash
poetry env use "C:\Users\Q256254\AppData\Local\Programs\Python\Python312\python.exe"
poetry env info   # verificare Python: 3.12.10
```

## Percorsi di Progetto

```
Sorgente attuale:   Desktop/PERSONALE/MarketAI/market-ai/MarketAI 1.0/   (path con spazio!)
Target installato:  %APPDATA%\MarketAI\  =  C:\Users\Q256254\AppData\Roaming\MarketAI\
Backup:             %LOCALAPPDATA%\MarketAI\backups\
Config UI:          %LOCALAPPDATA%\MarketAI\ui_config.json
GitHub:             https://github.com/tommasocuspolici-del/MarketAI (PAT auth)
```

## Installer v3 (scripts/install_v3.py)

Script Python con GUI tkinter che:
1. Verifica prerequisiti (Python 3.12, Git, Poetry)
2. Copia progetto → `%APPDATA%\MarketAI\` (esclude .venv, cache, *.pyc)
3. Ricrea venv con Python 3.12.10 esplicito (`poetry env use ...`)
4. `poetry install --no-interaction`
5. Copia `.env` (già configurato con API keys)
6. Inizializza DB (`scripts/init_database.py`)
7. Crea shortcut Desktop (`MarketAI_start.bat`)
8. Esegue smoke test (`pytest -m regression -q`)

**Avvio installer:**
```bash
python scripts/install_v3.py          # GUI interattiva
python scripts/install_v3.py --cli    # Solo terminale
```

**NON sovrascrivere** `scripts/install.py` (v1, backward compat). Il nuovo file è `install_v3.py`.

## Variabili d'Ambiente (.env)

```bash
# Data providers
FINNHUB_API_KEY=...
ALPHA_VANTAGE_KEY=...
FRED_API_KEY=...

# Auth dashboard (disabilitare in dev locale)
STREAMLIT_AUTH_ENABLED=false
STREAMLIT_AUTH_PASSWORD_HASH=...   # sha256 della password

# DB paths (default: db/ nella cartella progetto)
DUCKDB_PATH=db/market_data.duckdb
SQLITE_PATH=db/market_ai.db

# Backup
BACKUP_DIR=%LOCALAPPDATA%\MarketAI\backups
BACKUP_RETAIN_COUNT=10

# API key MarketAI (per FastAPI)
MARKETAI_API_KEY=...
```

## Management UI (management_ui.py)

- **REGOLA ASSOLUTA:** management_ui.py NON importa NULLA da engine/personal/shared/bridge
- Import permessi: `tkinter`, `subprocess`, `pathlib`, `zipfile`, `datetime`, `threading`, `shutil`, `os`, `pystray`, `PIL`
- Subprocess sempre con `CREATE_NO_WINDOW = 0x08000000`
- Config letta da `%LOCALAPPDATA%\MarketAI\ui_config.json` (non da config/ del progetto)

## Workflow Setup da Zero (5 minuti)

```bash
# 1. Clone
git clone https://github.com/tommasocuspolici-del/MarketAI
cd MarketAI

# 2. Installa con installer GUI
python scripts/install_v3.py

# --- oppure manuale: ---
# 2. Configura ambiente
poetry env use "C:\...\Python312\python.exe"
poetry install

# 3. Configura .env
cp .env.example .env
# Aggiungere API keys in .env

# 4. Init DB
poetry run python scripts/init_database.py

# 5. Avvio
poetry run streamlit run app_unified.py   # → http://localhost:8501
```

## Hardware di Riferimento

```
CPU:  Ryzen 5 5600 (6 core / 12 thread)
GPU:  RX 6700 8GB VRAM — ROCm su Windows NON stabile → CPU only per PyTorch
RAM:  16GB DDR4 3200MHz
SSD:  512GB NVMe
OS:   Windows 11
```

**Vincolo GPU:** Mai usare GPU per training PyTorch. Usare sempre `tree_method="hist"` per XGBoost (CPU). N-BEATS: `torch.set_num_threads(4)`, `device=torch.device("cpu")`.
