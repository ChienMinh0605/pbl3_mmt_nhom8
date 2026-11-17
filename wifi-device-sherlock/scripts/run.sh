#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON_BIN="$ROOT/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" || ! -f "$ROOT/frontend/dist/index.html" ]]; then
  echo 'Chuẩn bị môi trường Python và giao diện cho lần chạy đầu...'
  bash "$ROOT/scripts/setup.sh"
fi
echo "Mở http://127.0.0.1:${WIFI_PORT:-8000} — Ctrl+C để dừng"
exec "$PYTHON_BIN" -m uvicorn backend.app.main:app --host 127.0.0.1 --port "${WIFI_PORT:-8000}"
