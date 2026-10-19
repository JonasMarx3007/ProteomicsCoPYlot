#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${COPYLOT_BUILD_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
DIST_DIR="$ROOT_DIR/dist"
VALIDATE_ONLY=0
VARIANT=all

while [[ $# -gt 0 ]]; do
  case "$1" in
    --validate-only) VALIDATE_ONLY=1; shift ;;
    --variant) VARIANT="${2:?Expected all, standard or ai}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done
case "$VARIANT" in
  all|standard|ai) ;;
  *) echo "Expected variant all, standard or ai" >&2; exit 1 ;;
esac

PYTHON_BIN="$BACKEND_DIR/.venv/bin/python3"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Error: backend virtualenv Python not found in $BACKEND_DIR/.venv/bin"
  exit 1
fi

if [[ "$VALIDATE_ONLY" -eq 1 ]]; then
  echo "Validation successful."
  exit 0
fi

build_frontend() {
  local mode="$1"
  local ai_enabled="$2"

  (
    cd "$FRONTEND_DIR"
    VITE_APP_MODE="$mode" VITE_AI_ENABLED="$ai_enabled" npm run build
  )
}

build_binary() {
  local name="$1"
  local entry_point="$2"
  local legal_dir="$ROOT_DIR/build/legal/$name"
  "$PYTHON_BIN" "$ROOT_DIR/tools/package_release_licenses.py" prepare --legal-dir "$legal_dir"
  local notebook_source_args=()
  local notebook_source
  while IFS= read -r notebook_source || [[ -n "$notebook_source" ]]; do
    notebook_source="${notebook_source%%$'\r'}"
    [[ -z "${notebook_source// }" || "$notebook_source" == \#* ]] && continue
    notebook_source_args+=(--add-data "$ROOT_DIR/backend/app/services/$notebook_source:notebook_sources")
  done < "$ROOT_DIR/packaging/notebook_sources.txt"
  # Version metadata of every distribution a notebook export pins.
  local notebook_metadata_args=()
  local notebook_distribution
  while IFS= read -r notebook_distribution || [[ -n "$notebook_distribution" ]]; do
    notebook_distribution="${notebook_distribution%%$'\r'}"
    [[ -z "${notebook_distribution// }" || "$notebook_distribution" == \#* ]] && continue
    notebook_metadata_args+=(--copy-metadata "$notebook_distribution")
  done < "$ROOT_DIR/packaging/notebook_distributions.txt"

  (
    cd "$ROOT_DIR"
    "$PYTHON_BIN" -m PyInstaller \
      --noconfirm \
      --clean \
      --onefile \
      --name "$name" \
      --specpath "$ROOT_DIR/build/specs" \
      --paths "$BACKEND_DIR" \
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
      --add-data "$ROOT_DIR/frontend/dist:frontend_dist" \
      --add-data "$ROOT_DIR/data/db:data/db" \
      --add-data "$ROOT_DIR/data/report:data/report" \
      --add-data "$ROOT_DIR/proteomicscopylot/example_data:proteomicscopylot/example_data" \
      --add-data "$ROOT_DIR/viewer_config.json:." \
      --add-data "$ROOT_DIR/proteomicscopylot/notebook_functions.py:notebook_sources" \
      --add-data "$ROOT_DIR/proteomicscopylot/_core.py:notebook_sources" \
      "${notebook_source_args[@]}" \
      "${notebook_metadata_args[@]}" \
      --add-data "$ROOT_DIR/LICENSE:notebook_sources" \
      --add-data "$ROOT_DIR/NOTICE:notebook_sources" \
      --add-data "$legal_dir:legal" \
      "$ROOT_DIR/$entry_point"
  )
  "$PYTHON_BIN" "$ROOT_DIR/tools/package_release_licenses.py" finish --legal-dir "$legal_dir" --executable "$DIST_DIR/$name"
}

echo "[prep] Installing the release PyInstaller version..."
"$PYTHON_BIN" -m pip install "pyinstaller==6.19.0"

if [[ "$VARIANT" != all ]]; then
  if [[ "$VARIANT" == ai ]]; then
    build_frontend analysis 1
    build_binary ProteomicsCoPYlotAI launch_tool.py
  else
    build_frontend analysis 0
    build_binary ProteomicsCoPYlot launch_tool.py
  fi
  exit 0
fi

echo
echo "[1/4] Building ProteomicsCoPYlotAI..."
build_frontend "analysis" "1"
build_binary "ProteomicsCoPYlotAI" "launch_tool.py"

echo
echo "[2/4] Building DataViewerAI..."
build_frontend "viewer" "1"
build_binary "DataViewerAI" "launch_viewer.py"

echo
echo "[3/4] Building standard ProteomicsCoPYlot..."
build_frontend "analysis" "0"
build_binary "ProteomicsCoPYlot" "launch_tool.py"

echo
echo "[4/4] Building standard DataViewer..."
build_frontend "viewer" "0"
build_binary "DataViewer" "launch_viewer.py"

echo
echo "Build completed. Outputs:"
for file_name in \
  "ProteomicsCoPYlot" \
  "ProteomicsCoPYlotAI" \
  "DataViewer" \
  "DataViewerAI"; do
  if [[ -f "$DIST_DIR/$file_name" ]]; then
    echo "  $DIST_DIR/$file_name"
  else
    echo "  MISSING: $DIST_DIR/$file_name"
  fi
done
