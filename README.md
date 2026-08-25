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
- **AI variants:** analysis or viewer modes with a chat surface.

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
```

Examples:

- `examples/example.ipynb`
- `examples/example.R`

Notebook abundance, correlation, coverage, overlap, and completeness helpers
accept `data_scale="log2"` or `data_scale="linear"` (default: `"log2"`). A zero
is an observed value on the log2 scale and a non-detection on the linear scale;
`NA`/`NaN` is missing on both. Pass the scale explicitly when using linear/raw
matrices. Raw peptide/precursor report helpers and `log2_transform_data()` apply
the linear zero-to-missing rule at their input boundary.

`histo_int()`, `boxplot_int()`, `pca_plot()` and `correlation_xy_intensity()`
use whatever matrix they are given as-is. `cov_plot()` computes `CV = sd / mean`,
which is only meaningful on linear intensities, and therefore requires the
explicit argument `data_scale="linear"`. Omission and `data_scale="log2"` are
rejected; inverse-transform log2 data before calling it.

For notebook ORA, `different_genes(..., test_type=...)` selects genes from the
exact `volcano_data_f()` classifications. `different_genes_control()` does the
same for the corrected `volcano_data_f_control()` result. Both support
`unpaired`, `unpaired_welch`, `unpaired_moderated`, `paired`, and
`paired_moderated`; omitting `test_type` retains the older `paired` argument.

The installable package includes:

- `proteomicscopylot/notebook_functions.py`
- `proteomicscopylot/notebook_functions.R`
- `proteomicscopylot/example_data/`
- the Gene Ontology reference table used by `load_go_db()`

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
      "project": "GRK_project",
      "label": "GRK Project"
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

The nginx routing example is `deploy/nginx/proteomics-data.de.conf.example`.

## Development

Install development dependencies and run validation:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
npm.cmd --prefix frontend run build
npm.cmd --prefix frontend run lint
```

## Methods and citations

Several analyses re-implement or delegate to published methods. If you use them,
please cite the original work alongside this software.

| Method | Where it is used | Reference |
| --- | --- | --- |
| Empirical Bayes variance shrinkage (moderated *t*-test) | `unpaired_moderated` and `paired_moderated`; `squeeze_variance()`, `fit_variance_prior()`, `trigamma_inverse()` | Smyth (2004), [10.2202/1544-6115.1027](https://doi.org/10.2202/1544-6115.1027); Ritchie *et al.* (2015), [10.1093/nar/gkv007](https://doi.org/10.1093/nar/gkv007) |
| Quantile normalization | `normalize_data(method="quantile")`, a port of `limma::normalizeQuantiles` | Ritchie *et al.* (2015), [10.1093/nar/gkv007](https://doi.org/10.1093/nar/gkv007) |
| Downshifted-normal imputation | `impute_values(method="numerical")`, defaults `down_shift=1.8`, `width=0.3` | Tyanova *et al.* (2016), [10.1038/nmeth.3901](https://doi.org/10.1038/nmeth.3901) |
| Variance-stabilizing normalization | `normalize_data(method="vsn")`, delegated to Bioconductor `vsn` | Huber *et al.* (2002), [10.1093/bioinformatics/18.suppl_1.S96](https://doi.org/10.1093/bioinformatics/18.suppl_1.S96) |
| Benjamini–Hochberg false discovery rate | every `adj_pval` column | Benjamini & Hochberg (1995), [10.1111/j.2517-6161.1995.tb02031.x](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x) |
| Tukey–Kramer post-hoc | `anova_posthoc_data(post_hoc="tukey")` | Tukey (1949), *Biometrics* 5:99–114; Kramer (1956), *Biometrics* 12:307–310 |
| Kinase–substrate specificity atlases | `ksea_data_f()`, `ksea_volcano()` | Johnson *et al.* (2023), [10.1038/s41586-022-05575-3](https://doi.org/10.1038/s41586-022-05575-3); Yaron-Barir *et al.* (2024), [10.1038/s41586-024-07407-y](https://doi.org/10.1038/s41586-024-07407-y) |

Kinase enrichment is not computed here. `ksea_data_f()` prepares the site list
and `ksea_volcano()` plots the result; the enrichment itself is run in the
[Kinase Library](https://kinase-library.phosphosite.org), whose output columns
`Kinase`, `Log₂(Frequency Factor)` and `Adjusted p-value` are what
`ksea_volcano()` expects as input.

## License

Proteomics CoPYlot code is distributed under the [MIT License](LICENSE). Bundled biological
reference data retain their upstream terms and attribution; see
[Biological reference data](data/db/README.md).

The bundled HEK293 demonstration dataset is released separately under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) — see
[Example data](proteomicscopylot/example_data/README.md) for its contents,
checksums, experimental design, and provenance.

For citation metadata, see [CITATION.cff](CITATION.cff). Deployment security
requirements are covered in [Installation, Running, and Packaging](docs/INSTALLATION.md).
