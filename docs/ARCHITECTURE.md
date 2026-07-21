# Architecture and Repository Map

## Runtime flow

The React/TypeScript frontend calls FastAPI endpoints through `frontend/src/lib/api.ts`. Routes under `backend/app/api/` validate models from `backend/app/schemas/` and delegate analysis to `backend/app/services/`.

Dataset, metadata, viewer, and authentication state are session-scoped in backend stores. Browser-only presentation preferences use local storage and are included in saved UI state.

Plot output has two paths:

- interactive Plotly HTML responses;
- static Matplotlib/Seaborn images.

Advanced plot settings are serialized by the frontend and sent through the `advanced` request parameter.

## Repository ownership

- `backend/`: FastAPI application, schemas, services, and runtime state.
- `frontend/`: React UI plus public runtime assets and generated manuals.
- `proteomicscopylot/`: installable Python notebook API, monolithic R helper, and canonical bundled example data.
- `examples/`: runnable Python notebook and R examples.
- `docs/`: installation, architecture, and longer-lived project guidance.
- `packaging/`: platform launchers and distribution-build helpers.
- `deploy/`: reverse-proxy and hosting examples.
- `data/`: intentionally versioned biological reference databases and report assets.
- `viewer_data/`: public/example viewer projects; private projects belong under ignored local paths.

Root files are reserved for conventional tooling and true entry points: Git/Docker configuration, `pyproject.toml`, `launch*.py`, public viewer configuration templates, the license, and the main README.

## Notebook APIs

`proteomicscopylot/notebook_functions.py` and `proteomicscopylot/notebook_functions.R` intentionally expose broad notebook APIs as single source files. Their monolithic form supports simple sourcing/importing and cross-language discoverability. Do not split them solely to reduce line count. Refactor them only when a concrete correctness or maintainability benefit outweighs compatibility costs.

## Example data

`proteomicscopylot/example_data/` is the sole canonical example-data location. It is package data, is used by `examples/`, and backs the checked-in HEK293 viewer configuration. Do not create a second root-level copy.

## Deployment modes

- Analysis: upload, annotation, analysis, reports, and external tools.
- Viewer: read-only configured datasets.
- Viewer portal: password/session mapping to projects.
- AI variants: the same modes with an Ollama-backed chat surface.

The root `launch.py` is the shared production launcher; `launch_tool.py` and `launch_viewer.py` are packaging entry points and remain at root intentionally.
