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

macOS:

- Analysis: `./run_app_macos.sh`
- Viewer: `./run_viewer_macos.sh`

Linux:

- Analysis: `./run_app_linux.sh`
- Viewer: `./run_viewer_linux.sh`

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
