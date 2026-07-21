# Proteomics CoPYlot (React + FastAPI Version)

Proteomics CoPYlot is a tool for proteomics data analysis and visualization with a modern frontend/backend architecture.
It provides the full analysis workflow and a separate read-only viewer workflow.

## Features

- Upload and analyze proteomics tables from typical workflows (for example Spectronaut, DIA-NN, MaxQuant-derived exports)
- Pipeline-based UI with translated modules from the original project
- QC, statistical analysis, comparison, phospho-specific analysis, peptide-level modules, and summary/report generation
- Interactive and static plot outputs (Plotly + Matplotlib/Seaborn) with report integration
- Dedicated viewer mode for preloaded data without upload/annotation editing
- Password-gated viewer portal mode (`/viewer`, `/viewer-ai`) with project selection by password

## Modes

- Analysis tool: full workflow with upload, annotation, analysis, and report generation
- Viewer: read-only mode for provided datasets via `viewer_config.json`
- Local viewer override: place local-only settings under `local/`, for example `local/viewer_config.local.json`.
- Viewer portal (optional): password login that maps each user session to a project folder in `viewer_data/<ProjectName>/`.

## Pipelines

- Data
- Completeness
- QC Pipeline
- Statistical Analysis
- Peptide Level (when peptide data is available)
- Phospho-specific (when phospho data is available)
- Comparison
- Summary
- External Tool (analysis mode only)

## Installation

Use the ordered install/run/build guide in [readme.txt](./readme.txt), organized as:

- Global notes and AI prerequisites
- Windows: install, run, production run, onefile EXE build
- macOS: install, run, production run, onefile app build
- Linux: install, run, production run, onefile app build
- Remote Ollama hosting over Tailscale

## Notebook Package

The notebook-facing Python API is packaged as `proteomicscopylot`.

Local editable install:

```bash
python -m pip install -e .
```

Build distributions:

```bash
python -m pip install build twine
python build_pip_package.py
```

Upload a new version to PyPI:

```bash
python -m twine upload dist/*
```

Every PyPI upload needs a new version in `pyproject.toml` and
`proteomicscopylot/_version.py`; existing versions cannot be overwritten.

## Usage

Windows:

- Analysis: `run_app.bat`
- Viewer: `run_viewer.bat`
- Viewer (specific project): `run_viewer.bat --project GRK_project` or `run_viewer.bat --GRK_project`
- Analysis (AI): `run_app_ai.bat [--model-name]`
- Viewer (AI): `run_viewer_ai.bat [--model-name] [--project GRK_project]`

macOS:

- Analysis: `./run_app_macos.sh`
- Viewer: `./run_viewer_macos.sh`
- Viewer (specific project): `./run_viewer_macos.sh --project GRK_project` or `./run_viewer_macos.sh --GRK_project`
- Analysis (AI): `./run_app_ai_macos.sh [--model-name]`
- Viewer (AI): `./run_viewer_ai_macos.sh [--model-name] [--project GRK_project]`

Linux:

- Analysis: `./run_app_linux.sh`
- Viewer: `./run_viewer_linux.sh`
- Viewer (specific project): `./run_viewer_linux.sh --project GRK_project` or `./run_viewer_linux.sh --GRK_project`
- Analysis (AI): `./run_app_ai_linux.sh [--model-name]`
- Viewer (AI): `./run_viewer_ai_linux.sh [--model-name] [--project GRK_project]`

## Viewer Portal (Password -> Project)

For hosted viewer portals (for example behind nginx on `/viewer` and `/viewer-ai`), enable:

- `COPYLOT_VIEWER_MODE=1`
- `COPYLOT_VIEWER_PORTAL_ENABLED=1`
- `COPYLOT_VIEWER_ACCESS_FILE=/app/local/viewer_access.local.json`

`local/viewer_access.local.json` format:

```json
{
  "credentials": [
    { "password": "strong-pass-1", "project": "GRK_project", "label": "GRK Project" },
    { "password": "strong-pass-2", "project": "TKI_project", "label": "TKI Project" }
  ]
}
```

Project folders:

- `viewer_data/GRK_project/viewer_config.json`
- `viewer_data/TKI_project/viewer_config.json`

Each browser session is isolated (`COPYLOT_SESSION_ISOLATION=1`), and viewer project data is loaded into that specific session after successful login.

## AI Prerequisite

AI mode requires a local [Ollama](https://ollama.com) installation (system dependency, not a Python `pip` package).

Examples:

- `run_app_ai.bat --deepseek-r1:1.5b`
- `run_viewer_ai.bat --deepseek-r1:1.5b`
- `run_app_ai.bat --dev`
- `run_app_ai.bat --dev0`
- `run_app_ai.bat --dev2`
- `run_app_ai.bat --dev20`
- `run_viewer_ai.bat --dev`
- `run_viewer_ai.bat --dev0`
- `run_viewer_ai.bat --dev2`
- `run_viewer_ai.bat --dev20`

## Windows Onefile EXE Builds

PowerShell (inside project root):

- Tool: `.\build_exe_windows.ps1 -Target Tool`
- Viewer: `.\build_exe_windows.ps1 -Target Viewer`
- Viewer (single project bundle): `.\build_exe_windows.ps1 -Target Viewer -ViewerProject GRK_project`

CMD (inside project root):

- Tool: `powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Tool`
- Viewer: `powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Viewer`

Outputs:

- `dist/ProteomicsCoPYlot.exe`
- `dist/DataViewer.exe`

## Windows AI Onefile EXE Builds

Build note:

- AI-enabled builds require frontend AI flags at build time.
- Runtime AI still requires `COPYLOT_AI_MODE=1` when launching the EXE.

Tool (AI):

```powershell
cd C:\PythonProject\ProteomicsCoPYlot\frontend
cmd /c "set VITE_APP_MODE=analysis&& set VITE_AI_ENABLED=1&& npm run build"
Set-Content -Path .\dist\.copylot_mode.txt -Value analysis -NoNewline
cd ..
powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Tool -SkipFrontendBuild
```

Tool (AI dev20 default endpoint):

```powershell
cd C:\PythonProject\ProteomicsCoPYlot\frontend
$DEV20_ENDPOINT = (Get-Content ..\local\dev_ai.local.env | Where-Object { $_ -like "COPYLOT_DEV2_OLLAMA_ENDPOINT=*" } | Select-Object -First 1).Split("=", 2)[1]
cmd /c "set VITE_APP_MODE=analysis&& set VITE_AI_ENABLED=1&& set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=$DEV20_ENDPOINT&& set VITE_AI_DEFAULT_OLLAMA_MODEL=llama3.1:8b&& npm run build"
Set-Content -Path .\dist\.copylot_mode.txt -Value analysis -NoNewline
cd ..
powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Tool -SkipFrontendBuild
```

Viewer (AI):

```powershell
cd C:\PythonProject\ProteomicsCoPYlot\frontend
cmd /c "set VITE_APP_MODE=viewer&& set VITE_AI_ENABLED=1&& npm run build"
Set-Content -Path .\dist\.copylot_mode.txt -Value viewer -NoNewline
cd ..
powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Viewer -SkipFrontendBuild
```

Viewer (AI dev20 default endpoint):

```powershell
cd C:\PythonProject\ProteomicsCoPYlot\frontend
$DEV20_ENDPOINT = (Get-Content ..\local\dev_ai.local.env | Where-Object { $_ -like "COPYLOT_DEV2_OLLAMA_ENDPOINT=*" } | Select-Object -First 1).Split("=", 2)[1]
cmd /c "set VITE_APP_MODE=viewer&& set VITE_AI_ENABLED=1&& set VITE_AI_DEFAULT_OLLAMA_ENDPOINT=$DEV20_ENDPOINT&& set VITE_AI_DEFAULT_OLLAMA_MODEL=llama3.1:8b&& npm run build"
Set-Content -Path .\dist\.copylot_mode.txt -Value viewer -NoNewline
cd ..
powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Viewer -SkipFrontendBuild
```

Run AI EXEs:

```powershell
set COPYLOT_AI_MODE=1
.\dist\ProteomicsCoPYlot.exe
.\dist\DataViewer.exe
```

## Project Structure

- `frontend/`: React + TypeScript UI
- `backend/`: FastAPI API + services
- `viewer_data/`: data folder for viewer inputs
- `viewer_data/<ProjectName>/`: project-specific viewer folders (each with its own `viewer_config.json`)
- `viewer_data/local/<ProjectName>/`: ignored local/private viewer projects
- `viewer_config.json`: viewer dataset/config mapping
- `viewer_access.example.json`: template for password-to-project mapping in viewer portal mode
- `launch.py`: shared runtime launcher
- `launch_tool.py`: analysis launcher entrypoint
- `launch_viewer.py`: viewer launcher entrypoint

## Development Map

- The React/TypeScript frontend calls the FastAPI routes under `backend/app/api/` through `frontend/src/lib/api.ts`.
- FastAPI routes validate models from `backend/app/schemas/`; analysis logic belongs in `backend/app/services/`.
- Session-scoped datasets and metadata are managed by backend stores. Browser-only presentation settings use local storage and are included in saved UI state.
- Plot generation is split between interactive Plotly responses and static Matplotlib/Seaborn images. Advanced plot settings travel from the frontend as an `advanced` query parameter.
- Notebook helpers live in `proteomicscopylot/notebook_functions.py` for Python and `proteomicscopylot/notebook_functions.R` for R.

## R Notebook Compatibility

The Settings page reports whether `Rscript` is available. Detection checks `COPYLOT_RSCRIPT`, `COPYLOT_R_BINARY`, or `RSCRIPT`, then `PATH`, then common platform-specific installation paths. Run `example.R` from the repository for an R usage example; installed Python distributions also include `proteomicscopylot/notebook_functions.R`.

## Docker Compose (Viewer Portals)

Use the dedicated compose file for hosted viewer portals:

```bash
docker compose -f docker-compose.viewer.yml up -d --build
```

Containers:

- `proteomics-viewer` on port `18081` (non-AI viewer)
- `proteomics-viewer-ai` on port `18082` (AI-enabled viewer)

Both expect a local `local/viewer_access.local.json` file and shared `viewer_data/` folder.

## Nginx Routing Example

An example nginx config is included at:

- `deploy/nginx/proteomics-data.de.conf.example`

It routes:

- `/` -> analysis app
- `/ai` -> analysis AI app
- `/viewer` -> viewer portal (password-based project selection)
- `/viewer-ai` -> viewer AI portal

## Deploy on Render (Docker)

This repository now includes:

- `Dockerfile` for combined frontend+backend deployment
- `.dockerignore` for smaller and faster Docker builds
- `render.yaml` Blueprint for one-click Render setup

Steps:

1. Push this repository to GitHub.
2. In Render, create a Blueprint and point it to this repo (it will detect `render.yaml`).
3. If `proteomics-copylot` is already taken in your Render workspace, rename the service in `render.yaml` and push again.
4. Wait for the first deploy to finish, then open the generated `*.onrender.com` URL.
5. Confirm health endpoint works at `/api/health`.

Notes:

- Free plan instances have important limits and can sleep when idle.
- Service filesystems are ephemeral; runtime-written local files are not durable across redeploys.
- AI mode is disabled by default in `render.yaml` (`COPYLOT_AI_MODE=0`).

## License

Licensed under the GNU GPL version 3. See [LICENSE](./LICENSE).
