# Proteomics CoPYlot

Proteomics CoPYlot is a React and FastAPI application for proteomics and phosphoproteomics analysis, visualization, reporting, and read-only dataset sharing. It also provides notebook-facing Python and R helpers.

## Capabilities

- Upload tables from Spectronaut, DIA-NN, MaxQuant-derived, and similar workflows.
- Annotate samples and manage protein, peptide, phosphosite, and phosphoprotein datasets.
- Run completeness, quality-control, statistical, comparison, peptide, phospho, and single-protein workflows.
- Generate interactive Plotly and static Matplotlib/Seaborn plots.
- Customize plot titles, labels, colors, axes, grids, themes, and download output.
- Save and restore UI/report state.
- Publish configured datasets through read-only viewer and password-gated viewer-portal modes.
- Use optional Ollama-backed AI features.
- Reuse analysis helpers from Python or R notebooks.

## Quick start

Install backend and frontend dependencies on Windows:

```powershell
py -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm.cmd --prefix frontend install
```

Run the analysis application:

```powershell
.\packaging\windows\run_app.bat
```

Run the viewer:

```powershell
.\packaging\windows\run_viewer.bat
```

macOS and Linux launchers are grouped under `packaging/macos/` and `packaging/linux/`.

See [Installation, Running, and Packaging](docs/INSTALLATION.md) for every supported platform, AI variants, production launch, Docker, viewer portals, and executable/package builds.

## Application modes

- **Analysis:** full upload, annotation, analysis, external-tool, and report workflow.
- **Viewer:** read-only access to datasets configured by `viewer_config.json`.
- **Viewer portal:** password/session routing to projects under `viewer_data/`.
- **AI variants:** analysis or viewer modes with an Ollama-backed chat surface.

## Notebook package

Install the Python package locally:

```bash
python -m pip install -e .
```

Examples:

- `examples/example.ipynb`
- `examples/example.R`

The installable package includes:

- `proteomicscopylot/notebook_functions.py`
- `proteomicscopylot/notebook_functions.R`
- `proteomicscopylot/example_data/`

The Settings page reports whether `Rscript` is available. Detection checks explicit CoPYlot/R environment variables, `PATH`, and common platform installation locations.

## Repository map

- `backend/`: FastAPI routes, schemas, services, and runtime stores.
- `frontend/`: React/TypeScript UI and public assets.
- `proteomicscopylot/`: notebook APIs and canonical bundled example data.
- `examples/`: runnable notebook and R examples.
- `docs/`: installation and architectural guidance.
- `packaging/`: platform launchers and distribution builders.
- `deploy/`: hosting and reverse-proxy examples.
- `viewer_data/`: checked-in viewer examples and local/private project locations.
- `data/`: intentionally versioned biological reference resources.

See [Architecture and Repository Map](docs/ARCHITECTURE.md) for runtime flow and directory ownership.

## Viewer configuration

The checked-in `viewer_config.json` points to the canonical HEK293 example data in `proteomicscopylot/example_data/`. Local overrides and credentials belong under ignored `local/` files.

Viewer portal credential template:

```json
{
  "credentials": [
    { "password": "strong-pass-1", "project": "GRK_project", "label": "GRK Project" }
  ]
}
```

Do not commit real passwords or private project inputs.

## Docker

```bash
docker compose up -d --build
docker compose -f docker-compose.viewer.yml up -d --build
```

The nginx routing example is `deploy/nginx/proteomics-data.de.conf.example`.

## Development

Install development dependencies and run validation:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run lint
```

## License

Proteomics CoPYlot is distributed under the [GNU GPL version 3](LICENSE).
