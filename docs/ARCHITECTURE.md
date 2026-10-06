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

## What each implementation offers

The web app, the pip package (`notebook_functions.py`) and the R package
(`notebook_functions.R`) implement the same analyses. Where they share a
function, it has the same name, arguments and result; the tests under
`tests/parity/` compare the numbers. Differences:

| Feature | Web app | pip | R |
|---|---|---|---|
| Reading, sample IDs, log2, zero rule (`raw_zero_to_nan`), filtering, median and quantile normalization | ✓ | ✓ | ✓ |
| VSN normalization | ✓ (calls R `vsn`) | ✗ (raises; use R or the app) | ✓ |
| Imputation | ✓ | ✓ | ✓ (R's random-number generator, so draws differ from Python) |
| Volcano (± control, paired, Welch), ANOVA with Tukey | ✓ | ✓ | ✓ |
| PCA (`pca_scores`, `pca_plot`) | ✓ | ✓ | ✓ |
| UMAP and t-SNE | ✓ | ✗ | ✗ |
| Feature scaling choice for projections (`scaling=`) | ✓ (PCA, UMAP, t-SNE) | ✓ (PCA) | ✓ (PCA) |
| QC plots: coverage, boxplot, CV, histogram, Q-Q, correlation (`sample_correlation_matrix`), completeness tables | ✓ | ✓ | ✓ |
| ORA and pathway heatmap | ✓ | ✓ | ✓ |
| Kinase Library ("KSEA") | ✓ | ✓ | ✓ |
| Kinase tree data | ✗ | ✓ | ✓ |
| Phosphoprotein aggregation and regulation, site coverage, STY | ✓ | ✓ | ✓ |
| Peptide: protease rules, missed cleavages, RT, sequence coverage | ✓ | ✓ | ✓ |
| Single protein (`single_protein_values`, boxplot) | ✓ (boxplot, lineplot, heatmap) | ✓ (boxplot) | ✓ (boxplot) |
| ID translation | ✓ | ✗ | ✗ |

Conventions shared by all three:

- Filter modes are `per_group`, `in_at_least_one_group` and `overall`; the
  older spelling with spaces (`"per group"`) is still accepted.
- Unit-variance scaling divides by the sample standard deviation (n − 1), as R's
  `prcomp(scale. = TRUE)` does; row z-scores use the same convention.
- Fold changes are `condition1 − condition2`.
- A component's sign in PCA is arbitrary and may differ between implementations.

## Example data

`proteomicscopylot/example_data/` is the sole canonical example-data location. It is package data, is used by `examples/`, and backs the checked-in HEK293 viewer configuration. Do not create a second root-level copy.

## Deployment modes

- Analysis: upload, annotation, analysis, reports, and external tools.
- Viewer: read-only configured datasets.
- Viewer portal: password/session mapping to projects.
- AI variants: the same modes with an Ollama-backed chat surface.

The root `launch.py` is the shared production launcher; `launch_tool.py` and `launch_viewer.py` are packaging entry points and remain at root intentionally.
