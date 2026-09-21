@echo off
REM Build the Windows .exe (run ON Windows, needs Python 3.11+).
cd /d "%~dp0\.."
python -m pip install -q pyinstaller
python -m pip install -q -r backend\requirements.txt
pyinstaller notebooklm.spec
echo.
echo Done: dist\NotebookLM-Clone\NotebookLM-Clone.exe
pause
