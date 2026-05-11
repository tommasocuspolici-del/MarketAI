# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec per MarketAI launcher.

Build:
  poetry add --group dev pyinstaller
  poetry run pyinstaller MarketAI.spec --clean --noconfirm

Output: dist/MarketAI.exe (singolo eseguibile, senza console, con icona)

NOTA: questo .exe è un "launcher" minimalista. Non incorpora Streamlit
né l'intera applicazione: si limita a invocare `poetry run streamlit run`
nella directory in cui risiede. Vantaggi:
  · Build veloce (<30 secondi)
  · Eseguibile leggero (~10 MB)
  · Aggiornamenti del progetto immediati (basta `poetry install`,
    nessun rebuild dell'exe)
  · Compatibile con il venv Poetry esistente
"""
from pathlib import Path

block_cipher = None

a = Analysis(
    ["launcher.py"],
    pathex=[str(Path.cwd())],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Esclusioni per ridurre dimensione: non servono al launcher
        "streamlit",
        "pandas",
        "numpy",
        "matplotlib",
        "scipy",
        "duckdb",
        "plotly",
        "torch",
        "sklearn",
        "tkinter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MarketAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,        # ★ Nessuna console (--windowed)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",      # ★ Icona personalizzata
    version_file=None,
    contents_directory=".",
)
