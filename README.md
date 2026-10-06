# Proteomics CoPYlot

[![tests](https://github.com/JonasMarx3007/ProteomicsCoPYlot/actions/workflows/tests.yml/badge.svg)](https://github.com/JonasMarx3007/ProteomicsCoPYlot/actions/workflows/tests.yml)
[![cross-implementation](https://github.com/JonasMarx3007/ProteomicsCoPYlot/actions/workflows/cross-implementation.yml/badge.svg)](https://github.com/JonasMarx3007/ProteomicsCoPYlot/actions/workflows/cross-implementation.yml)

Proteomics CoPYlot is a React and FastAPI application for proteomics and phosphoproteomics analysis, visualization, reporting, and read-only dataset sharing. It also provides notebook-facing Python and R helpers.

## Capabilities

- Upload wide-format quantitative tables; Spectronaut and DIA-NN column names are recognized automatically, and other exports can be mapped by naming the sample columns during annotation.
- Annotate samples and manage protein, peptide, phosphosite, and phosphoprotein datasets.
- Run completeness, quality-control, statistical, comparison, peptide, phospho, and single-protein workflows.
- Generate interactive Plotly and static Matplotlib/Seaborn plots.
- Customize plot titles, labels, colors, axes, grids, themes, and download output.
- Save and restore UI/report state, with a portable export that omits local dataset paths for sharing.
- Publish configured datasets through read-only viewer and password-gated viewer-portal modes.
- Use optional AI features, backed either by a local Ollama instance or by a cloud provider.
- Reuse analysis helpers from Python or R notebooks.

For phosphoprotein analysis, missing values can be imputed at the phosphosite level
before collapsing, never on the collapsed phosphoprotein matrix. Both imputed and
non-imputed inputs are supported. Keep the original observations alongside imputed
data to preserve meaningful site-coverage diagnostics. Ordinary protein imputation
remains available.

## Quick start

Refreshing the analysis app starts a new analysis. After interaction, the browser
warns before refresh/close/navigation if analysis data or saved UI settings have
changed since the last successful save; cancelling leaves the current page intact.
The browser controls the wording and may suppress the dialog, especially on mobile,
so save important work explicitly. Native file writes establish the saved baseline
only after completion. For ordinary downloads, confirm that the file was downloaded;
otherwise the warning remains active. Failed or uncertain backend writes conservatively
remain unsaved until saving again. Viewer mode does not reset or show this analysis warning.

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
- **AI variants:** analysis or viewer modes with a chat surface.

### Metadata profiles

Uploaded annotation metadata must contain a sample column and one to five categorical
grouping columns. Each grouping column becomes a source metadata profile; `pair_id`, when
present, is retained as pairing structure rather than treated as a group. CoPYlot creates
every non-singleton combination of the source profiles automatically, so five grouping
columns produce 26 derived profiles. A conventional two-column `sample,condition` file
continues to populate the currently selected profile. Uploads above the five-profile limit
are rejected before any profile is changed. Deleting a source profile also deletes its
dependent derived profiles and frees a source-profile slot.

### AI providers and data handling

The chat surface runs against a local [Ollama](https://ollama.com) instance by default, in which
case nothing leaves the machine. It can also be pointed at a cloud provider, which requires an
API key and sends data to that provider:

| provider | endpoint |
|---|---|
| Ollama (default) | local, no external request |
| OpenAI | `https://api.openai.com/v1/chat/completions` |
| Anthropic | `https://api.anthropic.com/v1/messages` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/models` |

When a cloud provider is selected, the request includes context derived from the loaded dataset
— condition-level summary statistics, top differential hits, and similar values — not only the
question that was typed. Use the local Ollama option for unpublished or otherwise sensitive
data.

Provide the key through `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` where
possible; a key set in the environment takes precedence over one entered in the interface and
is never transmitted from the browser.

## Notebook package

Install the Python package locally:

```bash
python -m pip install -e ".[bio]"
```

Install the optional R packages used by the complete R helper:

```r
install.packages(c("arrow", "hexbin", "plotly", "readxl", "scatterplot3d", "VennDiagram"))
# VSN normalization (optional) comes from Bioconductor:
install.packages("BiocManager"); BiocManager::install("vsn")
```

Examples:

- `examples/example.ipynb`
- `examples/example.R`

The Python notebook, R notebook, and UI pipelines support the same core analysis
workflows. Use the examples above for detailed usage and parameter choices.

The installable package includes:

- `proteomicscopylot/notebook_functions.py`
- `proteomicscopylot/notebook_functions.R`
- `proteomicscopylot/example_data/`
- the Gene Ontology reference table

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
    {
      "password_pbkdf2_sha256": "GENERATED_VALUE",
      "project": "HEK293",
      "label": "HEK293 example"
    }
  ]
}
```

Do not commit real passwords or private project inputs.

The Docker stacks also require local credential files. Copy the three checked-in
`*.example.json` templates into `local/` as described in
[Installation, Running, and Packaging](docs/INSTALLATION.md), replace their zero digests,
and keep the resulting `*.local.json` files private.

Tool and QR bearer links use URL fragments (`#tool=...` and `#qr=...`). Credentials in query
strings are deliberately ignored because proxies and referrers can log them.

## Docker

```bash
docker compose up -d --build
docker compose -f docker-compose.viewer.yml up -d --build
```

## Development

Install development dependencies and run validation:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run lint
```

For a reproducible Python 3.13 reference environment, install
`backend/requirements.lock` and then install this package editable with
`--no-deps`. Production Docker builds use the smaller
`backend/requirements-runtime.lock`; security CI audits both exact locks.

## Methods and citations

Several analyses re-implement or delegate to published methods. If you use them,
please cite the original work alongside this software.

| Method | Where it is used | Reference |
| --- | --- | --- |
| Quantile normalization | Normalization across samples | Bolstad *et al.* (2003), [10.1093/bioinformatics/19.2.185](https://doi.org/10.1093/bioinformatics/19.2.185) |
| Downshifted-normal imputation | Missing-value imputation | Tyanova *et al.* (2016), [10.1038/nmeth.3901](https://doi.org/10.1038/nmeth.3901) |
| Variance-stabilizing normalization | Normalization delegated to Bioconductor VSN | Huber *et al.* (2002), [10.1093/bioinformatics/18.suppl_1.S96](https://doi.org/10.1093/bioinformatics/18.suppl_1.S96) |
| Benjamini–Hochberg false discovery rate | Multiple-testing correction | Benjamini & Hochberg (1995), [10.1111/j.2517-6161.1995.tb02031.x](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x) |
| Tukey–Kramer post-hoc | Pairwise comparisons after ANOVA | Tukey (1949), *Biometrics* 5:99–114; Kramer (1956), *Biometrics* 12:307–310 |
| Kinase–substrate specificity atlases | Kinase Library input preparation and result visualization | Johnson *et al.* (2023), [10.1038/s41586-022-05575-3](https://doi.org/10.1038/s41586-022-05575-3); Yaron-Barir *et al.* (2024), [10.1038/s41586-024-07407-y](https://doi.org/10.1038/s41586-024-07407-y) |

Kinase enrichment is calculated externally in the
[Kinase Library](https://kinase-library.phosphosite.org). CoPYlot prepares the
phosphosite input and visualizes the returned results.

## License

Proteomics CoPYlot code is distributed under the [GNU GPL version 3](LICENSE). Bundled biological
reference data retain their upstream terms and attribution; see
[Biological reference data](data/db/README.md).

The bundled HEK293 demonstration dataset is released separately under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — see
[Example data](proteomicscopylot/example_data/README.md) for its contents,
checksums, experimental design, and provenance.

For citation metadata, see [CITATION.cff](CITATION.cff). Deployment security
requirements are covered in [Installation, Running, and Packaging](docs/INSTALLATION.md).
