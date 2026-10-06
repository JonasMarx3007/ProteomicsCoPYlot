# Tests

`pytest` (from the repository root) runs everything below. Each folder is also a
marker, so `pytest -m parity` or `pytest -m "not integration"` works too.

| Folder | What it checks |
|---|---|
| `unit/<area>/` | One function or module: `stats`, `data`, `qc`, `plots`, `report`, `phospho`, `peptide`, `assistant`, `security`, `restore`, `notebook`, `package` |
| `reference/` | Our numbers against an established implementation (scipy, statsmodels), with the reason in each docstring |
| `integration/api/`, `integration/viewer/` | Requests through the app, or a loaded viewer project, end to end |
| `parity/` | The web app, the pip package and the R package agree; R scripts they drive are in `parity/r/` |
| `contracts/` | The frontend and the backend agree: the generated API files are current, and the advanced plot settings reach the renderers |
| `repo/` | Repository layout, packaging and release hygiene |
| `fixtures/` | Test-owned data and configuration (see `fixtures/README.md`) |
| `r/` | The R package's own testthat tests (`Rscript tests/r/test_notebook_functions.R`) and `renv.lock` |

Shared fixtures live in `conftest.py`:

- `example_project`: the HEK293 example, loaded from `fixtures/viewer_config.json`;
- `client`: a TestClient on it;
- `qc_protein_data`: a small annotated matrix the QC routes can draw;
- `rscript` / `require_r`: Rscript for tests marked `requires_r(...)`.

Tests that run R are marked `@pytest.mark.requires_r("pkg", ...)`. They skip
when R or a package is missing, and fail instead with `COPYLOT_REQUIRE_R=1`.

## What is checked where

Tests check behaviour: they call the function, send the request, or mount the
component. None reads a source file to look for a string. Three other
mechanisms carry what is not behaviour:

- **Generated contracts.** `tools/export_openapi.py` (`npm --prefix frontend run
  generate:api`) writes the backend's OpenAPI schema and plot size limits to
  `frontend/src/lib/generated/`; the frontend's types are checked against them
  when `tsc` runs (`frontend/src/lib/apiContract.ts`) and the size controls read
  the limits directly. `contracts/test_generated_api_is_current.py` fails when
  the files are stale.
- **Component tests.** `frontend/tests/component/` and `frontend/tests/unit/`
  run on vitest in jsdom (`npm --prefix frontend test`), with the API mocked by
  `frontend/tests/component/apiMock.ts`.
- **Code-shape rules.** How code may be written -- one size row, no exception
  text in a response, every 500 logged -- is lint: `no-restricted-syntax` in
  `frontend/eslint.config.js`, and `tools/check_backend_rules.py` for the
  backend (run by `repo/test_backend_code_rules.py` and in CI).

Tables shared by two sides that cannot import each other are fixtures both
check against: `fixtures/pca_default_scaling.json`,
`fixtures/comparison_contrast.json`, `fixtures/assistant_plot_modules.json`.

`browser_server.py` and `docker_runtime_check.py` are tools, not tests: the
first serves the app for the Playwright tests in `frontend/tests/browser/`, the
second checks a built Docker image.
