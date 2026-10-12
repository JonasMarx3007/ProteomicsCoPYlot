# Architecture and Repository Map

## Interactive map

The [interactive map](architecture/index.html) connects frontend features, API
routes and Python services. Download the HTML and open it in a browser, or view
it on GitHub Pages after enabling publication. Search for a feature or endpoint,
then select a node to inspect its connections.

The map uses static source analysis, not runtime traces. Python links come from
imports and calls; frontend links are inferred from API paths and named imports.
Dynamic dispatch, indirect frontend wrappers and runtime-generated paths may be
missing. A link does not establish scientific correctness or test coverage.

### Regenerate

From the repository root, run:

```sh
python tools/build_architecture_map.py
```

Only versioned application source and the published API schema are read. Add new
source files to Git before regenerating. No application is started, no model is
called and no data is sent over the network. Python's standard library is enough;
the private Graphify installation and graph are not required or published.

The output contains repository-relative filenames, symbol names, API paths and
inferred connections. It excludes source bodies, docstrings, datasets, local
configuration and internal reports. A source fingerprint identifies the input
snapshot. Commit the regenerated HTML alongside relevant code changes.

### GitHub Pages

1. In repository **Settings > Pages**, select **GitHub Actions** as the source.
2. In **Settings > Secrets and variables > Actions > Variables**, add
   `PUBLISH_ARCHITECTURE_MAP` with the value `true`.
3. Run **Architecture map** from the Actions tab, or push to `main`.

The workflow rebuilds the map from that commit and publishes only the generated
HTML, never the repository or `local/`. Its deployment summary provides the live
URL. Without the variable, the workflow validates the map but does not deploy.
GitHub Pages availability depends on repository visibility and the account plan.

See [GitHub's Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Runtime flow

The React/TypeScript frontend calls FastAPI endpoints through `frontend/src/lib/api.ts`. Routes under `backend/app/api/` validate models from `backend/app/schemas/` and delegate analysis to `backend/app/services/`.

Dataset, metadata, viewer, and authentication state are session-scoped in backend stores. Browser-only presentation preferences use local storage and are included in saved UI state.

Plot output has two paths:

- interactive Plotly HTML responses;
- static Matplotlib/Seaborn images.

Advanced plot settings are serialized by the frontend and sent through the `advanced` request parameter.

## Repository ownership

- `backend/`: FastAPI application, schemas, services, and runtime state.
- `frontend/`: React UI plus public runtime assets and the manual: one PDF per page of the app and the complete book in `public/manuals/`, built from the manual's LaTeX sources and mapped to the pages in `src/lib/manualChapters.ts`.
- `proteomicscopylot/`: installable Python notebook API, the shared core (`_core.py`), the R functions (a script, not an installable R package), and canonical bundled example data.
- `examples/`: runnable Python notebook and R examples.
- `docs/`: installation, architecture, environment variables (`ENVIRONMENT.md`), and longer-lived project guidance.
- `packaging/`: launchers (`windows/`, and `unix/` for macOS and Linux) and distribution-build helpers.
- `deploy/`: reverse-proxy and hosting examples.
- `data/`: intentionally versioned biological reference databases and report assets.
- `viewer_data/`: public/example viewer projects; private projects belong under ignored local paths.

Root files are reserved for conventional tooling and true entry points: Git/Docker configuration, `pyproject.toml`, `launch*.py`, public viewer configuration templates, the license, and the main README.

## Request pipeline

Every request passes the same middleware, outermost first (`backend/app/main.py`
lists it where the middleware is registered, and
`tests/unit/security/test_middleware_order_and_session_gate.py` checks it):

1. **Host allowlist.** A request for an unknown `Host` is refused first.
2. **Gzip** of the finished response (JSON tables and HTML; PNG and ZIP responses declare
   `Content-Encoding: identity`, so the middleware leaves them alone).
3. **Tab sessions.** `/api/tabs/<id>/api/...` is rewritten before any path is read.
4. **Security headers**, on every response including refusals.
5. **CORS**, only when `COPYLOT_CORS_ORIGINS` is set.
6. **Session and authentication**, the viewer bootstrap, and the session's
   operation gate: a change to session data (`PUT`, `PATCH`, `DELETE` and the
   listed write `POST`s) waits for exclusive use of the session, a read shares
   it, and AI-provider calls take no gate. Gates are dropped when nobody holds or
   waits for them.
7. **Admission** of heavy work, then of AI-provider calls, counted per session.
8. **Plot download format and notices**, closest to the route. A notice a
   renderer records (for example "after VSN the CV plot uses the unnormalized
   data") reaches the browser in the `X-CoPYlot-Notice` header and is shown under
   the plot, never inside the figure or the report.

## Assistant

`backend/app/services/scientific_assistant.py` runs one step of a chat request; the
browser (`frontend/src/lib/runAssistant.ts`) applies the step's control changes through
the page's own handlers, re-reads the view and asks for the next step. The model plans;
the application resolves every change against the live, registered controls, computes
evidence and checks answers. How much a model may plan at once is its level
(`assistant_profiles.py`: Basic, Standard, Advanced, chosen from the user's setting, the
operator's list or automatic classification). Supporting modules:
`assistant_styling.py` (semantic style edits to controls), `assistant_plot_parts.py`
(what "the bars" are on each plot), `assistant_presets.py` (journal styles with
sources, colour-blind-safe palettes) and `assistant_prose.py` (number, name, colour and comparison checks
for answers Advanced models write themselves), `assistant_tools.py` (native tool calling: read-only
tools and finishing tools that become the same validated plan), `assistant_safety.py` (the pipeline
fence: filtering, normalization, imputation, transformation and the localization cutoff never reach
a model) and `assistant_progress.py` (phase and token count of a running step, polled by the browser).
In the browser, `lib/plotStyles.ts` saves a plot's look under a name and applies it to other plots. Providers live in `chat_tools.py` and,
for OpenAI-compatible local servers, `local_ai_server.py`.

## Memory and sessions

Each browser session has its own datasets, annotations and caches
(`COPYLOT_SESSION_ISOLATION=1`). Sessions are removed after
`COPYLOT_SESSION_IDLE_SECONDS`. When the number of sessions exceeds
`COPYLOT_MAX_SESSIONS`, or session data exceeds the server budget
(`COPYLOT_SERVER_MEMORY_MB`, default 60 % of RAM), empty sessions go first, then
the stalest sessions with data; the current session and any session active
within `COPYLOT_SESSION_PROTECT_SECONDS` are never removed for room.

A viewer project is loaded once per configuration file and modification time;
each visitor's session gets a copy that shares the read-only matrices (pandas
copy-on-write), so a hundred visitors do not hold a hundred copies of the data.
With pandas older than 3 (no copy-on-write) each session gets its own copy, but
the project is still read and parsed only once.

Interactive plots load the Plotly library once, from
`/api/runtime/plotly-<version>.js` (cached by the browser), instead of
embedding several megabytes in every figure. Figures downloaded as HTML still
embed it, so a downloaded file works offline.

## One copy of shared definitions

- **Arithmetic shared by the app and the pip package** lives in
  `proteomicscopylot/_core.py`: sample-name parsing, condition means, the
  constant-group check, feature scaling, Benjamini-Hochberg, the pooled and
  Welch-Satterthwaite standard errors and the two-sided t p-value. The backend
  loads that file through `app.services.copylot_core` (it does not import the
  pip package, which may be a different release); `notebook_functions.py`
  imports it as `._core`. Notebook exports stay self-contained: when their
  source is assembled, the definitions they use replace the `# <shared-core>`
  import block (`notebook_source.module_source`). The R functions keep their own copy,
  compared by the parity tests.
- **Method references** cited by the report, the README table and the manual
  come from `backend/app/services/method_references.py`.

## Notebook APIs

`proteomicscopylot/notebook_functions.py` and `proteomicscopylot/notebook_functions.R` intentionally expose broad notebook APIs as single source files. Their monolithic form supports simple sourcing/importing and cross-language discoverability. Do not split them solely to reduce line count. Refactor them only when a concrete correctness or maintainability benefit outweighs compatibility costs.

## What each implementation offers

The web app, the pip package (`notebook_functions.py`) and the R functions
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
- AI variants: the same modes with a chat surface backed by Ollama, a local OpenAI-compatible server (`app.services.local_ai_server`) or a cloud provider.

The root `launch.py` is the shared production launcher; `launch_tool.py` and `launch_viewer.py` are packaging entry points and remain at root intentionally.
