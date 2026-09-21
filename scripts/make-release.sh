#!/bin/bash
# Build per-OS release archives (source + launcher each). Run from repo root.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VER="${1:-1.0.0}"
OUT="$ROOT/release-$VER"
rm -rf "$OUT" && mkdir -p "$OUT"
FILES="backend scripts start.sh notebooklm.spec README.md docs pyproject.toml Dockerfile docker-compose.yml .env.example DEMO_SCRIPT.md"
cd "$ROOT"
tar --exclude='backend/__pycache__' --exclude='backend/app/__pycache__' -czf "$OUT/notebooklm-linux-$VER.tar.gz" $FILES
tar --exclude='backend/__pycache__' --exclude='backend/app/__pycache__' -czf "$OUT/notebooklm-macos-$VER.tar.gz" $FILES
rm -f "$OUT/notebooklm-windows-$VER.zip"
zip -qr "$OUT/notebooklm-windows-$VER.zip" $FILES -x 'backend/__pycache__/*' 'backend/app/__pycache__/*'
ls -la "$OUT"
echo "iOS/Android: no download needed - install the PWA from Safari/Chrome (see docs/INSTALL.md)."
