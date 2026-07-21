# Installation, Running, and Packaging

Run commands from the repository root unless a section says otherwise.

## Prerequisites

- Python 3.10 or newer
- Node.js and npm
- Optional: [Ollama](https://ollama.com) for AI mode
- Optional: R with `Rscript` for the R notebook-compatible helpers

## Install

### Windows

```powershell
py -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd --prefix frontend install
```

For development and tests, also install:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

### macOS and Linux

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend install
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
```

## Development launchers

Platform launchers are grouped under `packaging/` and resolve the repository root automatically.

### Windows

```powershell
.\packaging\windows\run_app.bat
.\packaging\windows\run_viewer.bat
.\packaging\windows\run_app_ai.bat [model-or-dev-flag]
.\packaging\windows\run_viewer_ai.bat [model-or-dev-flag] [--project NAME]
```

Supported development flags include `--dev`, `--dev0`, `--dev2`, and `--dev20`.

### macOS

```bash
bash packaging/macos/run_app_macos.sh
bash packaging/macos/run_viewer_macos.sh
bash packaging/macos/run_app_ai_macos.sh [model-or-dev-flag]
bash packaging/macos/run_viewer_ai_macos.sh [model-or-dev-flag] [--project NAME]
```

### Linux

```bash
bash packaging/linux/run_app_linux.sh
bash packaging/linux/run_viewer_linux.sh
bash packaging/linux/run_app_ai_linux.sh [model-or-dev-flag]
bash packaging/linux/run_viewer_ai_linux.sh [model-or-dev-flag] [--project NAME]
```

Viewer projects can be selected with `--project NAME`, `--project=NAME`, or the existing shorthand `--NAME`.

## Production launch

Build the frontend and let the shared launcher serve it through FastAPI:

```powershell
npm.cmd --prefix frontend run build
.\backend\.venv\Scripts\python.exe launch.py
.\backend\.venv\Scripts\python.exe launch.py --viewer --port 8001
```

On macOS/Linux, use `backend/.venv/bin/python` instead.

## Frontend modes

The analysis and viewer bundles are distinct builds:

```powershell
cd frontend
cmd /c "set VITE_APP_MODE=analysis&& npm run build"
cmd /c "set VITE_APP_MODE=viewer&& npm run build"
```

AI builds additionally set `VITE_AI_ENABLED=1`. Runtime AI mode requires `COPYLOT_AI_MODE=1` and an available Ollama endpoint.

## Windows one-file builds

```powershell
.\packaging\windows\build_exe_windows.ps1 -Target Tool
.\packaging\windows\build_exe_windows.ps1 -Target Viewer
.\packaging\windows\build_exe_windows.ps1 -Target Viewer -ViewerProject GRK_project
```

Outputs:

- `dist/ProteomicsCoPYlot.exe`
- `dist/DataViewer.exe`

Build all configured Windows variants with:

```powershell
.\packaging\windows\build_all_windows_variants.cmd
```

macOS variant builds are under `packaging/macos/`.

## Python package

Install the notebook-facing package locally:

```bash
python -m pip install -e .
```

Build source and wheel distributions:

```bash
python packaging/python/build_pip_package.py
```

Every PyPI upload requires a new version in both `pyproject.toml` and `proteomicscopylot/_version.py`.

## Validation

```powershell
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run lint
docker compose config -q
docker compose -f docker-compose.viewer.yml config -q
```

The full frontend lint command currently has an existing baseline of React effect-state and memoization findings. New or touched frontend files should not add findings.

## Viewer portal

For password-to-project routing, set:

- `COPYLOT_VIEWER_MODE=1`
- `COPYLOT_VIEWER_PORTAL_ENABLED=1`
- `COPYLOT_VIEWER_ACCESS_FILE=/app/local/viewer_access.local.json`

Use `viewer_access.example.json` as the public template. Keep real credentials under ignored `local/` files.

Project data belongs in `viewer_data/<ProjectName>/`. Private local-only projects may use `viewer_data/local/<ProjectName>/`.

## Docker

General deployment:

```bash
docker compose up -d --build
```

Viewer portals:

```bash
docker compose -f docker-compose.viewer.yml up -d --build
```

The nginx example is `deploy/nginx/proteomics-data.de.conf.example`.

## Remote Ollama over Tailscale

1. Install Ollama and Tailscale on the host.
2. Bind Ollama to the tailnet-accessible interface, for example `OLLAMA_HOST=0.0.0.0:11434`.
3. Pull the intended model with `ollama pull MODEL`.
4. Allow TCP port `11434` through the host firewall when needed.
5. From the client, verify `http://TAILSCALE_HOST:11434/api/tags`.
6. Enter that endpoint in the application’s AI settings.

Do not commit private endpoints, credentials, or machine-specific configuration.
