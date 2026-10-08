#!/usr/bin/env bash
set -euo pipefail

# macOS opens URLs with `open`, Linux desktops with `xdg-open` (on some Linux
# systems `open` is a different program). Without either, open the URL yourself.
open_browser() {
  if [ "$(uname -s)" = "Darwin" ]; then
    open "$1" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$1" >/dev/null 2>&1 || true
  fi
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PYTHON_BIN="$BACKEND_DIR/.venv/bin/python3"

if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
fi

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Backend virtualenv Python not found at $BACKEND_DIR/.venv/bin"
  exit 1
fi

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  if [ -n "${FRONTEND_PID:-}" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
  if [ -n "${BACKEND_PID:-}" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

(
  cd "$BACKEND_DIR"
  COPYLOT_AI_MODE=0 "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
) &
BACKEND_PID=$!

(
  cd "$FRONTEND_DIR"
  VITE_AI_ENABLED=0 VITE_PROXY_TARGET="http://127.0.0.1:8000" npm run dev -- --port 5173
) &
FRONTEND_PID=$!

sleep 3
open_browser "http://localhost:5173"

echo "Analysis app started."
echo "Backend: http://127.0.0.1:8000"
echo "Frontend: http://localhost:5173"

wait "$BACKEND_PID" "$FRONTEND_PID"
