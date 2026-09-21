@echo off
REM NotebookLM Clone - double-click starter for Windows.
cd /d "%~dp0\.."
where python >nul 2>nul
if errorlevel 1 (
  echo [NotebookLM Clone] Install Python 3.11+ from https://www.python.org/downloads/
  echo Tick "Add python.exe to PATH" during setup, then double-click again.
  pause
  exit /b 1
)
if not exist data mkdir data
python -m pip install -q -r backend\requirements.txt
if "%LLM_PROVIDER%"=="" set LLM_PROVIDER=mock
if "%TTS_PROVIDER%"=="" set TTS_PROVIDER=edge
if "%PORT%"=="" set PORT=8000
start "" http://localhost:%PORT%/
cd backend
set STORAGE_DIR=..\data
python -m uvicorn app.main:app --host 0.0.0.0 --port %PORT%
pause
