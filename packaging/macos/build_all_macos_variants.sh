#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
DIST_DIR="$ROOT_DIR/dist"
DEV_CONFIG="$ROOT_DIR/local/dev_ai.local.env"
if [[ ! -f "$DEV_CONFIG" ]]; then
  DEV_CONFIG="$ROOT_DIR/dev_ai.local.env"
fi
DEV20_ENDPOINT=""
VALIDATE_ONLY=0

if [[ "${1:-}" == "--validate-only" ]]; then
  VALIDATE_ONLY=1
fi

PYTHON_BIN="$BACKEND_DIR/.venv/bin/python3"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: backend virtualenv Python not found in $BACKEND_DIR/.venv/bin"
  exit 1
fi

if [[ ! -f "$DEV_CONFIG" ]]; then
  echo "Error: dev config not found: $DEV_CONFIG"
  exit 1
fi

while IFS='=' read -r raw_key raw_value || [[ -n "${raw_key:-}" ]]; do
  key="$(echo "${raw_key:-}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  value="$(echo "${raw_value:-}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
  if [[ -z "$key" || "$key" == \#* ]]; then
    continue
  fi
  if [[ "$key" == "COPYLOT_DEV2_OLLAMA_ENDPOINT" ]]; then
    DEV20_ENDPOINT="$value"
  fi
done < "$DEV_CONFIG"

if [[ -z "$DEV20_ENDPOINT" ]]; then
  echo "Error: COPYLOT_DEV2_OLLAMA_ENDPOINT missing in $DEV_CONFIG"
  exit 1
fi

if [[ "$VALIDATE_ONLY" -eq 1 ]]; then
  echo "Validation successful."
  echo "Using dev20 endpoint from dev_ai.local.env"
  exit 0
fi

build_frontend() {
  local mode="$1"
  local ai_enabled="$2"
  local endpoint="${3:-}"
  local default_model="${4:-}"

  (
    cd "$FRONTEND_DIR"
    if [[ -n "$endpoint" && -n "$default_model" ]]; then
      VITE_APP_MODE="$mode" \
      VITE_AI_ENABLED="$ai_enabled" \
      VITE_AI_DEFAULT_OLLAMA_ENDPOINT="$endpoint" \
      VITE_AI_DEFAULT_OLLAMA_MODEL="$default_model" \
      npm run build
    elif [[ -n "$endpoint" ]]; then
      VITE_APP_MODE="$mode" \
      VITE_AI_ENABLED="$ai_enabled" \
      VITE_AI_DEFAULT_OLLAMA_ENDPOINT="$endpoint" \
      npm run build
    elif [[ "$ai_enabled" == "1" ]]; then
      VITE_APP_MODE="$mode" \
      VITE_AI_ENABLED=1 \
      npm run build
    else
      VITE_APP_MODE="$mode" \
      npm run build
    fi
    printf "%s" "$mode" > "$FRONTEND_DIR/dist/.copylot_mode.txt"
  )
}

build_binary() {
  local name="$1"
  local entry_point="$2"

  (
    cd "$ROOT_DIR"
    "$PYTHON_BIN" -m PyInstaller \
      --noconfirm \
      --clean \
      --onefile \
      --name "$name" \
      --paths "backend" \
      --hidden-import "uvicorn.logging" \
      --hidden-import "uvicorn.loops.auto" \
      --hidden-import "uvicorn.protocols.http.auto" \
      --hidden-import "uvicorn.protocols.websockets.auto" \
      --hidden-import "uvicorn.lifespan.on" \
      --collect-all "fastapi" \
      --collect-all "starlette" \
      --collect-all "uvicorn" \
      --collect-all "pandas" \
      --collect-all "numpy" \
      --collect-all "scipy" \
      --collect-all "sklearn" \
      --collect-all "umap" \
      --collect-all "matplotlib" \
      --collect-all "seaborn" \
      --collect-all "plotly" \
      --collect-all "pyarrow" \
      --collect-all "openpyxl" \
      --add-data "frontend/dist:frontend_dist" \
      --add-data "data/db:data/db" \
      --add-data "data/report:data/report" \
      --add-data "proteomicscopylot/example_data:proteomicscopylot/example_data" \
      --add-data "viewer_config.json:." \
      --add-data "viewer_data:viewer_data" \
      "$entry_point"
  )
}

echo "[prep] Installing/upgrading pyinstaller in backend venv..."
"$PYTHON_BIN" -m pip install --upgrade pip pyinstaller

echo
echo "[1/6] Building ProteomicsCoPYlotAI..."
build_frontend "analysis" "1" "" ""
build_binary "ProteomicsCoPYlotAI" "launch_tool.py"

echo
echo "[2/6] Building ProteomicsCoPYlotAIDev20..."
build_frontend "analysis" "1" "$DEV20_ENDPOINT" "llama3.1:8b"
build_binary "ProteomicsCoPYlotAIDev20" "launch_tool.py"

echo
echo "[3/6] Building DataViewerAI..."
build_frontend "viewer" "1" "" ""
build_binary "DataViewerAI" "launch_viewer.py"

echo
echo "[4/6] Building DataViewerAIDev20..."
build_frontend "viewer" "1" "$DEV20_ENDPOINT" "llama3.1:8b"
build_binary "DataViewerAIDev20" "launch_viewer.py"

echo
echo "[5/6] Building standard ProteomicsCoPYlot..."
build_frontend "analysis" "0" "" ""
build_binary "ProteomicsCoPYlot" "launch_tool.py"

echo
echo "[6/6] Building standard DataViewer..."
build_frontend "viewer" "0" "" ""
build_binary "DataViewer" "launch_viewer.py"

echo
echo "Build completed. Outputs:"
for file_name in \
  "ProteomicsCoPYlot" \
  "ProteomicsCoPYlotAI" \
  "ProteomicsCoPYlotAIDev20" \
  "DataViewer" \
  "DataViewerAI" \
  "DataViewerAIDev20"; do
  if [[ -f "$DIST_DIR/$file_name" ]]; then
    echo "  $DIST_DIR/$file_name"
  else
    echo "  MISSING: $DIST_DIR/$file_name"
  fi
done
