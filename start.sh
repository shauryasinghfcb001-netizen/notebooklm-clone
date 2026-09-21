#!/bin/bash
# NotebookLM Clone - starter (uses .venv when install-linux.sh created one)
set -e
cd "$(dirname "$0")/backend"
if [ -x "../.venv/bin/python" ]; then PY="../.venv/bin/python"; else PY="python"; pip install -q -r requirements.txt; fi
STORAGE_DIR=../data LLM_PROVIDER=${LLM_PROVIDER:-mock} TTS_PROVIDER=${TTS_PROVIDER:-edge} \
  "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
