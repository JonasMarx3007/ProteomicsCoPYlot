#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

CHAT_MODEL=""
DEV_MODE=0
DEV_OLLAMA_ENDPOINT=""
VIEWER_PROJECT=""

viewer_project_exists() {
  local project="$1"
  [[ -f "$ROOT_DIR/viewer_data/$project/viewer_config.local.json" ]] || \
  [[ -f "$ROOT_DIR/viewer_data/$project/viewer_config.json" ]] || \
  [[ -f "$ROOT_DIR/viewer_data/projects/$project/viewer_config.local.json" ]] || \
  [[ -f "$ROOT_DIR/viewer_data/projects/$project/viewer_config.json" ]]
}

while [[ $# -gt 0 ]]; do
  arg="$1"
  if [[ "$arg" == "--dev" ]]; then
    DEV_MODE=1
    shift
    continue
  fi
  if [[ "$arg" == "--project" ]]; then
    shift
    VIEWER_PROJECT="${1:-}"
    if [[ -z "$VIEWER_PROJECT" ]]; then
      echo "Error: --project requires a project name."
      exit 1
    fi
    shift
    continue
  fi
  if [[ "$arg" == --project=* ]]; then
    VIEWER_PROJECT="${arg#--project=}"
    shift
    continue
  fi
  if [[ "$arg" == "--model" ]]; then
    shift
    CHAT_MODEL="${1:-}"
    if [[ -z "$CHAT_MODEL" ]]; then
      echo "Error: --model requires a model name."
      exit 1
    fi
    shift
    continue
  fi
  if [[ "$arg" == --model=* ]]; then
    CHAT_MODEL="${arg#--model=}"
    shift
    continue
  fi
  if [[ "$arg" == --* ]]; then
    candidate="${arg#--}"
    if [[ -z "$VIEWER_PROJECT" ]] && viewer_project_exists "$candidate"; then
      VIEWER_PROJECT="$candidate"
      shift
      continue
    fi
  fi
  if [[ -z "$CHAT_MODEL" ]]; then
    if [[ "$arg" == --* ]]; then
      CHAT_MODEL="${arg#--}"
    else
      CHAT_MODEL="$arg"
    fi
  fi
  shift
done

if [[ -f "$ROOT_DIR/viewer_config.local.json" ]]; then
  VIEWER_CONFIG="$ROOT_DIR/viewer_config.local.json"
else
  VIEWER_CONFIG="$ROOT_DIR/viewer_config.json"
fi
if [[ -n "$VIEWER_PROJECT" ]]; then
  if [[ -f "$ROOT_DIR/viewer_data/$VIEWER_PROJECT/viewer_config.local.json" ]]; then
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
    echo "  $ROOT_DIR/viewer_data/$VIEWER_PROJECT/viewer_config.json"
    echo "  $ROOT_DIR/viewer_data/projects/$VIEWER_PROJECT/viewer_config.json"
    exit 1
  fi
fi

if [[ "$DEV_MODE" -eq 1 ]]; then
  DEV_CONFIG="$ROOT_DIR/dev_ai.local.env"
  if [[ -f "$DEV_CONFIG" ]]; then
    while IFS='=' read -r key value || [[ -n "${key:-}" ]]; do
      key="$(echo "${key:-}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
      value="$(echo "${value:-}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
      if [[ -z "$key" || "$key" == \#* ]]; then
        continue
      fi
      if [[ "$key" == "COPYLOT_DEV_OLLAMA_ENDPOINT" ]]; then
        DEV_OLLAMA_ENDPOINT="$value"
      fi
    done < "$DEV_CONFIG"
  else
    echo "Warning: --dev requested but dev config file not found: $DEV_CONFIG"
  fi
fi

if [ -n "$CHAT_MODEL" ]; then
  if ! command -v ollama >/dev/null 2>&1; then
    echo "Warning: ollama executable not found in PATH. Skipping model pull for '$CHAT_MODEL'."
  else
    echo "Pulling Ollama model '$CHAT_MODEL'..."
    if ! ollama pull "$CHAT_MODEL"; then
      echo "Warning: failed to pull model '$CHAT_MODEL'. Continuing startup."
    fi
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
  if [ -n "$CHAT_MODEL" ]; then
    COPYLOT_VIEWER_MODE=1 COPYLOT_VIEWER_PORTAL_ENABLED=0 COPYLOT_VIEWER_INCLUDE_EMPTY_PACKAGES=0 COPYLOT_SESSION_ISOLATION=0 COPYLOT_RESET_ON_BROWSER_LOAD=0 COPYLOT_VIEWER_PROJECT="$VIEWER_PROJECT" COPYLOT_VIEWER_CONFIG="$VIEWER_CONFIG" COPYLOT_AI_MODE=1 COPYLOT_OLLAMA_MODEL="$CHAT_MODEL" \
      "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8001
  else
    COPYLOT_VIEWER_MODE=1 COPYLOT_VIEWER_PORTAL_ENABLED=0 COPYLOT_VIEWER_INCLUDE_EMPTY_PACKAGES=0 COPYLOT_SESSION_ISOLATION=0 COPYLOT_RESET_ON_BROWSER_LOAD=0 COPYLOT_VIEWER_PROJECT="$VIEWER_PROJECT" COPYLOT_VIEWER_CONFIG="$VIEWER_CONFIG" COPYLOT_AI_MODE=1 \
      "$PYTHON_BIN" -m uvicorn app.main:app --host 127.0.0.1 --port 8001
  fi
) &
BACKEND_PID=$!

(
  cd "$FRONTEND_DIR"
  if [[ "$DEV_MODE" -eq 1 ]]; then
    VITE_APP_MODE=viewer VITE_AI_ENABLED=1 VITE_VIEWER_PORTAL_AUTH=0 VITE_RESET_ON_BROWSER_LOAD=0 VITE_AI_DEV_MODE=1 VITE_AI_DEFAULT_OLLAMA_ENDPOINT="$DEV_OLLAMA_ENDPOINT" VITE_PROXY_TARGET="http://127.0.0.1:8001" \
      npm run dev -- --port 5174
  else
    VITE_APP_MODE=viewer VITE_AI_ENABLED=1 VITE_VIEWER_PORTAL_AUTH=0 VITE_RESET_ON_BROWSER_LOAD=0 VITE_PROXY_TARGET="http://127.0.0.1:8001" \
      npm run dev -- --port 5174
  fi
) &
FRONTEND_PID=$!

sleep 3
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost:5174" >/dev/null 2>&1 || true
fi

if [[ -n "$VIEWER_PROJECT" ]]; then
  echo "Viewer app (AI mode) started (project: $VIEWER_PROJECT)."
else
  echo "Viewer app (AI mode) started."
fi
echo "Backend: http://127.0.0.1:8001"
echo "Frontend: http://localhost:5174"

wait "$BACKEND_PID" "$FRONTEND_PID"
