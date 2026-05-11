@echo off
REM ============================================================
REM  MarketAI · Build dell'eseguibile MarketAI.exe
REM ============================================================
REM  Eseguire UNA SOLA VOLTA dalla root del progetto.
REM
REM  PyInstaller e' uno STRUMENTO DI BUILD, non una dipendenza
REM  del progetto: lo installiamo nel venv di Poetry con `pip`
REM  per evitare conflitti col range Python di pyproject.toml
REM  (PyInstaller dichiara python <3.15, il progetto <4.0).
REM
REM  Output finale: MarketAI.exe nella root del progetto.
REM ============================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo [1/4] Verifico/installo PyInstaller nel venv Poetry...
call poetry run pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo     PyInstaller non presente, installazione in corso...
    call poetry run pip install pyinstaller
    if errorlevel 1 (
        echo ERRORE: impossibile installare PyInstaller con pip.
        pause
        exit /b 1
    )
) else (
    echo     PyInstaller gia' presente, skip.
)

echo.
echo [2/4] Pulizia build precedente...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo.
echo [3/4] Build dell'eseguibile (PyInstaller)...
call poetry run pyinstaller MarketAI.spec --clean --noconfirm
if errorlevel 1 (
    echo ERRORE: build PyInstaller fallito.
    pause
    exit /b 1
)

echo.
echo [4/4] Copia MarketAI.exe nella root del progetto...
copy /y "dist\MarketAI.exe" "MarketAI.exe"
if errorlevel 1 (
    echo ERRORE: copia fallita.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  BUILD COMPLETATO
echo ============================================================
echo  File creato: %CD%\MarketAI.exe
echo.
echo  Doppio-click su MarketAI.exe per avviare il dashboard.
echo  Per un collegamento sul desktop: tasto destro -^> Invia a
echo  -^> Desktop (crea collegamento).
echo ============================================================
echo.
pause
