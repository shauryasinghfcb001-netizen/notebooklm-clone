#!/bin/bash
# NotebookLM Clone - Linux installer: venv + deps + app-menu entry.
# Usage: ./scripts/install-linux.sh [--dense]
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
command -v python3 >/dev/null || { echo "Install python3 first (e.g. sudo apt install python3 python3-venv)"; exit 1; }
if [ ! -x "$ROOT/.venv/bin/python" ]; then python3 -m venv "$ROOT/.venv"; fi
"$ROOT/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
if [ "$1" = "--dense" ]; then
  "$ROOT/.venv/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cpu
  "$ROOT/.venv/bin/pip" install -q sentence-transformers
fi
mkdir -p "$ROOT/data" "$HOME/.local/share/applications"
sed "s|XXX|$ROOT|g" "$ROOT/scripts/notebooklm-clone.desktop" > "$HOME/.local/share/applications/notebooklm-clone.desktop"
echo "Done. Launch 'NotebookLM Clone' from your app menu, or run: $ROOT/start.sh"
echo "Optional auto-start: cp $ROOT/scripts/notebooklm-clone.service ~/.config/systemd/user/ && systemctl --user enable --now notebooklm-clone"
