#!/bin/bash
# NotebookLM Clone - double-click starter for macOS (Finder runs .command files).
cd "$(dirname "$0")/.." || exit 1
command -v python3 >/dev/null 2>&1 || {
  osascript -e 'display alert "NotebookLM Clone" message "Install Python 3.11+ first: https://www.python.org/downloads/ or: brew install python"'
  exit 1
}
mkdir -p data
python3 -m pip install -q -r backend/requirements.txt
export PORT="${PORT:-8000}"
open "http://localhost:${PORT}/" 2>/dev/null || true
cd backend || exit 1
STORAGE_DIR=../data LLM_PROVIDER="${LLM_PROVIDER:-mock}" TTS_PROVIDER="${TTS_PROVIDER:-edge}" \
  python3 -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
