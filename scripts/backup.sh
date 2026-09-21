#!/bin/bash
# Backup data dir (sqlite + uploads + artifacts) to a timestamped tarball.
set -e
cd "$(dirname "$0")/.."
STAMP=$(date +%Y%m%d-%H%M%S)
FILES="data"; [ -f .env ] && FILES="data .env"
tar -czf "backup-$STAMP.tar.gz" --exclude='data/*.db-shm' --exclude='data/*.db-wal' $FILES
echo "wrote backup-$STAMP.tar.gz"
