# Tests

`pytest` (from the repository root) runs everything below. Each folder is also a
marker, so `pytest -m parity` or `pytest -m "not integration"` works too.

| Folder | What it checks |
|---|---|
| `unit/<area>/` | One function or module: `stats`, `data`, `qc`, `plots`, `report`, `phospho`, `peptide`, `assistant`, `security`, `restore`, `notebook`, `package` |
| `reference/` | Our numbers against an established implementation (scipy, statsmodels), with the reason in each docstring |
| `integration/api/`, `integration/viewer/` | Requests through the app, or a loaded viewer project, end to end |
| `parity/` | The web app, the pip package and the R functions agree; R scripts they drive are in `parity/r/` |
| `contracts/` | The frontend and the backend agree: the generated API files are current, and the advanced plot settings reach the renderers |
| `repo/` | Repository layout, packaging and release hygiene |
| `fixtures/` | Test-owned data and configuration (see `fixtures/README.md`) |
| `r/` | The R functions' own testthat tests (`Rscript tests/r/test_notebook_functions.R`) and `renv.lock` |

Shared fixtures live in `conftest.py`:

- `example_project`: the HEK293 example, loaded from `fixtures/viewer_config.json`;
- `client`: a TestClient on it;
- `qc_protein_data`: a small annotated matrix the QC routes can draw;
- `rscript` / `require_r`: Rscript for tests marked `requires_r(...)`.

Tests that run R are marked `@pytest.mark.requires_r("pkg", ...)`. They skip
when R or a package is missing, and fail instead with `COPYLOT_REQUIRE_R=1`.

## What is checked where

Scientific and UI tests check behaviour: they call the function, send the
request, or mount the component. Repository checks also inspect manifests,
launchers and code structure where these are the contract being tested. Three
other mechanisms help keep the layers aligned:

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

## Keeping tests efficient without weakening them

- Use the Node environment for frontend tests of pure helpers; retain jsdom
  for components, storage and browser-dependent behaviour. Keep per-file
  isolation enabled.
- Share expensive, read-only reference results when several assertions use
  exactly the same inputs. Do not share mutable analysis state or replace
  standalone notebook execution with an in-process mock.
- The root `fresh_runtime_cache` fixture resets every session before and after
  each test. Additional resets are needed for changes *within* a test, not for
  duplicate setup/teardown fixtures.
- Close test-created figures after their assertions, including on failure.
- Mark individual R-dependent parameter cases with `requires_r`, not just
  whole functions. The R CI job selects this marker, and `COPYLOT_REQUIRE_R=1`
  makes a missing dependency fail. Use the `rscript`/`require_r` fixtures for
  the executable as well as prerequisite checking.
- Required Python dependencies must fail when missing, rather than silently
  skipping numerical-reference checks.
- Fixed scientific fixtures must fail if they stop exercising the intended
  result; empty output is not a reason to silently skip a reference comparison.

The suite uses two workers (`-n 2`, pytest-xdist, set in pyproject.toml) to
bound memory use. Larger machines can explicitly request `-n auto`;
each worker is a separate process with its own stores, so tests must not rely
on another test's state or on a fixed path outside `tmp_path`. `pytest -n 0`
runs serially. Measure Python runtime with `pytest --durations=40`. Keep the full CI matrix,
parameter cases, numerical tolerances and coverage floor intact when improving
setup costs; a shorter run achieved by silently selecting fewer checks is not
an equivalent optimization.
