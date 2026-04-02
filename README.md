# Proteomics CoPYlot (React + FastAPI Version)

Proteomics CoPYlot is a tool for proteomics data analysis and visualization with a modern frontend/backend architecture.
It provides the full analysis workflow and a separate read-only viewer workflow.

## Features

- Upload and analyze proteomics tables from typical workflows (for example Spectronaut, DIA-NN, MaxQuant-derived exports)
- Pipeline-based UI with translated modules from the original project
- QC, statistical analysis, comparison, phospho-specific analysis, peptide-level modules, and summary/report generation
- Interactive and static plot outputs (Plotly + Matplotlib/Seaborn) with report integration
- Dedicated viewer mode for preloaded data without upload/annotation editing

## Modes

- Analysis tool: full workflow with upload, annotation, analysis, and report generation
- Viewer: read-only mode for provided datasets via `viewer_config.json`

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

Use the concise install/run guide in [readme.txt](./readme.txt) for:

- Windows
- macOS
- Linux
- Development run
- Production run
- Windows onefile executable builds

## Usage

Windows:

- Analysis: `run_app.bat`
- Viewer: `run_viewer.bat`
- Analysis (AI): `run_app_ai.bat [--model-name]`
- Viewer (AI): `run_viewer_ai.bat [--model-name]`

macOS:

- Analysis: `./run_app_macos.sh`
- Viewer: `./run_viewer_macos.sh`
- Analysis (AI): `./run_app_ai_macos.sh [--model-name]`
- Viewer (AI): `./run_viewer_ai_macos.sh [--model-name]`

Linux:

- Analysis: `./run_app_linux.sh`
- Viewer: `./run_viewer_linux.sh`
- Analysis (AI): `./run_app_ai_linux.sh [--model-name]`
- Viewer (AI): `./run_viewer_ai_linux.sh [--model-name]`

## AI Prerequisite

AI mode requires a local [Ollama](https://ollama.com) installation (system dependency, not a Python `pip` package).

Examples:

- `run_app_ai.bat --deepseek-r1:1.5b`
- `run_viewer_ai.bat --deepseek-r1:1.5b`

## Windows Onefile EXE Builds

PowerShell (inside project root):

- Tool: `.\build_exe_windows.ps1 -Target Tool`
- Viewer: `.\build_exe_windows.ps1 -Target Viewer`

CMD (inside project root):

- Tool: `powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Tool`
- Viewer: `powershell -ExecutionPolicy Bypass -File ".\build_exe_windows.ps1" -Target Viewer`

Outputs:

- `dist/ProteomicsCoPYlot.exe`
- `dist/DataViewer.exe`

## Project Structure

- `frontend/`: React + TypeScript UI
- `backend/`: FastAPI API + services
- `viewer_data/`: data folder for viewer inputs
- `viewer_config.json`: viewer dataset/config mapping
- `launch.py`: shared runtime launcher
- `launch_tool.py`: analysis launcher entrypoint
- `launch_viewer.py`: viewer launcher entrypoint

## License

Licensed under the MIT License. See [LICENSE](./LICENSE).
