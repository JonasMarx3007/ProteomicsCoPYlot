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
- Use optional AI features, backed by a local Ollama instance, a local server with the OpenAI-compatible API (llama.cpp, vLLM, LM Studio), or a cloud provider.
- Reuse analysis helpers from Python or R notebooks.

## Download and run

Download the complete ZIP for your computer from
[GitHub Releases](https://github.com/JonasMarx3007/ProteomicsCoPYlot/releases),
including releases marked **Pre-release** during the beta. Choose the standard
edition or the **AI** edition for the optional chat features, then extract the ZIP.
These application downloads include Python; no separate Python installation is needed.

On Windows, open `ProteomicsCoPYlot.exe` (or `ProteomicsCoPYlotAI.exe`). On Linux
or macOS, run the extracted `./ProteomicsCoPYlot` (or `./ProteomicsCoPYlotAI`)
from a terminal. Keep the terminal open while using the app; the interface opens
in your browser. Choose `arm64` for Apple Silicon Macs and `x86_64` for Intel Macs.

**Please allow time for startup and launch only once.** CoPYlot first unpacks
its bundled Python runtime, loads the scientific libraries, and starts a local
server. The browser interface connects to that server once it is ready.

| Build (standard and AI) | Approximate startup |
| --- | --- |
| Windows | 1–2 minutes |
| Linux (Docker) | About 20 seconds |

## Quick start from source

The current development release is **1.0.0 Beta 1** (planned GitHub tag
`v1.0.0-beta.1`). Python metadata uses the equivalent version `1.0.0b1`.
See [release versions](docs/RELEASING.md) for the naming convention.

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

On macOS and Linux, the same launchers are in `packaging/unix/` (for example `bash packaging/unix/run_app.sh`).

See [Installation, Running, and Packaging](docs/INSTALLATION.md) (and [Environment variables](docs/ENVIRONMENT.md)) for every supported platform, AI variants, production launch, Docker, viewer portals, and executable/package builds.

For code navigation, explore the [interactive architecture](https://jonasmarx3007.github.io/ProteomicsCoPYlot/).

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
| Local server (OpenAI-compatible) | a llama.cpp, vLLM or LM Studio server the operator allows, e.g. `http://host:8080/v1` (see [Installation](docs/INSTALLATION.md)) |
| OpenAI | `https://api.openai.com/v1/chat/completions` |
| Anthropic | `https://api.anthropic.com/v1/messages` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/models` |

When a cloud provider is selected, the request includes context derived from the loaded dataset,
such as condition-level summary statistics and top differential hits, not only the question that
was typed. Use Ollama or a local server for unpublished or otherwise sensitive
data.

Provide the key through `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` or `GEMINI_API_KEY` where
possible; a key set in the environment takes precedence over one entered in the interface and
is never transmitted from the browser.

Each model works at an assistant level (Basic, Standard or Advanced) that matches what it
handles reliably: small models take one small step at a time and answer with sentences the
application writes; large models may restyle a whole figure, apply Nature or Cell Press figure
specifications and write their own answers, whose numbers the application checks. The rules
are the same at every level; see [Installation](docs/INSTALLATION.md#assistant-levels).


### Saving work

Refreshing the analysis app starts a new analysis. After interaction, the browser
warns before refresh/close/navigation if analysis data or saved UI settings have
changed since the last successful save; cancelling leaves the current page intact.
The browser controls the wording and may suppress the dialog, especially on mobile,
so save important work explicitly (Ctrl+S exports the session state). Native file
writes establish the saved baseline only after completion. For ordinary downloads,
confirm that the file was downloaded; otherwise the warning remains active. Failed or
uncertain backend writes conservatively remain unsaved until saving again. Viewer mode
does not reset or show this analysis warning.

## Notebook package

Install the Python package from a checkout of this repository:

```bash
python -m pip install ".[bio]"
```

For development, install it editable instead (`python -m pip install -e ".[bio]"`) so changes
to `proteomicscopylot/` take effect without reinstalling. The `bio` extra adds Biopython for
FASTA-based sequence coverage.

Load the bundled HEK293 example with `load_example_data("protein")` (also `"phospho"`,
`"phosphoprotein"`, `"protein_metadata"` and `"phospho_metadata"`); the R functions provide
the same `load_example_data()`.

Install the optional R packages the R functions use:

```r
install.packages(c("arrow", "hexbin", "plotly", "readxl", "scatterplot3d", "VennDiagram"))
# VSN normalization (optional) comes from Bioconductor:
install.packages("BiocManager"); BiocManager::install("vsn")
```

Examples:

- `examples/example.ipynb`
- `examples/example.R`

The Python package, the R functions (`notebook_functions.R`, loaded with `source()`; it
is a script, not an installable R package) and the app support the same core analysis
workflows. Use the examples above for detailed usage and parameter choices.

### Notebook exports

Most plots and tables, and the report, can be downloaded as a ZIP that holds a Jupyter
notebook recreating them. Given the original upload, the notebook replays the recorded
preprocessing (normalization, filtering, localization cutoff and phosphosite collapse) and
checks that it reproduces the exact input matrix the app used. Outputs computed from
imputed data are the exception: the ZIP ships that exact imputed matrix together with the
imputation settings, and the random draws are not repeated. The last cell compares every
figure byte for byte with the one CoPYlot produced, which requires the package versions in
the ZIP's `requirements.txt` and the same fonts.

The installable package includes:

- `proteomicscopylot/notebook_functions.py`
- `proteomicscopylot/notebook_functions.R`
- `proteomicscopylot/example_data/`
- the human and mouse Gene Ontology reference tables

The Settings page reports whether `Rscript` is available. Detection checks explicit CoPYlot/R environment variables, `PATH`, and common platform installation locations.

## Architecture

- `backend/`: FastAPI routes, schemas, services, and runtime stores.
- `frontend/`: React/TypeScript UI and public assets.
- `proteomicscopylot/`: notebook APIs and canonical bundled example data.
- `examples/`: runnable notebook and R examples.
- `docs/`: installation and architectural guidance.
- `packaging/`: platform launchers and distribution builders.
- `deploy/`: hosting and reverse-proxy examples.
- `viewer_data/`: checked-in viewer examples and local/private project locations.
- `data/`: intentionally versioned biological reference resources.

See [Architecture](docs/ARCHITECTURE.md) for runtime flow and directory ownership.

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
please cite the original work alongside this software. This table is generated from
`backend/app/services/method_references.py`, the list the report and the manual cite from.

| Method | Where it is used | Reference |
| --- | --- | --- |
| Quantile normalization | Normalization across samples | Bolstad et al. (2003), [10.1093/bioinformatics/19.2.185](https://doi.org/10.1093/bioinformatics/19.2.185) |
| Variance-stabilizing normalization | Normalization delegated to Bioconductor vsn | Huber et al. (2002), [10.1093/bioinformatics/18.suppl_1.S96](https://doi.org/10.1093/bioinformatics/18.suppl_1.S96) |
| Low-quantile normal imputation (default) | Missing values drawn around a low quantile of the observed values, in the spirit of MinProb | Lazar et al. (2016), [10.1021/acs.jproteome.5b00981](https://doi.org/10.1021/acs.jproteome.5b00981) |
| Downshifted-normal imputation | Missing-value imputation, 'numerical' method (Perseus defaults) | Tyanova et al. (2016), [10.1038/nmeth.3901](https://doi.org/10.1038/nmeth.3901) |
| Student's t-test | Pooled-variance and paired volcano tests | Student (1908), [10.1093/biomet/6.1.1](https://doi.org/10.1093/biomet/6.1.1) |
| Welch's t-test | Unequal-variance volcano test | Welch (1947), [10.1093/biomet/34.1-2.28](https://doi.org/10.1093/biomet/34.1-2.28) |
| Benjamini-Hochberg false discovery rate | Multiple-testing correction | Benjamini & Hochberg (1995), [10.1111/j.2517-6161.1995.tb02031.x](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x) |
| Tukey HSD post-hoc test (Tukey-Kramer for unequal group sizes) | Pairwise comparisons after ANOVA | Tukey (1949); Kramer (1956), Biometrics 5:99-114; Biometrics 12:307-310 |
| Hypergeometric over-representation test | GO over-representation analysis | Rivals et al. (2007), [10.1093/bioinformatics/btl633](https://doi.org/10.1093/bioinformatics/btl633) |
| Gene Ontology | Term annotations for over-representation analysis | Ashburner et al. (2000); Gene Ontology Consortium (2023), [10.1038/75556](https://doi.org/10.1038/75556); [10.1093/genetics/iyad031](https://doi.org/10.1093/genetics/iyad031) |
| Class I phosphosite localization (probability >= 0.75) | Phosphosite coverage classes | Olsen et al. (2006), [10.1016/j.cell.2006.09.026](https://doi.org/10.1016/j.cell.2006.09.026) |
| Kinase-substrate specificity atlases | Kinase Library input preparation and result visualization | Johnson et al. (2023); Yaron-Barir et al. (2024), [10.1038/s41586-022-05575-3](https://doi.org/10.1038/s41586-022-05575-3); [10.1038/s41586-024-07407-y](https://doi.org/10.1038/s41586-024-07407-y) |
| UMAP | Sample embedding (optional) | McInnes et al. (2018), arXiv:1802.03426 |
| t-SNE | Sample embedding (optional) | van der Maaten & Hinton (2008), J. Mach. Learn. Res. 9:2579-2605 |

Kinase enrichment is calculated externally in the
[Kinase Library](https://kinase-library.phosphosite.org). CoPYlot prepares the
phosphosite input and visualizes the returned results.

## License

Proteomics CoPYlot code is distributed under [GNU GPL version 3](LICENSE).
See [NOTICE](NOTICE) for authorship and peptide-collapse credits.
Executable releases include corresponding source and third-party notices; distribute
the complete release ZIP rather than the executable alone. Bundled biological
reference data retain their upstream terms and attribution; see
[Biological reference data](data/db/README.md).

The bundled HEK293 demonstration dataset is released separately under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Its contents, checksums,
experimental design, and provenance are described in
[Example data](proteomicscopylot/example_data/README.md).

For citation metadata, see [CITATION.cff](CITATION.cff). Deployment security
requirements are covered in [Installation, Running, and Packaging](docs/INSTALLATION.md).
