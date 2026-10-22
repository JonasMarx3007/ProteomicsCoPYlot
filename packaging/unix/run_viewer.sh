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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
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

for arg in "$@"; do
  case "$arg" in
    --model|--model=*)
      exec "$SCRIPT_DIR/run_viewer_ai.sh" "$@"
      ;;
  esac
done

VIEWER_PROJECT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      shift
      VIEWER_PROJECT="${1:-}"
      if [[ -z "$VIEWER_PROJECT" ]]; then
        echo "Error: --project requires a project name."
        exit 1
      fi
      ;;
    --project=*)
      VIEWER_PROJECT="${1#--project=}"
      ;;
    --*)
      if [[ -z "$VIEWER_PROJECT" ]]; then
        VIEWER_PROJECT="${1#--}"
      fi
      ;;
    *)
      if [[ -z "$VIEWER_PROJECT" ]]; then
        VIEWER_PROJECT="$1"
      fi
      ;;
  esac
  shift || true
done

if [[ -f "$ROOT_DIR/local/viewer_config.local.json" ]]; then
  VIEWER_CONFIG="$ROOT_DIR/local/viewer_config.local.json"
elif [[ -f "$ROOT_DIR/viewer_config.local.json" ]]; then
  VIEWER_CONFIG="$ROOT_DIR/viewer_config.local.json"
else
  VIEWER_CONFIG="$ROOT_DIR/viewer_config.json"
fi
if [[ -n "$VIEWER_PROJECT" ]]; then
  if [[ -f "$ROOT_DIR/viewer_data/local/$VIEWER_PROJECT/viewer_config.local.json" ]]; then
    VIEWER_CONFIG="$ROOT_DIR/viewer_data/local/$VIEWER_PROJECT/viewer_config.local.json"
  elif [[ -f "$ROOT_DIR/viewer_data/local/$VIEWER_PROJECT/viewer_config.json" ]]; then
    VIEWER_CONFIG="$ROOT_DIR/viewer_data/local/$VIEWER_PROJECT/viewer_config.json"
  elif [[ -f "$ROOT_DIR/viewer_data/$VIEWER_PROJECT/viewer_config.local.json" ]]; then
    VIEWER_CONFIG="$ROOT_DIR/viewer_data/$VIEWER_PROJECT/viewer_config.local.json"
  elif [[ -f "$ROOT_DIR/viewer_data/$VIEWER_PROJECT/viewer_config.json" ]]; then
    VIEWER_CONFIG="$ROOT_DIR/viewer_data/$VIEWER_PROJECT/viewer_config.json"
  elif [[ -f "$ROOT_DIR/viewer_data/projects/$VIEWER_PROJECT/viewer_config.local.json" ]]; then
    VIEWER_CONFIG="$ROOT_DIR/viewer_data/projects/$VIEWER_PROJECT/viewer_config.local.json"
  elif [[ -f "$ROOT_DIR/viewer_data/projects/$VIEWER_PROJECT/viewer_config.json" ]]; then
    VIEWER_CONFIG="$ROOT_DIR/viewer_data/projects/$VIEWER_PROJECT/viewer_config.json"
  else
    echo "Viewer project '$VIEWER_PROJECT' not found or missing viewer_config.json."
    echo "Expected one of:"
    echo "  $ROOT_DIR/viewer_data/local/$VIEWER_PROJECT/viewer_config.json"
    echo "  $ROOT_DIR/viewer_data/$VIEWER_PROJECT/viewer_config.json"
    echo "  $ROOT_DIR/viewer_data/projects/$VIEWER_PROJECT/viewer_config.json"
    exit 1
  fi
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
  COPYLOT_VIEWER_MODE=1 COPYLOT_VIEWER_PORTAL_ENABLED=0 COPYLOT_SESSION_ISOLATION=1 COPYLOT_RESET_ON_BROWSER_LOAD=0 COPYLOT_VIEWER_PROJECT="$VIEWER_PROJECT" COPYLOT_VIEWER_CONFIG="$VIEWER_CONFIG" \
    "$PYTHON_BIN" -m uvicorn app.main:app --workers 1 --host 127.0.0.1 --port 8001
) &
BACKEND_PID=$!

(
  cd "$FRONTEND_DIR"
  VITE_APP_MODE=viewer VITE_RESET_ON_BROWSER_LOAD=0 VITE_PROXY_TARGET="http://127.0.0.1:8001" \
    npm run dev -- --port 5174
) &
FRONTEND_PID=$!

sleep 3
open_browser "http://localhost:5174"

if [[ -n "$VIEWER_PROJECT" ]]; then
  echo "Viewer app started (project: $VIEWER_PROJECT)."
else
  echo "Viewer app started."
fi
echo "Backend: http://127.0.0.1:8001"
echo "Frontend: http://localhost:5174"

wait "$BACKEND_PID" "$FRONTEND_PID"
